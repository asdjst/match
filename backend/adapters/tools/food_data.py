"""食物成分示例库：MCP server 与 FakeTools 共用同一份数据与算法。"""

import json
from functools import lru_cache
from pathlib import Path

_TABLE_PATH = Path(__file__).resolve().parents[2] / "data" / "food_nutrition.json"
SOURCE = "演示示例库：碳水参考《中国食物成分表》，GI 参考国内外常见 GI 表；逐项出处见 food_nutrition.json 的 source"


@lru_cache(maxsize=1)
def _foods() -> list[dict]:
    return json.loads(_TABLE_PATH.read_text(encoding="utf-8"))["foods"]


def source_of(item: dict) -> str:
    return item.get("source") or SOURCE


def _names(item: dict) -> list[str]:
    return [item["name"], *item.get("aliases", [])]


def lookup(name: str) -> dict | None:
    """先精确匹配（含别名，如“冰激凌”→冰淇淋），再按包含关系兜底（“一碗米饭” → 米饭）。"""
    query = (name or "").strip()
    if not query:
        return None
    for item in _foods():
        if query in _names(item):
            return item
    for item in _foods():
        if any(n in query or query in n for n in _names(item)):
            return item
    return None


def nutrition_for(name: str, grams: float) -> dict | None:
    """把「食物名 + 克数」折算成碳水与 GL：库外食物或克数无效返回 None，不猜数。"""
    item = lookup(name)
    if item is None or grams <= 0:
        return None
    carbs = round(float(item["carbs_per_100g"]) * float(grams) / 100, 1)
    gi = item["gi"]
    return {
        "name": item["name"],
        "carbs_g": carbs,
        "gl": round(gi * carbs / 100, 1) if gi is not None else None,
        "source": source_of(item),
    }


def gl_estimate(name: str, carbs_g: float) -> dict | None:
    """GI 未收录（gi=None）时只给碳水，gl 返回 None，不拿猜测值凑数。"""
    item = lookup(name)
    if item is None or carbs_g < 0:
        return None
    gi = item["gi"]
    carbs = float(carbs_g)
    return {
        "name": item["name"],
        "gi": gi,
        "carbs_g": round(carbs, 1),
        "gl": round(gi * carbs / 100, 1) if gi is not None else None,
        "source": source_of(item),
    }
