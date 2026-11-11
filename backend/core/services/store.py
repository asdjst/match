import json
import sqlite3
import threading
import uuid
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

CREATE TABLE IF NOT EXISTS meal_logs (
    meal_id       TEXT PRIMARY KEY,
    user_id       TEXT NOT NULL DEFAULT 'local',
    eaten_at      TEXT NOT NULL,
    meal_type     TEXT NOT NULL DEFAULT '午餐',
    foods         TEXT NOT NULL DEFAULT '[]',
    carbs_g       REAL,
    gl            REAL,
    note          TEXT NOT NULL DEFAULT '',
    source        TEXT NOT NULL DEFAULT 'manual',
    image_id      TEXT,
    insulin_note  TEXT NOT NULL DEFAULT '',
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_meals_user_time ON meal_logs(user_id, eaten_at DESC);

CREATE TABLE IF NOT EXISTS glucose_readings (
    reading_id     TEXT PRIMARY KEY,
    meal_id        TEXT NOT NULL,
    measured_at    TEXT NOT NULL,
    minutes_after  INTEGER NOT NULL DEFAULT 120,
    value_mmol     REAL NOT NULL,
    source         TEXT NOT NULL DEFAULT 'manual',
    created_at     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_glucose_meal ON glucose_readings(meal_id);
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
            "image_id": state.get("image_id"),
            "food_items": state.get("food_items", []),
            "profile": state.get("profile"),
            # 各图节点耗时与整轮总耗时：用于定位慢在检索还是模型
            "timings": state.get("timings", []),
            "duration_ms": state.get("duration_ms"),
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

    def get_run(self, run_id: str, with_session: bool = False) -> dict | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT session_id, created_at, payload FROM runs WHERE run_id=?", (run_id,)
            ).fetchone()
        if row is None:
            return None
        payload = json.loads(row["payload"])
        # payload 里没存会话元信息，回放历史会话时从列上补回来
        if with_session:
            payload.setdefault("session_id", row["session_id"])
            payload.setdefault("created_at", row["created_at"])
        return payload

    def list_runs(self, limit: int = 50) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                """SELECT run_id, session_id, question, status, confidence, refused, created_at
                   FROM runs ORDER BY created_at DESC LIMIT ?""",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]

    def history(self, session_id: str, last: int = 3) -> list[dict]:
        """会话内最近 last 轮问答（时间正序）：进程重启后给规划器回填多轮上下文。"""
        from core.services.memory import answer_snippet

        with self._lock:
            rows = self._conn.execute(
                """SELECT question, payload FROM runs
                   WHERE session_id=? ORDER BY created_at DESC, rowid DESC LIMIT ?""",
                (session_id, last),
            ).fetchall()
        items: list[dict] = []
        for row in reversed(rows):
            payload = json.loads(row["payload"])
            deliverable = payload.get("deliverable") or {}
            items.append({
                "question": payload.get("question") or row["question"],
                "answer": answer_snippet(deliverable),
                "confidence": deliverable.get("confidence"),
            })
        return items

    def recent_food_names(self, session_id: str, last: int = 5) -> list[str]:
        """本会话最近一次拍照识别出的食物名：给“我之前吃过这个吗”这类追问补齐指代。"""
        with self._lock:
            rows = self._conn.execute(
                """SELECT payload FROM runs
                   WHERE session_id=? ORDER BY created_at DESC, rowid DESC LIMIT ?""",
                (session_id, last),
            ).fetchall()
        for row in rows:
            payload = json.loads(row["payload"])
            names = [
                str(item.get("name") or "").strip()
                for item in payload.get("food_items") or []
                if str(item.get("name") or "").strip()
            ]
            if names:
                return names
        return []

    def close(self) -> None:
        with self._lock:
            self._conn.close()


def _sum_carbs(foods: list[dict]) -> float | None:
    values = [float(f.get("carbs_g")) for f in foods if f.get("carbs_g") is not None]
    return round(sum(values), 1) if values else None


def _sum_gl(foods: list[dict]) -> float | None:
    values = [float(f.get("gl")) for f in foods if f.get("gl") is not None]
    return round(sum(values), 1) if values else None


def _foods_json(foods: list[dict]) -> str:
    clean = [
        {
            "name": str(f.get("name", "")).strip()[:40],
            "grams": float(f.get("grams") or 0),
            "carbs_g": None if f.get("carbs_g") is None else float(f.get("carbs_g")),
            "gl": None if f.get("gl") is None else float(f.get("gl")),
        }
        for f in foods
        if str(f.get("name", "")).strip()
    ]
    return json.dumps(clean, ensure_ascii=False)


class MealStore:
    """餐食与血糖记录：问答召回个人历史的结构化来源，独立于 run 快照。"""

    def __init__(self, path: str | Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(_SCHEMA)

    def add_meal(
        self,
        user_id: str,
        eaten_at: str,
        meal_type: str,
        foods: list[dict],
        note: str = "",
        source: str = "manual",
        image_id: str | None = None,
        insulin_note: str = "",
    ) -> dict:
        meal_id = uuid.uuid4().hex[:12]
        now = _now()
        with self._lock:
            self._conn.execute(
                """INSERT INTO meal_logs
                   (meal_id, user_id, eaten_at, meal_type, foods, carbs_g, gl, note, source,
                    image_id, insulin_note, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    meal_id,
                    user_id,
                    eaten_at,
                    meal_type,
                    _foods_json(foods),
                    _sum_carbs(foods),
                    _sum_gl(foods),
                    note,
                    source,
                    image_id,
                    insulin_note,
                    now,
                    now,
                ),
            )
            self._conn.commit()
        return self.get_meal(meal_id) or {}

    def get_meal(self, meal_id: str) -> dict | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM meal_logs WHERE meal_id=?", (meal_id,)
            ).fetchone()
            if row is None:
                return None
            readings = self._conn.execute(
                "SELECT * FROM glucose_readings WHERE meal_id=? ORDER BY measured_at, minutes_after",
                (meal_id,),
            ).fetchall()
        return self._to_meal(row, readings)

    def list_meals(self, user_id: str, limit: int = 50) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                """SELECT * FROM meal_logs WHERE user_id=?
                   ORDER BY eaten_at DESC, created_at DESC LIMIT ?""",
                (user_id, max(1, min(limit, 200))),
            ).fetchall()
            if not rows:
                return []
            placeholders = ",".join("?" for _ in rows)
            readings = self._conn.execute(
                f"SELECT * FROM glucose_readings WHERE meal_id IN ({placeholders})"
                " ORDER BY measured_at, minutes_after",
                tuple(r["meal_id"] for r in rows),
            ).fetchall()
        by_meal: dict[str, list] = {}
        for r in readings:
            by_meal.setdefault(r["meal_id"], []).append(r)
        return [self._to_meal(row, by_meal.get(row["meal_id"], [])) for row in rows]

    def update_meal(self, meal_id: str, patch: dict) -> dict | None:
        fields: list[str] = []
        values: list[object] = []
        for key in ("eaten_at", "meal_type", "note", "source", "insulin_note"):
            if key in patch:
                fields.append(f"{key}=?")
                values.append(patch[key])
        if "foods" in patch:
            foods = patch["foods"] or []
            fields += ["foods=?", "carbs_g=?", "gl=?"]
            values += [_foods_json(foods), _sum_carbs(foods), _sum_gl(foods)]
        if not fields:
            return self.get_meal(meal_id)
        fields.append("updated_at=?")
        values += [_now(), meal_id]
        action = "UPDATE meal_logs SET " + ", ".join(fields) + " WHERE meal_id=?"
        with self._lock:
            cur = self._conn.execute(action, tuple(values))
            self._conn.commit()
        return self.get_meal(meal_id) if cur.rowcount else None

    def delete_meal(self, meal_id: str) -> bool:
        with self._lock:
            self._conn.execute("DELETE FROM glucose_readings WHERE meal_id=?", (meal_id,))
            cur = self._conn.execute("DELETE FROM meal_logs WHERE meal_id=?", (meal_id,))
            self._conn.commit()
        return bool(cur.rowcount)

    def add_glucose(
        self,
        meal_id: str,
        value_mmol: float,
        minutes_after: int = 120,
        measured_at: str | None = None,
        source: str = "manual",
    ) -> dict | None:
        if self.get_meal(meal_id) is None:
            return None
        reading_id = uuid.uuid4().hex[:12]
        measured_at = measured_at or _now()
        with self._lock:
            self._conn.execute(
                """INSERT INTO glucose_readings
                   (reading_id, meal_id, measured_at, minutes_after, value_mmol, source, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (reading_id, meal_id, measured_at, minutes_after, value_mmol, source, _now()),
            )
            self._conn.commit()
            row = self._conn.execute(
                "SELECT * FROM glucose_readings WHERE reading_id=?", (reading_id,)
            ).fetchone()
        return dict(row) if row else None

    def delete_glucose(self, meal_id: str, reading_id: str) -> bool:
        with self._lock:
            cur = self._conn.execute(
                "DELETE FROM glucose_readings WHERE meal_id=? AND reading_id=?",
                (meal_id, reading_id),
            )
            self._conn.commit()
        return bool(cur.rowcount)

    @staticmethod
    def _to_meal(row: sqlite3.Row, readings: list[sqlite3.Row]) -> dict:
        return {
            "meal_id": row["meal_id"],
            "user_id": row["user_id"],
            "eaten_at": row["eaten_at"],
            "meal_type": row["meal_type"],
            "foods": json.loads(row["foods"] or "[]"),
            "carbs_g": row["carbs_g"],
            "gl": row["gl"],
            "note": row["note"],
            "source": row["source"],
            "image_id": row["image_id"],
            "insulin_note": row["insulin_note"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "readings": [dict(r) for r in readings],
        }

    def close(self) -> None:
        with self._lock:
            self._conn.close()
