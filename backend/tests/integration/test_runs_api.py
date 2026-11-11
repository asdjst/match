"""集成：runs 列表持久化与进程内缓存清空后的任务回查。"""

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from infra.config import Settings

STATE = {
    "question": "公司2024年营业收入是多少？",
    "round_no": 1,
    "node_results": {"r1": {"status": "done"}},
    "verdict": {"verdict": "pass"},
    "deliverable": {
        "question": "公司2024年营业收入是多少？",
        "assertions": [],
        "citations": [],
        "confidence": 0.9,
        "confidence_source": "formula",
        "degraded": False,
        "refused": False,
    },
    "pending_human": False,
    "dag": {"question": "公司2024年营业收入是多少？", "nodes": []},
    "evidence": {},
}


@pytest.fixture()
def app(tmp_path):
    # db_path 指向 tmp_path，避免污染默认库
    return create_app(Settings(mode="fake", db_path=str(tmp_path / "runs.db")))


@pytest.fixture()
def client(app):
    return TestClient(app)


def test_list_runs_empty_then_lists_saved_run(app, client):
    empty = client.get("/api/runs")
    assert empty.status_code == 200
    assert empty.json() == {"runs": []}

    app.state.store.save_run("run-1", STATE, session_id="s1", question=STATE["question"])

    resp = client.get("/api/runs")
    assert resp.status_code == 200
    body = resp.json()
    assert [r["run_id"] for r in body["runs"]] == ["run-1"]
    assert body["runs"][0]["status"] == "done"
    assert body["runs"][0]["confidence"] == 0.9
    # limit 参数透传
    assert client.get("/api/runs", params={"limit": 1}).json()["runs"]


def test_task_lookup_falls_back_to_store_after_cache_cleared(app, client):
    app.state.store.save_run("run-2", STATE, session_id="s1", question=STATE["question"])
    app.state.runs.clear()

    resp = client.get("/api/tasks/run-2")

    assert resp.status_code == 200
    body = resp.json()
    assert set(body) == {
        "run_id",
        "session_id",
        "created_at",
        "question",
        "round_no",
        "node_results",
        "verdict",
        "deliverable",
        "pending_human",
        "dag",
        "evidence",
        "image_id",
        "food_items",
        "profile",
        "timings",
        "duration_ms",
    }
    assert body["run_id"] == "run-2"
    assert body["session_id"] == "s1"
    assert body["created_at"]
    assert body["question"] == STATE["question"]
    assert body["deliverable"]["confidence"] == 0.9
    assert body["node_results"] == {"r1": {"status": "done"}}

    # 缓存与库里都没有的任务仍是 404
    assert client.get("/api/tasks/no-such-run").status_code == 404


class _StubGraph:
    """替身图：放行后直接返回兜底交付物，验证 approve 走的是落库快照 + 图恢复。"""

    async def ainvoke(self, command, config):
        return {
            "deliverable": {
                "question": STATE["question"],
                "assertions": [],
                "citations": [],
                "confidence": 0.5,
                "confidence_source": "formula",
                "degraded": True,
                "refused": True,
                "refusal_reason": "已达最大打回轮数（3），人工已放行，输出兜底结论",
            }
        }


def test_approve_works_after_cache_cleared(app, client):
    pending = {**STATE, "deliverable": None, "pending_human": True}
    app.state.store.save_run("run-3", pending, session_id="s1", question=STATE["question"])
    app.state.runs.clear()  # 模拟进程重启：内存里没有这条 run
    app.state.graph = _StubGraph()

    resp = client.post("/api/tasks/run-3/approve")

    assert resp.status_code == 200
    assert resp.json()["deliverable"]["refused"] is True
    snap = app.state.store.get_run("run-3")
    assert snap["pending_human"] is False
    assert snap["deliverable"]["confidence"] == 0.5


def test_approve_rejects_run_that_is_not_pending(app, client):
    app.state.store.save_run("run-4", STATE, session_id="s1", question=STATE["question"])
    app.state.runs.clear()

    resp = client.post("/api/tasks/run-4/approve")

    assert resp.status_code == 409
