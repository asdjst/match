"""直调 build_graph().invoke：用现成 fakes 验证图路径。"""

import pytest

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


@pytest.mark.asyncio
async def test_node_start_is_live_and_timing_excludes_preparation_and_stream_delay(monkeypatch):
    import asyncio
    import threading
    from types import SimpleNamespace
    from langgraph.graph import END, StateGraph
    from core.graph import builder
    from core.graph.events import NodeEventLog
    from core.graph.state import GraphState

    clock = [10.0]
    monkeypatch.setattr(builder, "time", SimpleNamespace(monotonic=lambda: clock[0]))
    release = threading.Event()
    finished = threading.Event()

    def planner(state):
        assert release.wait(timeout=5), "start event was not delivered while the node was running"
        clock[0] += 0.125
        finished.set()
        return {"round_no": state["round_no"], "dag": {"nodes": []}}

    g = StateGraph(GraphState)
    g.add_node("planner", builder._report_node("planner", planner))
    g.set_entry_point("planner")
    g.add_edge("planner", END)
    graph = g.compile()
    clock[0] += 60  # Preparation is not node execution.
    log = NodeEventLog()
    stream = graph.astream({"round_no": 2}, stream_mode=["custom", "updates"])
    try:
        mode, payload = await asyncio.wait_for(anext(stream), timeout=5)
        assert mode == "custom"
        assert log.custom(payload)["status"] == "running"
        assert not finished.is_set()
    finally:
        release.set()
    async for mode, payload in stream:
        if mode == "custom":
            log.custom(payload)
        else:
            clock[0] += 120  # Consumer latency must not inflate elapsed_ms either.
            done = log.done("planner")
    assert done["elapsed_ms"] == 125
    assert done["round_no"] == 2
    assert done["summary"] == "已完成任务规划，生成 0 项任务。"
    assert log.snapshot({})["node_events"] == [done]
    # get_stream_writer remains a no-op for ordinary async invocation.
    assert (await graph.ainvoke({"round_no": 3}))["round_no"] == 3


def test_summaries_exclude_prior_pool_and_skipped_results():
    from core.graph.events import node_summary

    old_result = {"status": "done", "evidence_used": ["E1"], "retrievals": [{"channel": "local", "hits": 9, "status": "ok"}]}
    before = {
        "dag": {"nodes": [{"node_id": "r1", "role": "retriever"}]},
        "node_results": {"r1": old_result},
        "evidence": {"E1": {"channel": "local"}, "E2": {"channel": "image"}, "E3": {"channel": "memory"}},
    }
    delta = {"node_results": {"r1": old_result}, "evidence": dict(before["evidence"])}
    summary = node_summary("retriever", delta, {**before, **delta}, before)
    assert "新增 0 条" in summary and "跳过 1 项" in summary
    assert "9" not in summary and "通道命中" not in summary
    # A freshly replaced but equal result is a genuine repeat, not a skipped task.
    delta["node_results"]["r1"] = dict(old_result)
    summary = node_summary("retriever", delta, {**before, **delta}, before)
    assert "新增 0 条" in summary and "本地库 9 条" in summary
    assert "跳过" not in summary


def test_executor_summary_counts_partial_calls_and_only_safe_numeric_results():
    from core.graph.events import node_summary

    specs = [
        {"node_id": "x1", "role": "executor", "tool": "calculate_gl"},
        {"node_id": "x2", "role": "executor", "tool": "growth_rate"},
        {"node_id": "x3", "role": "executor", "tool": "growth_rate"},
    ]
    old = {"status": "done", "output": {"result": 99, "unit": "%"}}
    before = {"dag": {"nodes": specs}, "node_results": {"x3": old}}
    delta = {"node_results": {
        "x1": {"status": "done", "output": {"calls": [
            {"tool": "calculate_gl", "ok": True, "result": 12.5, "source": "DO_NOT_LEAK"},
            {"tool": "query_food_nutrition", "ok": False, "error": "DO_NOT_LEAK"},
        ]}},
        "x2": {"status": "blocked", "block_reason": "DO_NOT_LEAK"},
        "x3": old,
    }}
    summary = node_summary("executor", delta, {**before, **delta}, before)
    assert "成功 1 次" in summary and "失败记录 1 次" in summary
    assert "阻塞 1 项、跳过 1 项" in summary
    assert "GL 估算值 12.5" in summary
    assert "99" not in summary and "DO_NOT_LEAK" not in summary


def test_analyst_summary_uses_current_assertions_without_exposing_claims():
    from core.graph.events import node_summary

    before = {"assertions": [{"cites": ["OLD"]}]}
    delta = {"assertions": [
        {"text": "DO_NOT_LEAK", "cites": ["E1", "E1"]},
        {"text": "DO_NOT_LEAK", "cites": ["E1", "E2"]},
    ]}
    assert node_summary("analyst", delta, {**before, **delta}, before) == "本轮分析形成 2 条断言，引用 2 个不同证据编号。"
    assert node_summary("analyst", {"assertions": []}, before, before) == "本轮分析形成 0 条断言，引用 0 个不同证据编号。"


@pytest.mark.parametrize("deliverable, expected", [
    ({"refused": False}, "已生成交付物。"),
    ({"refused": True}, "已生成拒答结果，未给出正常结论。"),
    ({"degraded": True}, "已生成降级交付物，不作为完整流程的正常交付。"),
    ({"degraded": True, "refused": True}, "已生成拒答式降级交付物。"),
])
def test_writer_summaries_reflect_actual_disposition(deliverable, expected):
    from core.graph.events import node_summary

    delta = {"deliverable": deliverable}
    assert node_summary("writer", delta, delta, {}) == expected

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

