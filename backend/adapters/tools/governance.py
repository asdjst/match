"""工具治理层：审计 JSONL + 单次调用超时兜底 + 参数基础校验（数值型）。

任何实现 list_tools/call 的 ToolGateway（FakeTools、MCP 传输层等）都可以被
GovernedGateway 包装，获得统一治理：
- 每次调用（含 list_tools）写一条审计记录到 JSONL（路径可配，默认 backend/logs/tool_audit.jsonl，
  环境变量 MRAG_TOOL_AUDIT_PATH 覆盖）
- 单次调用超时（默认 10s，MRAG_TOOL_TIMEOUT_S 可配）返回 {"ok": false, "error": "timeout"}，不抛异常
- 已知工具的数值参数做客户端预校验，坏参数不出子进程就被拒绝
"""

from __future__ import annotations

import json
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeoutError
from datetime import datetime
from pathlib import Path
from typing import Any

BACKEND_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_AUDIT_PATH = BACKEND_ROOT / "logs" / "tool_audit.jsonl"
DEFAULT_TIMEOUT_S = 10.0

# 超时兜底返回值（约定契约，勿原地修改）
TIMEOUT_RESULT: dict = {"ok": False, "error": "timeout"}

# 已知工具的数值参数规格（mcp_server.py schema 的镜像）：
# number 必填 / number? 可选 / number[] 非空数值列表
NUMERIC_TOOL_SCHEMAS: dict[str, dict[str, str]] = {
    "growth_rate": {"a": "number", "b": "number"},
    "yoy_diff": {"a": "number", "b": "number"},
    "slow_sum": {"a": "number", "b": "number", "delay_s": "number?"},
    "sum": {"values": "number[]"},
    "avg": {"values": "number[]"},
}


def default_audit_path() -> Path:
    raw = os.environ.get("MRAG_TOOL_AUDIT_PATH")
    return Path(raw) if raw else DEFAULT_AUDIT_PATH


def default_timeout_s() -> float:
    raw = os.environ.get("MRAG_TOOL_TIMEOUT_S")
    return float(raw) if raw else DEFAULT_TIMEOUT_S


def _is_number(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def validate_args(name: str, args: Any) -> str | None:
    """基础校验：args 必须为可 JSON 序列化 dict，已知工具数值参数逐个检查。

    通过返回 None；不通过返回错误文案（文案含参数名）。
    """
    if not isinstance(args, dict):
        return "参数必须是 dict"
    try:
        json.dumps(args, ensure_ascii=False)
    except (TypeError, ValueError):
        return "参数含不可 JSON 序列化的值"
    for key, kind in NUMERIC_TOOL_SCHEMAS.get(name, {}).items():
        if key not in args:
            if kind.endswith("?"):
                continue
            return f"缺少数值参数：{key}"
        val = args[key]
        if kind == "number[]":
            if not isinstance(val, list) or not val:
                return f"参数 {key} 必须为非空数值列表"
            if not all(_is_number(x) for x in val):
                return f"参数 {key} 必须全为数值"
        elif not _is_number(val):
            return f"参数 {key} 必须为数值"
    return None


def _jsonable(obj: Any) -> Any:
    """审计用：不可序列化的参数降级为 repr，保证审计记录永远能落盘。"""
    try:
        json.dumps(obj, ensure_ascii=False)
        return obj
    except (TypeError, ValueError):
        return repr(obj)


def _summary(result: Any, limit: int = 200) -> str:
    """结果摘要：紧凑 JSON 截断，审计文件不存全量大返回。"""
    try:
        text = json.dumps(result, ensure_ascii=False)
    except (TypeError, ValueError):
        text = repr(result)
    return text[:limit]


class GovernedGateway:
    """治理包装器：inner 需实现 list_tools()/call()（ToolGateway 协议子集）。

    list_tools 超时/出错按协议只能抛异常（签名是 list[str]）；
    call 超时按契约返回 {"ok": false, "error": "timeout"}，其余异常审计后原样抛出。
    """

    def __init__(
        self,
        inner: Any,
        *,
        audit_path: Path | str | None = None,
        timeout_s: float | None = None,
    ) -> None:
        self._inner = inner
        self.audit_path = Path(audit_path) if audit_path else default_audit_path()
        self.timeout_s = float(timeout_s) if timeout_s is not None else default_timeout_s()
        self._pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="tool-gov")
        self._lock = threading.Lock()

    # -- ToolGateway 协议 --
    def list_tools(self) -> list[str]:
        t0 = time.perf_counter()
        fut = None
        try:
            fut = self._pool.submit(self._inner.list_tools)
            tools = fut.result(self.timeout_s)
        except FuturesTimeoutError:
            if fut:
                fut.cancel()
            self._write("__list_tools__", {}, t0, {"ok": False, "error": "timeout"}, timed_out=True)
            raise TimeoutError("list_tools 超时") from None
        except Exception as exc:
            self._write("__list_tools__", {}, t0, {"ok": False, "error": str(exc)}, error=type(exc).__name__)
            raise
        self._write("__list_tools__", {}, t0, {"ok": True, "result": tools})
        return tools

    def call(self, name: str, args: dict) -> dict:
        bad = validate_args(name, args)
        if bad is not None:
            result = {"ok": False, "error": bad}
            self._write(name, args, time.perf_counter(), result)
            return result
        t0 = time.perf_counter()
        fut = None
        try:
            fut = self._pool.submit(self._inner.call, name, args)
            result = fut.result(self.timeout_s)
        except FuturesTimeoutError:
            if fut:
                fut.cancel()
            result = dict(TIMEOUT_RESULT)
            timed_out = True
        except Exception as exc:
            self._write(name, args, t0, {"ok": False, "error": str(exc)}, error=type(exc).__name__)
            raise
        else:
            timed_out = isinstance(result, dict) and result.get("ok") is False and result.get("error") == "timeout"
        self._write(name, args, t0, result, timed_out=timed_out)
        return result

    # -- 生命周期 --
    def close(self) -> None:
        inner_close = getattr(self._inner, "close", None)
        if callable(inner_close):
            inner_close()
        self._pool.shutdown(wait=False, cancel_futures=True)

    def __enter__(self) -> "GovernedGateway":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # -- 审计 --
    def _write(
        self,
        tool: str,
        args: Any,
        t0: float,
        result: Any,
        *,
        timed_out: bool = False,
        error: str | None = None,
    ) -> None:
        record = {
            "ts": datetime.now().astimezone().isoformat(timespec="milliseconds"),
            "tool": tool,
            "args": _jsonable(args),
            "duration_ms": round((time.perf_counter() - t0) * 1000, 2),
            "ok": bool(isinstance(result, dict) and result.get("ok") is True),
            "timed_out": bool(timed_out),
            "summary": _summary(result),
            "error": error,
        }
        with self._lock:
            self.audit_path.parent.mkdir(parents=True, exist_ok=True)
            with self.audit_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
