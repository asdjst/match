"""账号与会话：用户名 + scrypt 密码哈希，登录发放随机令牌，退出即吊销。

密码只存 scrypt 派生值（带随机盐），令牌只存 SHA-256，库被拖走也还原不出密码与可用令牌。
未登录的请求仍归单机演示身份 local，登录后的数据按 user_id 隔离。
"""

import hashlib
import hmac
import re
import secrets
import sqlite3
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    user_id        TEXT PRIMARY KEY,
    username       TEXT NOT NULL UNIQUE,
    password_hash  TEXT NOT NULL,
    created_at     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
    token_hash  TEXT PRIMARY KEY,
    user_id     TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    expires_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);
"""

_USERNAME_RE = re.compile(r"[A-Za-z0-9_\-一-鿿]{3,24}")
_SCRYPT_N, _SCRYPT_R, _SCRYPT_P, _KEY_LEN = 16384, 8, 1, 32
SESSION_TTL = timedelta(days=30)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _stamp(moment: datetime) -> str:
    return moment.isoformat(timespec="seconds")


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    derived = hashlib.scrypt(
        password.encode("utf-8"), salt=salt, n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P, dklen=_KEY_LEN
    )
    return f"scrypt${_SCRYPT_N}${_SCRYPT_R}${_SCRYPT_P}${salt.hex()}${derived.hex()}"


def password_matches(password: str, stored: str) -> bool:
    try:
        algo, n, r, p, salt_hex, hash_hex = stored.split("$")
        if algo != "scrypt":
            return False
        derived = hashlib.scrypt(
            password.encode("utf-8"), salt=bytes.fromhex(salt_hex), n=int(n), r=int(r), p=int(p),
            dklen=len(bytes.fromhex(hash_hex)),
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(derived.hex(), hash_hex)


def check_username(username: str) -> str:
    """返回规范化用户名（不区分大小写）；不合规抛 ValueError，文案直接给用户看。"""
    name = (username or "").strip()
    if not _USERNAME_RE.fullmatch(name):
        raise ValueError("用户名需 3–24 个字符，只能用中英文、数字、下划线或连字符")
    return name.casefold()


def check_password(password: str) -> str:
    if not 8 <= len(password or "") <= 128:
        raise ValueError("密码需 8–128 个字符")
    return password


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class AccountStore:
    """账号与登录态，和 run/餐食记录同一个 SQLite 文件，单文件零运维。"""

    def __init__(self, path: str | Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        # WAL 下 synchronous=NORMAL 足够安全且写入更快；busy_timeout 避免并发写直接报 locked
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.execute("PRAGMA busy_timeout=5000")
        self._conn.executescript(_SCHEMA)

    def register(self, username: str, password: str) -> dict | None:
        """用户名已存在返回 None，其余不合规抛 ValueError。"""
        name = check_username(username)
        secret = check_password(password)
        user_id = f"u_{uuid.uuid4().hex[:12]}"
        with self._lock:
            try:
                self._conn.execute(
                    "INSERT INTO users (user_id, username, password_hash, created_at) VALUES (?, ?, ?, ?)",
                    (user_id, name, hash_password(secret), _stamp(_now())),
                )
                self._conn.commit()
            except sqlite3.IntegrityError:
                return None
        return self.get_user(user_id)

    def verify(self, username: str, password: str) -> dict | None:
        name = (username or "").strip().casefold()
        with self._lock:
            row = self._conn.execute(
                "SELECT user_id, password_hash FROM users WHERE username=?", (name,)
            ).fetchone()
        # 用户名不存在也要跑一次哈希，避免用响应时间猜哪些用户名注册过
        stored = row["password_hash"] if row else hash_password("timing-equalizer")
        if not password_matches(password or "", stored) or row is None:
            return None
        return self.get_user(row["user_id"])

    def get_user(self, user_id: str) -> dict | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT user_id, username, created_at FROM users WHERE user_id=?", (user_id,)
            ).fetchone()
        return dict(row) if row else None

    def issue(self, user_id: str) -> tuple[str, str]:
        """发放新令牌，返回 (明文令牌, 过期时刻)；明文只在响应里出现一次。"""
        token = secrets.token_urlsafe(32)
        now = _now()
        expires = now + SESSION_TTL
        with self._lock:
            self._conn.execute("DELETE FROM sessions WHERE expires_at < ?", (_stamp(now),))
            self._conn.execute(
                "INSERT INTO sessions (token_hash, user_id, created_at, expires_at) VALUES (?, ?, ?, ?)",
                (_token_hash(token), user_id, _stamp(now), _stamp(expires)),
            )
            self._conn.commit()
        return token, _stamp(expires)

    def user_for_token(self, token: str) -> str | None:
        if not token:
            return None
        digest = _token_hash(token)
        with self._lock:
            row = self._conn.execute(
                "SELECT user_id, expires_at FROM sessions WHERE token_hash=?", (digest,)
            ).fetchone()
            if row is None:
                return None
            if datetime.fromisoformat(row["expires_at"]) <= _now():
                self._conn.execute("DELETE FROM sessions WHERE token_hash=?", (digest,))
                self._conn.commit()
                return None
            return row["user_id"]

    def revoke(self, token: str) -> bool:
        if not token:
            return False
        with self._lock:
            cur = self._conn.execute("DELETE FROM sessions WHERE token_hash=?", (_token_hash(token),))
            self._conn.commit()
        return bool(cur.rowcount)

    def close(self) -> None:
        with self._lock:
            self._conn.close()


class LoginThrottle:
    """同一用户名连续失败就冷却，挡住拿字典猜密码；进程内计数，重启即清零。"""

    def __init__(self, max_fails: int = 5, cooldown_s: float = 300.0) -> None:
        self._max_fails = max_fails
        self._cooldown_s = cooldown_s
        self._fails: dict[str, tuple[int, float]] = {}
        self._lock = threading.Lock()

    def blocked_for(self, username: str) -> int:
        """剩余冷却秒数，0 表示可以继续尝试。"""
        with self._lock:
            entry = self._fails.get((username or "").strip().casefold())
        if not entry:
            return 0
        _, until = entry
        return max(0, int(until - time.monotonic()))

    def record_failure(self, username: str) -> None:
        key = (username or "").strip().casefold()
        with self._lock:
            count, until = self._fails.get(key, (0, 0.0))
            if until and until <= time.monotonic():
                count = 0
            count += 1
            self._fails[key] = (count, time.monotonic() + self._cooldown_s if count >= self._max_fails else 0.0)

    def reset(self, username: str) -> None:
        with self._lock:
            self._fails.pop((username or "").strip().casefold(), None)
