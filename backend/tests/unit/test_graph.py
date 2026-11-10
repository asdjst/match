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
