"""语义回答缓存：同一用户、上下文指纹未变、问题语义相似 → 直接回放上次交付物。

相似度优先用本地 embeddings 服务（infinity / bge-small-zh-v1.5）的余弦相似度；
服务不可达（离线 fake 模式）退化为归一化文本的 SequenceMatcher 比值，保持确定性。
缓存按 user_id 隔离；指纹覆盖档案、餐图与餐食/血糖条数，个人数据一变就失效。
只缓存未拒答的正常交付物，拒答/降级不缓存。
"""

import hashlib
import json
import re
import sqlite3
import threading
import urllib.request
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher
from pathlib import Path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS answer_cache (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     TEXT NOT NULL,
    question    TEXT NOT NULL,
    fp          TEXT NOT NULL,
    vec         TEXT,
    deliverable TEXT NOT NULL,
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_answer_cache_user ON answer_cache(user_id, id DESC);
"""

_NORM_RE = re.compile(r"[\s,，.。!！?？;；:：、（）()【】\"'“”‘’]+")


def _norm(text: str) -> str:
    return _NORM_RE.sub("", text).lower()


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(x * x for x in b) ** 0.5
    if not na or not nb:
        return 0.0
    return dot / (na * nb)


class AnswerCache:
    def __init__(
        self,
        db_path: str | Path,
        embed_url: str = "",
        embed_model: str = "BAAI/bge-small-zh-v1.5",
        embed_timeout_s: float = 1.5,
        sim_threshold: float = 0.93,
        ttl_s: int = 604800,
        enabled: bool = True,
    ) -> None:
        self.embed_url = embed_url.rstrip("/")
        self.embed_model = embed_model
        self.embed_timeout_s = embed_timeout_s
        self.sim_threshold = sim_threshold
        self.ttl_s = ttl_s
        self.enabled = enabled
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.execute("PRAGMA busy_timeout=5000")
        with self._lock:
            self._conn.executescript(_SCHEMA)

    @staticmethod
    def fingerprint(profile, image_id, food_items, meals_fp: str) -> str:
        """上下文指纹：档案/餐图/识别结果/餐食血糖概况任一变化都视为新上下文。"""
        payload = json.dumps(
            {"p": profile, "img": image_id, "foods": food_items, "m": meals_fp},
            sort_keys=True, ensure_ascii=False, default=str,
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]

    def embed(self, text: str) -> list[float] | None:
        if not self.embed_url:
            return None
        try:
            req = urllib.request.Request(
                f"{self.embed_url}/embeddings",
                data=json.dumps({"model": self.embed_model, "input": [text]}).encode("utf-8"),
                headers={"content-type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=self.embed_timeout_s) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            return [float(x) for x in data["data"][0]["embedding"]]
        except Exception:
            return None

    def _similar(self, q: str, qvec: list[float] | None, row) -> float:
        if qvec is not None and row["vec"]:
            try:
                return _cosine(qvec, json.loads(row["vec"]))
            except Exception:
                pass
        return SequenceMatcher(None, _norm(q), _norm(row["question"])).ratio()

    def lookup(self, user_id: str, fp: str, question: str) -> dict | None:
        """命中返回交付物 dict（调用方自行标 from_cache），未命中返回 None。"""
        if not self.enabled:
            return None
        qvec = self.embed(question)
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=self.ttl_s)
        with self._lock:
            rows = self._conn.execute(
                "SELECT question, vec, fp, deliverable, created_at FROM answer_cache "
                "WHERE user_id=? ORDER BY id DESC LIMIT 200",
                (user_id,),
            ).fetchall()
        for row in rows:
            if row["fp"] != fp:
                continue
            try:
                created = datetime.fromisoformat(row["created_at"])
                if created.tzinfo is None:
                    created = created.replace(tzinfo=timezone.utc)
                if created < cutoff:
                    continue
            except ValueError:
                continue
            if self._similar(question, qvec, row) >= self.sim_threshold:
                try:
                    return json.loads(row["deliverable"])
                except ValueError:
                    continue
        return None

    def store(self, user_id: str, fp: str, question: str, deliverable: dict) -> None:
        if not self.enabled:
            return
        vec = self.embed(question)
        with self._lock:
            self._conn.execute(
                "INSERT INTO answer_cache(user_id, question, fp, vec, deliverable, created_at) "
                "VALUES (?,?,?,?,?,?)",
                (
                    user_id,
                    question,
                    fp,
                    json.dumps(vec) if vec else None,
                    json.dumps(deliverable, ensure_ascii=False),
                    datetime.now(timezone.utc).isoformat(timespec="seconds"),
                ),
            )
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()
