import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    run_id      TEXT PRIMARY KEY,
    session_id  TEXT NOT NULL DEFAULT '',
    question    TEXT NOT NULL DEFAULT '',
    status      TEXT NOT NULL DEFAULT 'running',
    confidence  REAL,
    refused     INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL,
    payload     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_runs_created ON runs(created_at DESC);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class RunStore:
    """SQLite 持久化：run 全量快照（含 node_results 里的检索记录）+ 历史列表。
    进程重启后 GET /api/tasks 仍可回查；WAL 模式，单文件零运维。"""

    def __init__(self, path: str | Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(_SCHEMA)

    def save_run(self, run_id: str, state: dict, session_id: str = "", question: str = "") -> None:
        deliverable = state.get("deliverable") or {}
        status = (
            "interrupted" if state.get("pending_human")
            else "done" if deliverable
            else "running"
        )
        payload = {
            "run_id": run_id,
            "question": state.get("question", question),
            "round_no": state.get("round_no", 0),
            "node_results": state.get("node_results", {}),
            "verdict": state.get("verdict"),
            "deliverable": deliverable or None,
            "pending_human": state.get("pending_human", False),
            "dag": state.get("dag"),
            "evidence": state.get("evidence", {}),
        }
        now = _now()
        # 首次写入用 created_at=now，后续 upsert 保留原 created_at
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO runs (run_id, session_id, question, status, confidence, refused, created_at, updated_at, payload)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(run_id) DO UPDATE SET
                    status=excluded.status, confidence=excluded.confidence,
                    refused=excluded.refused, updated_at=excluded.updated_at, payload=excluded.payload
                """,
                (
                    run_id,
                    session_id,
                    payload["question"] or "",
                    status,
                    deliverable.get("confidence"),
                    1 if deliverable.get("refused") else 0,
                    now,
                    now,
                    json.dumps(payload, ensure_ascii=False, default=str),
                ),
            )
            self._conn.commit()

    def get_run(self, run_id: str) -> dict | None:
        with self._lock:
            row = self._conn.execute("SELECT payload FROM runs WHERE run_id=?", (run_id,)).fetchone()
        return json.loads(row["payload"]) if row else None

    def list_runs(self, limit: int = 50) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                """SELECT run_id, session_id, question, status, confidence, refused, created_at
                   FROM runs ORDER BY created_at DESC LIMIT ?""",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]

    def close(self) -> None:
        with self._lock:
            self._conn.close()
