"""食物成分示例库：MCP server 与 FakeTools 共用同一份数据与算法。"""

import json
from functools import lru_cache
from pathlib import Path

_TABLE_PATH = Path(__file__).resolve().parents[2] / "data" / "food_nutrition.json"
SOURCE = "演示示例库：碳水参考中国食物成分表，GI 参考国际 GI 数据库常见值"


@lru_cache(maxsize=1)
def _foods() -> list[dict]:
    return json.loads(_TABLE_PATH.read_text(encoding="utf-8"))["foods"]


def lookup(name: str) -> dict | None:
    """先精确匹配，再按包含关系兜底（“一碗米饭” → 米饭）。"""
    query = (name or "").strip()
    if not query:
        return None
    for item in _foods():
        if item["name"] == query:
            return item
    for item in _foods():
        if item["name"] in query or query in item["name"]:
            return item
    return None


def gl_estimate(name: str, carbs_g: float) -> dict | None:
    item = lookup(name)
    if item is None or carbs_g < 0:
        return None
    return {
        "name": item["name"],
        "gi": item["gi"],
        "carbs_g": round(float(carbs_g), 1),
        "gl": round(item["gi"] * float(carbs_g) / 100, 1),
        "source": SOURCE,
    }
