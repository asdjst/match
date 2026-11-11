import pytest

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
