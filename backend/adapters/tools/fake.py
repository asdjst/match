from adapters.tools.food_data import SOURCE, gl_estimate, lookup


class FakeTools:
    """离线工具网关：财报增长率 + 食物成分/GL，契约与 MCP server 对齐。"""

    def list_tools(self) -> list[str]:
        return ["growth_rate", "query_food_nutrition", "calculate_gl"]

    def call(self, name: str, args: dict) -> dict:
        if name == "growth_rate":
            a, b = float(args["a"]), float(args["b"])
            if b == 0:
                return {"ok": False, "error": "分母为 0"}
            return {"ok": True, "result": round((a - b) / b * 100, 1), "unit": "%"}
        if name == "query_food_nutrition":
            item = lookup(str(args["name"]))
            if item is None:
                return {"ok": False, "error": f"食物库未收录：{args['name']}"}
            return {
                "ok": True,
                "result": {"name": item["name"], "carbs_per_100g": item["carbs_per_100g"], "gi": item["gi"]},
                "unit": "g/100g",
                "source": SOURCE,
            }
        if name == "calculate_gl":
            out = gl_estimate(str(args["name"]), float(args["carbs_g"]))
            if out is None:
                return {"ok": False, "error": f"无法计算：食物未收录或碳水为负（{args['name']}）"}
            return {"ok": True, "result": out["gl"], "unit": "GL", "gi": out["gi"], "carbs_g": out["carbs_g"], "source": out["source"]}
        raise KeyError(f"未知工具：{name}")
