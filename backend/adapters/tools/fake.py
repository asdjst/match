class FakeTools:
    """W1 工具网关假实现：只有增长率计算；MCP 治理版在 W4。"""

    def list_tools(self) -> list[str]:
        return ["growth_rate"]

    def call(self, name: str, args: dict) -> dict:
        if name == "growth_rate":
            a, b = float(args["a"]), float(args["b"])
            if b == 0:
                return {"ok": False, "error": "分母为 0"}
            return {"ok": True, "result": round((a - b) / b * 100, 1), "unit": "%"}
        raise KeyError(f"未知工具：{name}")
