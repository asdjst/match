"""本地 MCP stdio 数据工具 server（多智能体 RAG 比赛演示）。

独立可运行：
    .venv/bin/python -m adapters.tools.mcp_server
    # 或
    .venv/bin/python adapters/tools/mcp_server.py

用官方 mcp SDK 的 FastMCP 以 stdio 传输启动，暴露工具：
- growth_rate(a, b)：变化率 (a-b)/b*100，如两次血糖读数的升幅
- yoy_diff(a, b)：差值 a-b（带单位说明）
- sum(values) / avg(values)：简单统计
- query_food_nutrition(name) / calculate_gl(name, carbs_g)：食物成分与单点血糖负荷
- glucose_summary(values, low, high)：个人血糖读数统计（均值/CV/LAGE/读数占比）
- meal_gl_total(foods)：整餐血糖负荷合计，未收录与 GI 未收录项单列
- carb_target(height_cm, activity, weight_kg, goal)：每日碳水估算区间与三餐分配
- slow_sum(a, b, delay_s)：测试/演示用延迟工具，用于验证网关超时治理

返回契约与 adapters/tools/fake.py 的 FakeTools 对齐：
成功 {"ok": true, "result": ..., "unit": ...}；失败 {"ok": false, "error": ...}。
"""

from __future__ import annotations

import asyncio

from mcp.server.fastmcp import FastMCP

try:  # 作为脚本启动时 sys.path 只含本目录
    from adapters.tools.food_data import gl_estimate, lookup, source_of
    from adapters.tools.health_tools import carb_target as carb_target_calc
    from adapters.tools.health_tools import glucose_summary as glucose_summary_calc
    from adapters.tools.health_tools import meal_gl_total as meal_gl_total_calc
except ModuleNotFoundError:
    from food_data import gl_estimate, lookup, source_of
    from health_tools import carb_target as carb_target_calc
    from health_tools import glucose_summary as glucose_summary_calc
    from health_tools import meal_gl_total as meal_gl_total_calc

mcp = FastMCP("mrag-tools", instructions="多智能体 RAG 系统的本地数据计算工具集")


@mcp.tool()
def growth_rate(a: float, b: float) -> dict:
    """变化率：(a-b)/b*100，单位 %，如两次血糖读数的升幅；b=0 返回失败而非异常。"""
    if b == 0:
        return {"ok": False, "error": "分母为 0"}
    return {"ok": True, "result": round((a - b) / b * 100, 1), "unit": "%"}


@mcp.tool()
def yoy_diff(a: float, b: float) -> dict:
    """差值 a-b，如餐后血糖减去餐前血糖；unit 说明：结果与输入数据同单位，不是百分比。"""
    return {
        "ok": True,
        "result": round(a - b, 6),
        "unit": "same_as_input",
        "unit_note": "a-b 的绝对差值，与输入数据同单位（如 mmol/L、g、%），不是百分比",
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
def query_food_nutrition(name: str) -> dict:
    """按食物名查每 100g 碳水与 GI；未收录返回失败，不编造数值。

    gi 为 null 表示 GI 未收录（无权威测定或各表差异过大），此时只给碳水。
    """
    item = lookup(name)
    if item is None:
        return {"ok": False, "error": f"食物库未收录：{name}"}
    return {
        "ok": True,
        "result": {"name": item["name"], "carbs_per_100g": item["carbs_per_100g"], "gi": item["gi"]},
        "unit": "g/100g",
        "source": source_of(item),
    }


@mcp.tool()
def calculate_gl(name: str, carbs_g: float) -> dict:
    """血糖负荷 GL = GI × 碳水(g) / 100；只做营养估算，不构成医疗建议。

    GI 未收录的食物返回失败而不是猜一个 GI，碳水改用 query_food_nutrition 查。
    """
    out = gl_estimate(name, carbs_g)
    if out is None:
        return {"ok": False, "error": f"无法计算：食物未收录或碳水为负（{name}）"}
    if out["gl"] is None:
        return {"ok": False, "error": f"GI 未收录，不估算 GL：{name}（碳水可查 query_food_nutrition）"}
    return {"ok": True, "result": out["gl"], "unit": "GL", "gi": out["gi"], "carbs_g": out["carbs_g"], "source": out["source"]}


@mcp.tool()
def glucose_summary(values: list[float], low: float = 3.9, high: float = 10.0) -> dict:
    """个人血糖读数统计：均值、标准差(n-1)、CV、极差与五区间读数占比。

    手动点测只能算读数占比，不是动态血糖的时间占比，也不推算糖化血红蛋白。
    """
    out = glucose_summary_calc(values, low, high)
    if out is None:
        return {"ok": False, "error": "无法统计：读数为空、含非数值或目标区间非法"}
    return {"ok": True, "result": out, "unit": "mmol/L", "source": out["source"]}


@mcp.tool()
def meal_gl_total(foods: list[dict]) -> dict:
    """整餐血糖负荷合计：逐项 GI×碳水/100 再相加。

    foods 每项 {"name": str, "carbs_g": number}。未收录的食物列入 missing，
    GI 未收录但碳水已知的列入 unknown_gi：碳水合计含两者，GL 合计只含 GI 已收录项
    （partial=true），不得当成整餐精确值。
    """
    out = meal_gl_total_calc(foods)
    if out is None:
        return {"ok": False, "error": "无法计算：食物全部未收录、碳水为负或清单为空"}
    return {"ok": True, "result": out, "unit": "GL", "source": out["source"]}


@mcp.tool()
def carb_target(
    height_cm: float | None = None,
    activity: str | None = None,
    weight_kg: float | None = None,
    goal: str | None = None,
) -> dict:
    """按身高与活动量估算每日碳水区间与三餐分配；通用估算，不是医嘱。"""
    out = carb_target_calc(height_cm, activity, weight_kg, goal)
    if out is None:
        return {"ok": False, "error": "无法估算：缺身高或活动量（久坐/轻度活动/规律运动）"}
    return {"ok": True, "result": out, "unit": "g/天", "source": out["source"]}


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
