"""RunStore：SQLite 快照往返、upsert 语义、状态推导、历史列表与跨实例持久化。"""

import sqlite3
from pathlib import Path

from core.services.store import RunStore

DAG = {
    "question": "公司2024年营业收入是多少？",
    "nodes": [{"node_id": "r1", "role": "retriever", "instruction": "检索", "query": "营收"}],
}
EVIDENCE = {
    "E1": {"doc_id": "d1", "quote": "营业收入 120 亿元", "score": 3.0, "channel": "local"},
}
DELIVERABLE = {
    "question": "公司2024年营业收入是多少？",
    "assertions": [{"text": "营业收入 120 亿元", "cites": ["E1"]}],
    "citations": [],
    "confidence": 0.9,
    "confidence_source": "formula",
    "degraded": False,
    "refused": False,
}


def _state(question: str = "公司2024年营业收入是多少？", deliverable=None, pending_human: bool = False) -> dict:
    return {
        "question": question,
        "round_no": 1,
        "node_results": {"r1": {"status": "done", "retrievals": [{"channel": "local", "hits": 1}]}},
        "verdict": {"verdict": "pass"},
        "deliverable": deliverable,
        "pending_human": pending_human,
        "dag": DAG,
        "evidence": EVIDENCE,
    }


def _store(tmp_path: Path) -> RunStore:
    return RunStore(tmp_path / "runs.db")


def _set_created_at(db_path: Path, run_id: str, created_at: str) -> None:
    with sqlite3.connect(str(db_path)) as conn:
        conn.execute("UPDATE runs SET created_at=? WHERE run_id=?", (created_at, run_id))


def test_save_then_get_round_trips_payload(tmp_path):
    store = _store(tmp_path)
    state = _state(deliverable=DELIVERABLE)

    store.save_run("run-1", state, session_id="s1")

    got = store.get_run("run-1")
    assert got == {
        "run_id": "run-1",
        "question": state["question"],
        "round_no": 1,
        "node_results": state["node_results"],
        "verdict": {"verdict": "pass"},
        "deliverable": DELIVERABLE,
        "pending_human": False,
        "dag": DAG,
        "evidence": EVIDENCE,
        "image_id": None,
        "food_items": [],
        "profile": None,
        "timings": [],
        "duration_ms": None,
    }
    assert got["node_results"]["r1"]["retrievals"][0]["channel"] == "local"
    assert store.get_run("missing") is None
    store.close()


def test_second_save_upserts_but_keeps_created_at(tmp_path):
    db_path = tmp_path / "runs.db"
    store = RunStore(db_path)
    store.save_run("run-1", _state(deliverable=None), session_id="s1")
    # 手动把 created_at 改成旧值，绕开同秒精度，验证 upsert 不覆盖
    _set_created_at(db_path, "run-1", "2020-01-01T00:00:00+00:00")

    updated = dict(DELIVERABLE, confidence=0.33, refused=True)
    store.save_run("run-1", _state(deliverable=updated), session_id="s1")

    rows = store.list_runs()
    assert len(rows) == 1
    row = rows[0]
    assert row["status"] == "done"
    assert row["confidence"] == 0.33
    assert row["refused"] == 1
    assert row["created_at"] == "2020-01-01T00:00:00+00:00"
    assert store.get_run("run-1")["deliverable"] == updated
    store.close()


def test_status_derivation(tmp_path):
    store = _store(tmp_path)
    store.save_run("done", _state(deliverable=DELIVERABLE))
    store.save_run("waiting", _state(pending_human=True))
    store.save_run("fresh", _state())
    # 人工断点优先于交付物
    store.save_run("gate", _state(deliverable=DELIVERABLE, pending_human=True))

    status = {r["run_id"]: r["status"] for r in store.list_runs()}
    assert status == {"done": "done", "waiting": "interrupted", "fresh": "running", "gate": "interrupted"}
    store.close()


def test_list_runs_orders_desc_limits_and_returns_summary(tmp_path):
    db_path = tmp_path / "runs.db"
    store = RunStore(db_path)
    for run_id in ("oldest", "middle", "newest"):
        store.save_run(run_id, _state(question=f"问题-{run_id}"), session_id="s1")
    _set_created_at(db_path, "oldest", "2020-01-01T00:00:00+00:00")
    _set_created_at(db_path, "middle", "2021-01-01T00:00:00+00:00")
    _set_created_at(db_path, "newest", "2022-01-01T00:00:00+00:00")

    ordered = store.list_runs()
    assert [r["run_id"] for r in ordered] == ["newest", "middle", "oldest"]
    # 摘要字段齐全
    assert {"run_id", "question", "status", "confidence", "refused", "created_at"} <= set(ordered[0])
    assert ordered[0]["question"] == "问题-newest"

    limited = store.list_runs(limit=2)
    assert [r["run_id"] for r in limited] == ["newest", "middle"]
    store.close()


def test_reopen_same_path_reads_persisted_run(tmp_path):
    db_path = tmp_path / "nested" / "runs.db"
    first = RunStore(db_path)
    first.save_run("run-1", _state(deliverable=DELIVERABLE))
    first.close()

    # 重新 new 一个实例打开同一路径：真持久化，不依赖进程内状态
    second = RunStore(db_path)
    got = second.get_run("run-1")
    assert got is not None
    assert got["deliverable"]["confidence"] == 0.9
    assert second.list_runs()[0]["run_id"] == "run-1"
    second.close()


def test_history_returns_recent_turns_in_order(tmp_path):
    store = _store(tmp_path)
    for i, question in enumerate(["第一问", "第二问", "第三问"]):
        store.save_run(f"run-{i}", _state(question=question, deliverable=DELIVERABLE), session_id="s1")
    store.save_run("other", _state(question="别的会话"), session_id="s2")

    history = store.history("s1", last=2)

    # 只取本会话最近两轮，且按时间正序回填给 planner
    assert [h["question"] for h in history] == ["第二问", "第三问"]
    assert history[0]["answer"] == "营业收入 120 亿元"
    assert history[0]["confidence"] == 0.9
    store.close()


def test_recent_food_names_falls_back_to_latest_photo(tmp_path):
    store = _store(tmp_path)
    state = _state("我之前吃过这些吗")
    state["food_items"] = [{"name": "甜玉米", "grams_low": 120}, {"name": "樱桃"}]
    store.save_run("photo", state, session_id="s1")
    store.save_run("follow-up", _state("那甜玉米呢"), session_id="s1")
    store.save_run("other", _state("别的会话"), session_id="s2")

    assert store.recent_food_names("s1") == ["甜玉米", "樱桃"]
    assert store.recent_food_names("s2") == []
    store.close()
