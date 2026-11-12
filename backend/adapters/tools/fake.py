"""离线工具网关：与 mcp_server.py 共用同一份算法，工具集与返回契约逐字对齐。

在线走 MCP stdio 子进程，离线/演示走这里；两边算出的数值必须一致。
"""

from __future__ import annotations

import time

from adapters.tools.food_data import gl_estimate, lookup, source_of
from adapters.tools.health_tools import carb_target, glucose_summary, meal_gl_total

TOOL_NAMES = [
    "growth_rate",
    "yoy_diff",
    "sum",
    "avg",
    "query_food_nutrition",
    "calculate_gl",
    "glucose_summary",
    "meal_gl_total",
    "carb_target",
    "slow_sum",
]


class FakeTools:
    """离线工具网关：数值增减 + 食物成分/GL + 控糖统计，契约与 MCP server 对齐。"""

    def list_tools(self) -> list[str]:
        return list(TOOL_NAMES)

    def call(self, name: str, args: dict) -> dict:
        if name == "growth_rate":
            a, b = float(args["a"]), float(args["b"])
            if b == 0:
                return {"ok": False, "error": "分母为 0"}
            return {"ok": True, "result": round((a - b) / b * 100, 1), "unit": "%"}
        if name == "yoy_diff":
            return {
                "ok": True,
                "result": round(float(args["a"]) - float(args["b"]), 6),
                "unit": "same_as_input",
                "unit_note": "a-b 的绝对差值，与输入数据同单位（如 mmol/L、g、%），不是百分比",
            }
        if name in ("sum", "avg"):
            values = args["values"]
            if not values:
                return {"ok": False, "error": "values 不能为空"}
            total = sum(float(v) for v in values)
            result = total if name == "sum" else total / len(values)
            return {"ok": True, "result": round(result, 6), "unit": "same_as_input"}
        if name == "query_food_nutrition":
            item = lookup(str(args["name"]))
            if item is None:
                return {"ok": False, "error": f"食物库未收录：{args['name']}"}
            return {
                "ok": True,
                "result": {"name": item["name"], "carbs_per_100g": item["carbs_per_100g"], "gi": item["gi"]},
                "unit": "g/100g",
                "source": source_of(item),
            }
        if name == "calculate_gl":
            out = gl_estimate(str(args["name"]), float(args["carbs_g"]))
            if out is None:
                return {"ok": False, "error": f"无法计算：食物未收录或碳水为负（{args['name']}）"}
            if out["gl"] is None:
                return {"ok": False, "error": f"GI 未收录，不估算 GL：{args['name']}（碳水可查 query_food_nutrition）"}
            return {"ok": True, "result": out["gl"], "unit": "GL", "gi": out["gi"], "carbs_g": out["carbs_g"], "source": out["source"]}
        if name == "glucose_summary":
            out = glucose_summary(args["values"], float(args.get("low", 3.9)), float(args.get("high", 10.0)))
            if out is None:
                return {"ok": False, "error": "无法统计：读数为空、含非数值或目标区间非法"}
            return {"ok": True, "result": out, "unit": "mmol/L", "source": out["source"]}
        if name == "meal_gl_total":
            out = meal_gl_total(args["foods"])
            if out is None:
                return {"ok": False, "error": "无法计算：食物全部未收录、碳水为负或清单为空"}
            return {"ok": True, "result": out, "unit": "GL", "source": out["source"]}
        if name == "carb_target":
            out = carb_target(
                args.get("height_cm"), args.get("activity"), args.get("weight_kg"), args.get("goal")
            )
            if out is None:
                return {"ok": False, "error": "无法估算：缺身高或活动量（久坐/轻度活动/规律运动）"}
            return {"ok": True, "result": out, "unit": "g/天", "source": out["source"]}
        if name == "slow_sum":
            # 治理探针：必须经 GovernedGateway 调用，由线程池超时兜底，不要直接裸调
            time.sleep(max(0.0, float(args.get("delay_s", 0.0))))
            return {"ok": True, "result": float(args["a"]) + float(args["b"]), "unit": "same_as_input"}
        raise KeyError(f"未知工具：{name}")