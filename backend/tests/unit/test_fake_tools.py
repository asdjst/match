import json
from pathlib import Path

import pytest

from adapters.tools import food_data
from adapters.tools.fake import FakeTools


def test_growth_rate_normal():
    t = FakeTools()
    out = t.call("growth_rate", {"a": 120, "b": 100})
    # (120-100)/100*100 = 20%
    assert out["ok"] is True
    assert out["result"] == 20.0
    assert out["unit"] == "%"


def test_growth_rate_negative_and_rounding():
    t = FakeTools()
    out = t.call("growth_rate", {"a": 100, "b": 333})
    # 结果保留一位小数，可为负
    assert out["ok"] is True
    assert out["result"] == pytest.approx(-70.0)


def test_growth_rate_zero_denominator():
    t = FakeTools()
    out = t.call("growth_rate", {"a": 120, "b": 0})
    # 分母为 0 返回失败标记而非抛异常
    assert out["ok"] is False
    assert "error" in out


def test_unknown_tool_raises():
    t = FakeTools()
    # 未知工具必须抛 KeyError
    with pytest.raises(KeyError):
        t.call("weather", {"city": "北京"})


def test_list_tools():
    assert "growth_rate" in FakeTools().list_tools()
    assert {"query_food_nutrition", "calculate_gl"} <= set(FakeTools().list_tools())


def test_query_food_nutrition():
    out = FakeTools().call("query_food_nutrition", {"name": "一碗米饭"})

    assert out["ok"] is True
    assert out["result"] == {"name": "米饭", "carbs_per_100g": 25.9, "gi": 83}
    assert out["source"]


def test_calculate_gl():
    # GI 83 × 50g / 100 = 41.5
    out = FakeTools().call("calculate_gl", {"name": "米饭", "carbs_g": 50})

    assert out["ok"] is True
    assert out["result"] == 41.5
    assert out["gi"] == 83


def test_food_tool_unknown_food():
    assert FakeTools().call("query_food_nutrition", {"name": "火星果"})["ok"] is False
    assert FakeTools().call("calculate_gl", {"name": "火星果", "carbs_g": 10})["ok"] is False


def test_gi_unknown_food_reports_carbs_only():
    t = FakeTools()
    out = t.call("query_food_nutrition", {"name": "莲藕"})
    assert out["ok"] is True
    assert out["result"] == {"name": "莲藕", "carbs_per_100g": 16.4, "gi": None}
    assert "id 516" in out["source"]

    gl = t.call("calculate_gl", {"name": "莲藕", "carbs_g": 12})
    assert gl["ok"] is False and "GI 未收录" in gl["error"]


def test_demo_plate_foods_are_covered():
    t = FakeTools()
    for name in ("莲藕", "虾", "樱桃", "甜玉米段"):
        assert t.call("query_food_nutrition", {"name": name})["ok"] is True, name
    # 红油汤底没有权威成分值：宁可不收录，也不编一个碳水数
    assert t.call("query_food_nutrition", {"name": "红油汤底"})["ok"] is False


def test_food_table_is_well_formed_and_sourced():
    path = Path(__file__).resolve().parents[2] / "data" / "food_nutrition.json"
    foods = json.loads(path.read_text(encoding="utf-8"))["foods"]
    names = [f["name"] for f in foods]
    assert len(names) == len(set(names))
    for item in foods:
        assert isinstance(item["carbs_per_100g"], (int, float)) and item["carbs_per_100g"] >= 0
        assert item["gi"] is None or 0 <= item["gi"] <= 110
    # 扩充项必须写明出处：成分表条目 id + GI 来源或未收录理由
    for item in foods:
        if "source" in item:
            assert "id " in item["source"] and "GI" in item["source"], item["name"]
    # 别名不能和别的条目重名，否则 lookup 会指错食物
    labels = [n for item in foods for n in [item["name"], *item.get("aliases", [])]]
    assert len(labels) == len(set(labels))


def test_alias_lookup_ice_cream():
    for name in ("冰淇淋", "冰激凌", "雪糕"):
        assert food_data.lookup(name)["name"] == "冰淇淋", name
    assert FakeTools().call("query_food_nutrition", {"name": "冰激凌"})["result"]["carbs_per_100g"] == 17.3


def test_nutrition_for_fills_carbs_and_gl():
    ice = food_data.nutrition_for("冰激凌", 150)
    # 17.3g/100g × 150g；GI 未收录 → 只给碳水，不猜 GL
    assert ice["carbs_g"] == 25.9 and ice["gl"] is None
    assert "id 1393" in ice["source"]

    rice = food_data.nutrition_for("一碗米饭", 150)
    assert rice["carbs_g"] == 38.9 and rice["gl"] == 32.3


def test_nutrition_for_refuses_to_guess():
    assert food_data.nutrition_for("红油汤底", 50) is None
    assert food_data.nutrition_for("米饭", 0) is None
    assert food_data.nutrition_for("", 150) is None
