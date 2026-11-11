"""W4.4 降级演练（单测口径）：模型挂 → 缓存证据兜底；检索挂 → 证据为空则拒答式降级。"""

import json

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from infra.config import Settings


@pytest.fixture()
def client(tmp_path):
    return TestClient(create_app(Settings(mode="fake", db_path=str(tmp_path / "runs.db"))))


def _deliverable(events):
    ds = [e for e in events if e["type"] == "deliverable"]
    assert len(ds) == 1, f"应有 deliverable 事件，实际：{[e['type'] for e in events]}"
    return ds[0]["deliverable"]


def _chat(client, question):
    resp = client.post("/api/chat", json={"session_id": "s1", "question": question})
    return [json.loads(l[len("data: "):]) for l in resp.text.splitlines() if l.startswith("data: ")]


def test_degraded_with_cached_evidence_when_analyst_down(client, monkeypatch):
    from adapters.llm.fake import FakeLLM

    real = FakeLLM.complete

    def analyst_down(self, prompt, tier, schema=None):
        if prompt.role == "analyst":
            raise ConnectionError("LLM 网关不可达")
        return real(self, prompt, tier, schema)

    monkeypatch.setattr(FakeLLM, "complete", analyst_down)
    events = _chat(client, "公司2024年营业收入是多少？")
    d = _deliverable(events)
    snapshot = client.get(f"/api/tasks/{events[0]['run_id']}").json()
    assert "ConnectionError" in snapshot["error"]
    assert [e["node"] for e in snapshot["node_events"]] == ["planner", "retriever"]
    assert any(e.get("node") == "analyst" and e["status"] == "running" for e in events)
    assert client.app.state.store.get_run(events[0]["run_id"])["error"] == snapshot["error"]
    # 规划/检索已产出证据 → 模板兜底不拒答，但必须降级 + 免责声明 + 引用
    assert d["degraded"] is True
    assert d["refused"] is False
    assert d["confidence"] == 0.0
    assert d["citations"]
    assert "降级" in d["refusal_reason"]
    assert "未经完整审校" in d["refusal_reason"]


def test_refused_style_degrade_when_retriever_down(client, monkeypatch):
    from adapters.retrieval.fake import FakeRetriever

    def recall_down(self, query, filters=None):
        raise ConnectionError("R2R 不可达")

    monkeypatch.setattr(FakeRetriever, "recall", recall_down)
    events = _chat(client, "公司2024年营业收入是多少？")
    d = _deliverable(events)
    snapshot = client.get(f"/api/tasks/{events[0]['run_id']}").json()
    assert [e["node"] for e in snapshot["node_events"]] == ["planner"]
    assert "ConnectionError" in snapshot["error"]
    # 无任何证据 → 降级且拒答式兜底
    assert d["degraded"] is True
    assert d["refused"] is True
    assert "无可用证据" in d["refusal_reason"]


def test_executor_tool_timeout_marks_blocked():
    from adapters.llm.fake import FakeLLM
    from adapters.retrieval.fake import FakeRetriever
    from adapters.tools.fake import FakeTools
    from core.graph.builder import build_graph

    class TimeoutTools(FakeTools):
        def call(self, name, args):
            return {"ok": False, "error": "timeout"}

    graph = build_graph(FakeLLM(), FakeRetriever(), TimeoutTools())
    out = graph.invoke(
        {
            "session_id": "s1",
            "question": "2024年营业收入120亿元，2023年是100亿元，同比增长多少？",
            "trace_id": "t1",
            "round_no": 0,
            "evidence": {},
            "node_results": {},
        }
    )
    # 工具超时不炸图：executor blocked，走无工具证据路径
    assert out["node_results"]["x1"]["status"] == "blocked"
    assert "timeout" in out["node_results"]["x1"]["block_reason"]
    assert out["deliverable"]["refused"] is False
