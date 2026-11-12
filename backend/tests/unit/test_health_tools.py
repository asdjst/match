"""控糖领域工具：纯函数口径、双网关契约一致性、治理层参数校验。

血糖统计口径必须与前端 frontend/src/lib/glucoseStats.ts 逐项一致，
否则同一份记录在图表和问答里会给出两个数字。
"""

import pytest

from adapters.tools.fake import TOOL_NAMES, FakeTools
from adapters.tools.governance import GovernedGateway, validate_args
from adapters.tools.health_tools import (
    carb_target,
    glucose_summary,
    meal_gl_total,
    zone_of,
)


@pytest.mark.parametrize(
    "value, expected",
    [
        (2.9, "low2"),
        (3.0, "low"),
        (3.8, "low"),
        (3.9, "ok"),
        (10.0, "ok"),
        (10.1, "high"),
        (13.9, "high"),
        (14.0, "high2"),
    ],
)
def test_zone_boundaries(value, expected):
    assert zone_of(value) == expected


def test_glucose_summary_matches_frontend_formula():
    out = glucose_summary([5.6, 10.2, 7.8, 3.5, 14.2])
    assert out["n"] == 5
    assert out["mean"] == 8.26
    # 标准差用 n-1：sqrt(68.992/4)=4.1531…
    assert out["sd"] == 4.15
    assert out["cv"] == 50.3
    assert out["min"] == 3.5 and out["max"] == 14.2
    assert out["lage"] == 10.7
    assert out["counts"] == {"low2": 0, "low": 1, "ok": 2, "high": 1, "high2": 1}
    assert out["pct"]["ok"] == 40.0
    assert "读数条数" in out["source"] and "不是动态血糖的时间占比" in out["source"]


def test_glucose_summary_single_reading_has_no_dispersion():
    out = glucose_summary([6.1])
    assert out["n"] == 1
    assert out["sd"] is None and out["cv"] is None and out["lage"] is None
    assert out["pct"]["ok"] == 100.0


def test_glucose_summary_custom_target():
    out = glucose_summary([8.0, 9.0], low=3.9, high=7.8)
    assert out["counts"]["high"] == 2
    assert out["pct"]["ok"] == 0.0


@pytest.mark.parametrize("values", [[], [1.0, float("nan")], [float("inf")]])
def test_glucose_summary_rejects_bad_input(values):
    assert glucose_summary(values) is None


def test_glucose_summary_rejects_bad_target():
    assert glucose_summary([6.0], low=10.0, high=3.9) is None


def test_meal_gl_total_sums_and_flags_missing():
    out = meal_gl_total([
        {"name": "米饭", "carbs_g": 38.9},
        {"name": "豆腐", "carbs_g": 3.0},
        {"name": "红油汤底", "carbs_g": 12.0},
    ])
    rice = next(i for i in out["items"] if i["name"] == "米饭")
    assert rice["gi"] == 83 and rice["gl"] == 32.3
    assert out["total_gl"] == round(sum(i["gl"] for i in out["items"]), 1)
    assert out["total_carbs_g"] == 41.9
    # 红油汤底未收录：合计只覆盖已收录项，必须显式标 partial，不能冒充整餐值
    assert out["missing"] == ["红油汤底"] and out["partial"] is True


def test_meal_gl_total_counts_carbs_but_not_gl_when_gi_unknown():
    out = meal_gl_total([{"name": "米饭", "carbs_g": 39.0}, {"name": "莲藕", "carbs_g": 12.0}])
    assert out["total_gl"] == 32.4
    # 莲藕碳水已知、GI 未收录：碳水计入合计，GL 不计入，也不编一个 GI
    assert out["total_carbs_g"] == 51.0
    assert out["unknown_gi"] == [{"name": "莲藕", "carbs_g": 12.0}]
    assert out["missing"] == [] and out["partial"] is True


def test_meal_gl_total_without_any_known_gi_has_no_total():
    out = meal_gl_total([{"name": "莲藕", "carbs_g": 12.0}])
    # 没有 GI 已收录项时合计 GL 是 None，不是 0，免得被读成“整餐不升糖”
    assert out["total_gl"] is None
    assert out["total_carbs_g"] == 12.0 and out["partial"] is True


def test_meal_gl_total_full_coverage_is_not_partial():
    out = meal_gl_total([{"name": "米饭", "carbs_g": 50}])
    assert out["total_gl"] == 41.5
    assert out["partial"] is False and out["missing"] == []


@pytest.mark.parametrize(
    "foods",
    [[], [{"name": "外星食物", "carbs_g": 10}], [{"name": "米饭", "carbs_g": -1}], [{"carbs_g": 10}]],
)
def test_meal_gl_total_rejects_unusable_input(foods):
    assert meal_gl_total(foods) is None


def test_carb_target_known_values():
    out = carb_target(170, "轻度活动", 72, "控制餐后血糖")
    assert out["ideal_weight_kg"] == 65.0
    assert out["energy_kcal"] == [1950, 2275]
    assert out["carbs_g_per_day"] == [219, 341]
    assert out["per_meal_carbs_g"] == {"早餐": [44, 68], "午餐": [88, 136], "晚餐": [88, 136]}
    assert out["actual_weight_kg"] == 72.0
    assert "需由医生或营养师" in out["note"] and "不是用药或诊断依据" in out["note"]


def test_carb_target_ideal_weight_only_needs_height_and_activity():
    out = carb_target(160, "久坐")
    assert out["ideal_weight_kg"] == 55.0
    assert out["carbs_g_per_day"] == [155, 248]
    assert "actual_weight_kg" not in out


def test_carb_target_weight_loss_keeps_estimate_and_warns():
    out = carb_target(170, "轻度活动", goal="减重")
    assert out["carbs_g_per_day"] == [219, 341]
    assert "未自动下调" in out["note"]


@pytest.mark.parametrize(
    "kwargs",
    [{}, {"height_cm": 170}, {"activity": "久坐"}, {"height_cm": 170, "activity": "躺着"}, {"height_cm": 90, "activity": "久坐"}],
)
def test_carb_target_rejects_insufficient_profile(kwargs):
    assert carb_target(**kwargs) is None


@pytest.mark.parametrize(
    "name, args",
    [
        ("glucose_summary", {"values": [5.6, 10.2, 7.8, 3.5, 14.2]}),
        ("meal_gl_total", {"foods": [{"name": "米饭", "carbs_g": 38.9}, {"name": "莲藕", "carbs_g": 12}]}),
        ("carb_target", {"height_cm": 170, "activity": "轻度活动", "weight_kg": 72, "goal": "减重"}),
    ],
)
def test_fake_tools_match_pure_functions(name, args):
    out = FakeTools().call(name, args)
    assert out["ok"] is True
    expected = {"glucose_summary": glucose_summary, "meal_gl_total": meal_gl_total, "carb_target": carb_target}[name]
    assert out["result"] == expected(**args)


def test_fake_tools_error_contract():
    tools = FakeTools()
    assert tools.call("glucose_summary", {"values": []})["ok"] is False
    assert tools.call("meal_gl_total", {"foods": [{"name": "外星食物", "carbs_g": 1}]})["ok"] is False
    assert tools.call("carb_target", {})["ok"] is False
    with pytest.raises(KeyError):
        tools.call("insulin_dose", {"units": 8})


def test_fake_tools_expose_full_tool_set():
    assert FakeTools().list_tools() == TOOL_NAMES
    assert {"glucose_summary", "meal_gl_total", "carb_target", "sum", "avg", "yoy_diff"} <= set(TOOL_NAMES)


def test_governed_fake_matches_mcp_error_wording(tmp_path):
    """离线网关也需要治理层：空读数的报错文案必须与 MCP 模式一致。"""
    with GovernedGateway(FakeTools(), audit_path=tmp_path / "audit.jsonl") as gw:
        assert gw.call("glucose_summary", {"values": []}) == {
            "ok": False,
            "error": "参数 values 必须为非空数值列表",
        }


@pytest.mark.parametrize(
    "name, args, fragment",
    [
        ("meal_gl_total", {"foods": []}, "foods"),
        ("meal_gl_total", {"foods": ["米饭"]}, "foods"),
        ("meal_gl_total", {}, "foods"),
        ("glucose_summary", {"values": [1, "x"]}, "values"),
        ("glucose_summary", {"values": [6.0], "high": "10"}, "high"),
        ("carb_target", {"height_cm": "170"}, "height_cm"),
        ("carb_target", {"activity": "   "}, "activity"),
    ],
)
def test_validate_args_rejects_bad_payloads(name, args, fragment):
    error = validate_args(name, args)
    assert error is not None and fragment in error


@pytest.mark.parametrize(
    "args",
    [{}, {"height_cm": None, "activity": None}, {"height_cm": 170, "activity": "久坐", "goal": None}],
)
def test_validate_args_allows_optional_none(args):
    assert validate_args("carb_target", args) is None