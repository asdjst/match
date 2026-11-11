"""直调 build_graph().invoke：用现成 fakes 验证图路径。"""

from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from adapters.llm.fake import FakeLLM
from adapters.retrieval.demo_corpus import build_demo_corpus
from adapters.retrieval.fake import FakeRetriever
from adapters.tools.fake import FakeTools
from core.graph.builder import build_graph


def _run(question):
    graph = build_graph(FakeLLM(), FakeRetriever(), FakeTools())
    state = {
        "session_id": "s1",
        "question": question,
        "trace_id": "t1",
        "round_no": 0,
        "evidence": {},
        "node_results": {},
    }
    return graph.invoke(state)


def test_factual_path_produces_cited_deliverable():
    out = _run("公司2024年营业收入是多少？")
    d = out["deliverable"]
    # 事实路径正常作答：不拒、引用非空、断言全带引用
    assert d["refused"] is False
    assert d["citations"]
    assert d["assertions"]
    assert all(a["cites"] for a in d["assertions"])
    # 路径应为 planner→retriever→analyst→critic→writer：无 executor 节点结果
    assert set(out["node_results"]) == {"r1", "analyst", "critic"}
    assert out["verdict"]["verdict"] == "pass"
    assert d["confidence"] > 0


def test_calc_path_creates_and_cites_tool_evidence():
    out = _run("2024年营业收入120亿元，2023年是100亿元，同比增长多少？")
    tool_evs = [e for e in out["evidence"].values() if e["doc_id"] == "tool"]
    # executor 产出工具计算证据，格式含 "工具计算" 与百分号结果
    assert len(tool_evs) == 1
    assert "工具计算" in tool_evs[0]["quote"]
    assert "20.0%" in tool_evs[0]["quote"]
    # 工具证据被断言引用并进入交付物引用表
    cited_ids = {c for a in out["assertions"] for c in a["cites"]}
    assert tool_evs[0]["evidence_id"] in cited_ids
    assert any(c["doc_id"] == "tool" for c in out["deliverable"]["citations"])
    assert out["deliverable"]["refused"] is False


def test_out_of_corpus_question_refuses():
    out = _run("公司2025年股价会涨到多少？")
    # 库外问题检索不到任何证据
    assert out["evidence"] == {}
    d = out["deliverable"]
    assert d["refused"] is True
    assert d["citations"] == []
    assert d["refusal_reason"]


def test_executor_blocked_when_fewer_than_two_numbers():
    # 只能检索到含一个年度数值的证据时 executor 应标记 blocked
    corpus = build_demo_corpus()[:1]
    graph = build_graph(FakeLLM(), FakeRetriever(corpus=corpus), FakeTools())
    out = graph.invoke(
        {
            "session_id": "s1",
            "question": "2024年营业收入120亿元，同比增长多少？",
            "trace_id": "t1",
            "round_no": 0,
            "evidence": {},
            "node_results": {},
        }
    )
    # 语料只有 doc1（120亿一个数值）→ x1 blocked 且没有工具证据
    assert out["node_results"]["x1"]["status"] == "blocked"
    assert all(e["doc_id"] != "tool" for e in out["evidence"].values())


def test_rounds_exhausted_pauses_for_human_then_resume():
    from core.schemas.agent import CriticOutput

    class SendBackLLM(FakeLLM):
        def complete(self, prompt, tier, schema=None):
            if schema is CriticOutput:
                return CriticOutput(verdict="send_back", issues=["证据支撑不足"], send_back_to="retriever")
            return super().complete(prompt, tier, schema)

    graph = build_graph(SendBackLLM(), FakeRetriever(), FakeTools(), checkpointer=MemorySaver())
    config = {"configurable": {"thread_id": "t-h1"}, "recursion_limit": 30}
    init = {
        "session_id": "s1",
        "question": "公司2024年营业收入是多少？",
        "trace_id": "t-h1",
        "round_no": 0,
        "evidence": {},
        "node_results": {},
    }
    out = graph.invoke(init, config)
    # 打回轮数用尽 → 图暂停在人工断点，无交付物
    assert out.get("__interrupt__")
    assert out.get("deliverable") is None
    res = graph.invoke(Command(resume=True), config)
    d = res["deliverable"]
    # 放行后输出兜底交付物：拒绝 + 降级标记 + 原因说明
    assert d["refused"] is True
    assert d["degraded"] is True
    assert "人工已放行" in d["refusal_reason"]


def test_critic_drops_positive_statements_from_issues():
    from core.graph.nodes.critic import _llm_review
    from core.schemas.agent import CriticOutput
    from core.schemas.deliverable import Assertion

    class StubLLM:
        def __init__(self, out):
            self._out = out

        def complete(self, prompt, tier=None, schema=None):
            return self._out

    assertion = Assertion(text="米饭碳水约 39g", cites=["E1"])
    positive = CriticOutput(
        verdict="send_back", issues=["引用编号均存在，证据支持断言"], send_back_to="retriever"
    )
    # 只有通过项/表扬 → 不构成打回理由
    assert _llm_review(StubLLM(positive), {"question": "q"}, {}, [assertion]) == ([], None)

    concrete = CriticOutput(
        verdict="send_back", issues=["断言中的 39g 在 E1 中查无对应数值"], send_back_to="retriever"
    )
    issues, target = _llm_review(StubLLM(concrete), {"question": "q"}, {}, [assertion])
    assert issues == ["断言中的 39g 在 E1 中查无对应数值"]
    assert target == "retriever"

    many = CriticOutput(
        verdict="send_back",
        issues=[f"第{i}条必须修改" for i in range(1, 8)],
        send_back_to="analyst",
    )
    # 每轮最多回传 5 条，避免一轮塞太多把分析员带偏
    issues, target = _llm_review(StubLLM(many), {"question": "q"}, {}, [assertion])
    assert len(issues) == 5
    assert target == "analyst"


def test_tidy_assertions_dedupes_and_caps():
    from core.graph.nodes.roles import MAX_ASSERTIONS, _tidy_assertions
    from core.schemas.deliverable import Assertion

    assertions = [
        Assertion(text="每天食盐不超过 5g", cites=["E20"]),
        Assertion(text="每天食盐不超过5克", cites=["E21"]),
    ] + [
        Assertion(text=f"第{i}条互不相同的建议", cites=["E1"]) for i in range(1, 10)
    ]

    kept = _tidy_assertions(assertions)

    # 同义重复的盐句子只留第一条，总数封顶 7
    assert len(kept) == MAX_ASSERTIONS
    assert kept[0].cites == ["E20"]
    assert all("克" not in a.text for a in kept[1:])


def test_analyst_receives_previous_critic_issues():
    from core.graph.nodes.roles import make_analyst
    from core.schemas.agent import AnalystOutput
    from core.schemas.dag import TaskDAG

    class CaptureLLM:
        def __init__(self):
            self.prompt = None

        def complete(self, prompt, tier=None, schema=None):
            self.prompt = prompt
            return AnalystOutput(assertions=[])

    llm = CaptureLLM()
    state = {
        "dag": TaskDAG(question="吃这个需要注意什么？").model_dump(),
        "question": "吃这个需要注意什么？",
        "evidence": {},
        "verdict": {"verdict": "send_back", "issues": ["删掉重复的盐句子", "说明莲藕按主食算"]},
    }

    make_analyst(llm)(state)

    # 审校意见必须进入下一轮分析员任务，否则 send_back 只是白跑一次检索
    assert "上一轮审校意见" in llm.prompt.task
    assert "删掉重复的盐句子" in llm.prompt.task
    assert "说明莲藕按主食算" in llm.prompt.task


def test_send_back_to_analyst_routes_back_to_analyst():
    from core.graph.builder import _after_critic
    from core.schemas.dag import TaskDAG

    state = {
        "dag": TaskDAG(question="q").model_dump(),
        "round_no": 1,
        "verdict": {"verdict": "send_back", "issues": ["与前文重复"], "send_back_to": "analyst"},
    }
    assert _after_critic(state) == "analyst"
    # 未给目标时仍回到检索
    state["verdict"] = {"verdict": "send_back", "issues": ["证据缺失"]}
    assert _after_critic(state) == "retriever"

