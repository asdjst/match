"""语义回答缓存：命中/未命中/用户隔离/指纹失效/TTL/embeddings 余弦路径。"""

import json
from datetime import datetime, timedelta, timezone

from core.services.answer_cache import AnswerCache

D = {"question": "q", "answer": "米饭每100g碳水约26g[E1]", "assertions": [], "citations": []}


def make(tmp_path, **kw):
    kw.setdefault("embed_url", "")  # 默认走确定性的文本相似度回退路径
    return AnswerCache(tmp_path / "c.db", **kw)


def test_store_then_lookup_hit_same_question_normalized(tmp_path):
    c = make(tmp_path)
    c.store("alice", "fp1", "一碗米饭大概多少碳水？", D)
    hit = c.lookup("alice", "fp1", "一碗米饭大概多少碳水？？？")  # 标点空白归一化后相同
    assert hit is not None and hit["answer"] == D["answer"]


def test_lookup_miss_on_different_question(tmp_path):
    c = make(tmp_path)
    c.store("alice", "fp1", "一碗米饭大概多少碳水？", D)
    assert c.lookup("alice", "fp1", "今天天气怎么样") is None
    # 语序明显不同的改写在文本回退路径下不算命中（阈值 0.93 偏严格，避免误缓存）
    assert c.lookup("alice", "fp1", "米饭一碗大概多少碳水？") is None


def test_user_isolation(tmp_path):
    c = make(tmp_path)
    c.store("alice", "fp1", "一碗米饭大概多少碳水？", D)
    assert c.lookup("bob", "fp1", "一碗米饭大概多少碳水？") is None


def test_fingerprint_change_invalidates(tmp_path):
    c = make(tmp_path)
    c.store("alice", "fp1", "一碗米饭大概多少碳水？", D)
    assert c.lookup("alice", "fp2", "一碗米饭大概多少碳水？") is None


def test_ttl_expiry(tmp_path):
    c = make(tmp_path, ttl_s=60)
    c.store("alice", "fp1", "一碗米饭大概多少碳水？", D)
    old = (datetime.now(timezone.utc) - timedelta(seconds=3600)).isoformat(timespec="seconds")
    with c._lock:
        c._conn.execute("UPDATE answer_cache SET created_at=?", (old,))
        c._conn.commit()
    assert c.lookup("alice", "fp1", "一碗米饭大概多少碳水？") is None


def test_disabled_cache_is_noop(tmp_path):
    c = make(tmp_path, enabled=False)
    c.store("alice", "fp1", "一碗米饭大概多少碳水？", D)
    assert c.lookup("alice", "fp1", "一碗米饭大概多少碳水？") is None


def test_embedding_cosine_path(tmp_path):
    c = make(tmp_path)
    # 模拟本地 embeddings：含“米饭”的问题向量接近，其余正交
    c.embed = lambda text: [1.0, 0.0] if "米饭" in text else [0.0, 1.0]  # type: ignore[method-assign]
    c.store("alice", "fp1", "一碗米饭大概多少碳水？", D)
    row = c._conn.execute("SELECT vec FROM answer_cache").fetchone()
    assert json.loads(row["vec"]) == [1.0, 0.0]
    # 改写但语义相近（同一向量）→ 余弦 1.0 命中
    assert c.lookup("alice", "fp1", "米饭的碳水含量大概是多少？") is not None
    # 完全不相关（正交向量）→ 余弦 0 不命中
    assert c.lookup("alice", "fp1", "明天上海天气如何") is None
