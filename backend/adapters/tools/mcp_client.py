"""MCPToolGateway：本地 mcp_server.py（stdio 子进程）的 ToolGateway 协议适配器。

- 子进程生命周期：后台线程独占一个事件循环，stdio_client/ClientSession 异步上下文
  与该线程同生命周期；start() 等就绪、close() 优雅收尾（支持 with 语句）。
- list_tools/call 全部经 GovernedGateway 包装：审计 JSONL + 超时兜底 + 参数校验。
- 未知工具与 FakeTools 契约一致：抛 KeyError（graph 节点按此降级）。
"""

from __future__ import annotations

import asyncio
import json
import sys
import threading
from concurrent.futures import TimeoutError as FuturesTimeoutError
from datetime import timedelta
from pathlib import Path
from typing import Any

from adapters.tools.governance import GovernedGateway, default_timeout_s

SERVER_PATH = Path(__file__).with_name("mcp_server.py")


def _extract_result(call_result: Any) -> dict:
    """把 MCP CallToolResult 还原成 FakeTools 风格 dict。"""
    structured = getattr(call_result, "structuredContent", None)
    if isinstance(structured, dict):
        # 某些 SDK 版本对无模型注解的返回值包一层 {"result": ...}，剥掉
        if set(structured) == {"result"} and isinstance(structured["result"], dict):
            return structured["result"]
        return structured
    for block in getattr(call_result, "content", None) or []:
        text = getattr(block, "text", None)
        if not text:
            continue
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
    return {"ok": False, "error": "MCP 返回内容不可解析"}


def _error_text(call_result: Any) -> str:
    parts = [getattr(b, "text", "") for b in getattr(call_result, "content", None) or []]
    return " / ".join(p for p in parts if p) or "工具执行失败"


class _MCPConnection:
    """一条 MCP stdio 连接：同步门面 + 后台事件循环线程。

    线程主协程持有 stdio_client/ClientSession 上下文，直到 close() 置位停止事件，
    保证异步资源都在同一 task 内干净退出。
    """

    def __init__(
        self,
        server_path: Path | str = SERVER_PATH,
        *,
        python_exe: str | None = None,
        timeout_s: float = 10.0,
    ) -> None:
        self._server_path = Path(server_path)
        self._python = python_exe or sys.executable
        self._timeout_s = float(timeout_s)
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._session: Any = None
        self._stop_evt: asyncio.Event | None = None
        self._ready = threading.Event()
        self._start_error: str | None = None

    # -- 生命周期 --
    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._ready.clear()
        self._start_error = None
        self._thread = threading.Thread(target=self._run, name="mcp-stdio", daemon=True)
        self._thread.start()
        if not self._ready.wait(timeout=max(30.0, self._timeout_s * 3)):
            raise RuntimeError(f"MCP server 启动超时：{self._start_error or '无响应'}")
        if self._start_error:
            raise RuntimeError(f"MCP server 启动失败：{self._start_error}")

    def close(self) -> None:
        if self._stop_evt is not None and self._loop is not None:
            self._loop.call_soon_threadsafe(self._stop_evt.set)
        if self._thread is not None:
            self._thread.join(timeout=20)
        self._session = None
        self._stop_evt = None
        self._thread = None
        self._loop = None

    def __enter__(self) -> "_MCPConnection":
        self.start()
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def _run(self) -> None:
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._main())
        except BaseException as exc:  # 启动失败（含子进程拉不起来）
            self._start_error = repr(exc)
            self._ready.set()
        finally:
            try:
                self._loop.close()
            except Exception:
                pass

    async def _main(self) -> None:
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        params = StdioServerParameters(command=self._python, args=["-u", str(self._server_path)])
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                self._session = session
                stop = asyncio.Event()
                self._stop_evt = stop
                self._ready.set()
                await stop.wait()

    # -- 同步门面 --
    def _ensure_ready(self) -> None:
        if self._session is None or self._loop is None:
            raise RuntimeError("MCP 会话未就绪：先 start() 或使用 with 语句")

    def list_tools(self) -> list[str]:
        self._ensure_ready()
        fut = asyncio.run_coroutine_threadsafe(self._list_tools(), self._loop)
        try:
            return fut.result(self._timeout_s)
        except FuturesTimeoutError:
            # 不取消协程：请求自然完成后迟到响应会被 SDK 丢弃，会话保持一致
            raise TimeoutError("list_tools 超时") from None

    async def _list_tools(self) -> list[str]:
        result = await self._session.list_tools()
        return [tool.name for tool in result.tools]

    def call(self, name: str, args: dict) -> dict:
        self._ensure_ready()
        fut = asyncio.run_coroutine_threadsafe(self._call(name, args), self._loop)
        try:
            # SDK 内部已按 read_timeout_seconds 限时并干净收尾；外部只做极端兜底（留余量，
            # 避免与 SDK 超时竞争导致协程被外部取消、会话变慢）
            return fut.result(self._timeout_s + 10.0)
        except FuturesTimeoutError:
            fut.cancel()
            return {"ok": False, "error": "timeout"}

    async def _call(self, name: str, args: dict) -> dict:
        from mcp.shared.exceptions import McpError

        try:
            result = await self._session.call_tool(
                name, args, read_timeout_seconds=timedelta(seconds=self._timeout_s)
            )
        except McpError as exc:
            msg = str(exc).lower()
            if "unknown tool" in msg:
                raise KeyError(f"未知工具：{name}") from exc
            if "timed out while waiting" in msg:
                return {"ok": False, "error": "timeout"}
            raise
        if getattr(result, "isError", False):
            text = _error_text(result)
            if "unknown tool" in text.lower():
                raise KeyError(f"未知工具：{name}")
            return {"ok": False, "error": text}
        return _extract_result(result)


class MCPToolGateway:
    """ToolGateway 协议实现：本地 stdio MCP server + 治理（审计/超时/校验）。

    接线：app/main.py 中 `tools = FakeTools()` 换成
    `tools = MCPToolGateway(audit_path=..., timeout_s=...)` 即可；进程退出时调用 close()。
    """

    def __init__(
        self,
        *,
        server_path: Path | str | None = None,
        audit_path: Path | str | None = None,
        timeout_s: float | None = None,
        python_exe: str | None = None,
    ) -> None:
        timeout = float(timeout_s) if timeout_s is not None else default_timeout_s()
        self._conn = _MCPConnection(server_path or SERVER_PATH, python_exe=python_exe, timeout_s=timeout)
        # 治理层是外层兜底网：比 MCP 层（SDK 内部限时）多留 5s 余量，避免外层先触发
        # 把协程外部取消掉；正常路径的超时由 SDK 在 timeout_s 时返回 timeout dict。
        self._gov = GovernedGateway(self._conn, audit_path=audit_path, timeout_s=timeout + 5.0)

    @property
    def audit_path(self) -> Path:
        return self._gov.audit_path

    # -- ToolGateway 协议（治理后） --
    def list_tools(self) -> list[str]:
        return self._gov.list_tools()

    def call(self, name: str, args: dict) -> dict:
        return self._gov.call(name, args)

    # -- 生命周期 --
    def start(self) -> None:
        self._conn.start()

    def close(self) -> None:
        # GovernedGateway.close 先关底层子进程/会话（inner.close），再收治理线程池
        self._gov.close()

    def __enter__(self) -> "MCPToolGateway":
        self.start()
        return self

    def __exit__(self, *exc) -> None:
        self.close()
