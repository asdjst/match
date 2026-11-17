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
    parsed = json.loads(row["vec"])
    assert parsed["v"] == [1.0, 0.0] and parsed["m"] == c.embed_model
    # 改写但语义相近（同一向量）→ 余弦 1.0 命中
    assert c.lookup("alice", "fp1", "米饭的碳水含量大概是多少？") is not None
    # 完全不相关（正交向量）→ 余弦 0 不命中
    assert c.lookup("alice", "fp1", "明天上海天气如何") is None


def test_cacheable_predicate():
    from core.services.answer_cache import cacheable

    assert cacheable({"answer": "x"})
    assert not cacheable(None)
    assert not cacheable({})
    assert not cacheable({"refused": True})
    assert not cacheable({"degraded": True, "refused": False})  # 降级兜底也不能缓存


def test_fingerprint_day_change_invalidates(tmp_path):
    c = make(tmp_path)
    c.store("alice", AnswerCache.fingerprint(None, None, [], "m0", day="2026-11-12"), "一碗米饭大概多少碳水？", D)
    base = AnswerCache.fingerprint(None, None, [], "m0", day="2026-11-12")
    assert c.lookup("alice", base, "一碗米饭大概多少碳水？？？") is not None
    # 跨天 → 失效（"今天…"类问题的答案随日期变化）
    assert c.lookup("alice", AnswerCache.fingerprint(None, None, [], "m0", day="2026-11-13"), "一碗米饭大概多少碳水？") is None


def test_cosine_dimension_mismatch_is_zero():
    from core.services.answer_cache import _cosine

    assert _cosine([1.0, 0.0], [1.0]) == 0.0
    assert _cosine([1.0, 0.0], [1.0, 0.0]) == 1.0


def test_vec_model_mismatch_falls_back_to_text(tmp_path):
    c = make(tmp_path)
    c.embed = lambda text: [1.0, 0.0]  # type: ignore[method-assign]
    c.store("alice", "fp1", "一碗米饭大概多少碳水？", D)
    # 换了 embedding 模型：向量空间不同，回退文本相似度（同问题文本相似度 1.0 仍命中）
    c.embed_model = "other-model"
    assert c.lookup("alice", "fp1", "一碗米饭大概多少碳水？") is not None
    assert c.lookup("alice", "fp1", "完全不相关的问题") is None
