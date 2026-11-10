"""本地 MCP stdio 数据工具 server（多智能体 RAG 比赛演示）。

独立可运行：
    .venv/bin/python -m adapters.tools.mcp_server
    # 或
    .venv/bin/python adapters/tools/mcp_server.py

用官方 mcp SDK 的 FastMCP 以 stdio 传输启动，暴露工具：
- growth_rate(a, b)：同比增长率 (a-b)/b*100
- yoy_diff(a, b)：同比差值 a-b（带单位说明）
- sum(values) / avg(values)：简单统计
- slow_sum(a, b, delay_s)：测试/演示用延迟工具，用于验证网关超时治理

返回契约与 adapters/tools/fake.py 的 FakeTools 对齐：
成功 {"ok": true, "result": ..., "unit": ...}；失败 {"ok": false, "error": ...}。
"""

from __future__ import annotations

import asyncio

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("mrag-tools", instructions="多智能体 RAG 系统的本地数据计算工具集")


@mcp.tool()
def growth_rate(a: float, b: float) -> dict:
    """同比增长率：(a-b)/b*100，单位 %；b=0 返回失败而非异常。"""
    if b == 0:
        return {"ok": False, "error": "分母为 0"}
    return {"ok": True, "result": round((a - b) / b * 100, 1), "unit": "%"}


@mcp.tool()
def yoy_diff(a: float, b: float) -> dict:
    """同比差值 a-b；unit 说明：结果与输入数据同单位，不是百分比。"""
    return {
        "ok": True,
        "result": round(a - b, 6),
        "unit": "same_as_input",
        "unit_note": "a-b 的绝对差值，与输入数据同单位（如元、个、%），不是百分比",
    }


@mcp.tool(name="sum")
def _sum(values: list[float]) -> dict:
    """数值列表求和；unit 说明：结果与输入同单位。"""
    if not values:
        return {"ok": False, "error": "values 不能为空"}
    return {"ok": True, "result": round(sum(values), 6), "unit": "same_as_input"}


@mcp.tool(name="avg")
def _avg(values: list[float]) -> dict:
    """数值列表平均数；unit 说明：结果与输入同单位。"""
    if not values:
        return {"ok": False, "error": "values 不能为空"}
    return {"ok": True, "result": round(sum(values) / len(values), 6), "unit": "same_as_input"}


@mcp.tool()
async def slow_sum(a: float, b: float, delay_s: float = 0.0) -> dict:
    """测试/演示用：延迟 delay_s 秒后返回 a+b，用于验证网关超时治理。

    必须是 async 工具：FastMCP 1.x 对同步工具直接在事件循环上执行，
    time.sleep 会卡死整个 server（后续请求全部无响应）。
    """
    await asyncio.sleep(max(0.0, delay_s))
    return {"ok": True, "result": a + b, "unit": "same_as_input"}


if __name__ == "__main__":
    mcp.run()  # stdio 传输；注意不要向 stdout 打印任何非协议内容
