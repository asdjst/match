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
        "question",
        "round_no",
        "node_results",
        "verdict",
        "deliverable",
        "pending_human",
        "dag",
        "evidence",
    }
    assert body["run_id"] == "run-2"
    assert body["question"] == STATE["question"]
    assert body["deliverable"]["confidence"] == 0.9
    assert body["node_results"] == {"r1": {"status": "done"}}

    # 缓存与库里都没有的任务仍是 404
    assert client.get("/api/tasks/no-such-run").status_code == 404
