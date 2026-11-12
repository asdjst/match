"""账号存储：密码只存 scrypt 派生值，令牌只存哈希，过期与退出都立刻失效。"""

import hashlib
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from core.services.accounts import (
    AccountStore,
    LoginThrottle,
    check_password,
    check_username,
    hash_password,
    password_matches,
)


@pytest.fixture()
def store(tmp_path):
    with_store = AccountStore(tmp_path / "runs.db")
    yield with_store
    with_store.close()


def test_password_hash_is_salted_and_verifiable():
    a = hash_password("控糖日记2026")
    b = hash_password("控糖日记2026")
    assert a != b, "同一密码两次哈希必须不同盐"
    assert "控糖日记2026" not in a
    assert password_matches("控糖日记2026", a)
    assert not password_matches("控糖日记2027", a)


@pytest.mark.parametrize("stored", ["", "plaintext", "md5$1$2$3$aa$bb", "scrypt$x$8$1$zz$bb"])
def test_malformed_hash_never_matches(stored):
    assert not password_matches("whatever", stored)


def test_username_and_password_rules():
    assert check_username("  Alice_01 ") == "alice_01"
    assert check_username("控糖日记") == "控糖日记"
    for bad in ["ab", "x" * 25, "has space", "drop;table", ""]:
        with pytest.raises(ValueError):
            check_username(bad)
    assert check_password("12345678") == "12345678"
    for bad in ["1234567", "x" * 129, ""]:
        with pytest.raises(ValueError):
            check_password(bad)


def test_register_is_case_insensitive_and_stores_no_plaintext(tmp_path):
    path = tmp_path / "runs.db"
    store = AccountStore(path)
    try:
        user = store.register("Alice", "控糖日记2026")
        assert user["username"] == "alice"
        assert user["user_id"].startswith("u_")
        assert "password_hash" not in user
        assert store.register("alice", "另一个密码123") is None
        assert store.verify("ALICE", "控糖日记2026")["user_id"] == user["user_id"]
        assert store.verify("alice", "猜错了12345") is None
        assert store.verify("没人注册", "控糖日记2026") is None
    finally:
        store.close()

    raw = sqlite3.connect(str(path))
    try:
        stored = raw.execute("SELECT password_hash FROM users").fetchone()[0]
        assert stored.startswith("scrypt$16384$8$1$")
        assert "控糖日记2026" not in stored
    finally:
        raw.close()


def test_token_is_stored_hashed_and_revocable(store, tmp_path):
    user = store.register("bob", "控糖日记2026")
    token, expires_at = store.issue(user["user_id"])
    left = datetime.fromisoformat(expires_at) - datetime.now(timezone.utc)
    assert timedelta(days=29) < left <= timedelta(days=30)
    assert store.user_for_token(token) == user["user_id"]
    assert store.user_for_token("") is None
    assert store.user_for_token("伪造的令牌") is None

    conn = sqlite3.connect(str(tmp_path / "runs.db"))
    try:
        digests = [r[0] for r in conn.execute("SELECT token_hash FROM sessions")]
    finally:
        conn.close()
    assert digests == [hashlib.sha256(token.encode()).hexdigest()]
    assert token not in digests

    assert store.revoke(token) is True
    assert store.revoke(token) is False
    assert store.user_for_token(token) is None


def test_expired_session_is_rejected_and_cleaned(store):
    user = store.register("carol", "控糖日记2026")
    token, _ = store.issue(user["user_id"])
    store._conn.execute("UPDATE sessions SET expires_at='2020-01-01T00:00:00+00:00'")
    store._conn.commit()
    assert store.user_for_token(token) is None
    assert store._conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 0


def test_login_throttle_cooldown_and_reset():
    throttle = LoginThrottle(max_fails=3, cooldown_s=300)
    assert throttle.blocked_for("Alice") == 0
    for _ in range(2):
        throttle.record_failure("alice")
    assert throttle.blocked_for("ALICE") == 0, "未到上限不该锁"
    throttle.record_failure("Alice")
    assert 290 <= throttle.blocked_for(" alice ") <= 300
    assert throttle.blocked_for("bob") == 0, "只锁这一个用户名"
    throttle.reset("alice")
    assert throttle.blocked_for("alice") == 0


def test_throttle_cooldown_expires():
    throttle = LoginThrottle(max_fails=1, cooldown_s=0.0)
    throttle.record_failure("alice")
    assert throttle.blocked_for("alice") == 0
    throttle.record_failure("alice")
    assert throttle.blocked_for("alice") == 0