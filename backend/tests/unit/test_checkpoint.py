"""断点跨进程存活：进程内 MemorySaver 换成 SQLite 后，新图实例仍能放行旧断点。"""

import pytest
from langgraph.checkpoint.memory import MemorySaver
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.types import Command

from adapters.llm.fake import FakeLLM
from adapters.retrieval.fake import FakeRetriever
from adapters.tools.fake import FakeTools
from core.graph.builder import build_graph
from core.schemas.agent import CriticOutput


class SendBackLLM(FakeLLM):
    """审校永远打回 → 打回轮数用尽后挂在 writer 人工断点。"""

    def complete(self, prompt, tier, schema=None):
        if schema is CriticOutput:
            return CriticOutput(verdict="send_back", issues=["证据支撑不足"], send_back_to="retriever")
        return super().complete(prompt, tier, schema)


INIT = {
    "session_id": "s1",
    "question": "一碗米饭大概多少碳水？",
    "trace_id": "t-ckpt",
    "round_no": 0,
    "evidence": {},
    "node_results": {},
}
CONFIG = {"configurable": {"thread_id": "t-ckpt"}, "recursion_limit": 30}


@pytest.mark.asyncio
async def test_interrupt_survives_new_saver_instance(tmp_path):
    db = tmp_path / "checkpoints.db"

    async with AsyncSqliteSaver.from_conn_string(str(db)) as saver:
        graph = build_graph(SendBackLLM(), FakeRetriever(), FakeTools(), checkpointer=saver)
        out = await graph.ainvoke(INIT, CONFIG)
        assert out.get("__interrupt__")
        assert out.get("deliverable") is None

    # 模拟进程重启：旧 saver/graph 全部丢弃，只留磁盘上的 checkpoints.db
    async with AsyncSqliteSaver.from_conn_string(str(db)) as saver:
        graph = build_graph(SendBackLLM(), FakeRetriever(), FakeTools(), checkpointer=saver)
        resumed = await graph.ainvoke(Command(resume=True), CONFIG)

    deliverable = resumed["deliverable"]
    assert deliverable["refused"] is True
    assert deliverable["degraded"] is True
    assert "人工已放行" in deliverable["refusal_reason"]


@pytest.mark.asyncio
async def test_memory_saver_cannot_resume_from_a_different_instance():
    # 对照：进程内 saver 换实例即丢断点，这是本次改成 SQLite 的原因
    graph = build_graph(SendBackLLM(), FakeRetriever(), FakeTools(), checkpointer=MemorySaver())
    out = await graph.ainvoke(INIT, CONFIG)
    assert out.get("__interrupt__")

    fresh = build_graph(SendBackLLM(), FakeRetriever(), FakeTools(), checkpointer=MemorySaver())
    with pytest.raises(Exception):
        await fresh.ainvoke(Command(resume=True), CONFIG)
