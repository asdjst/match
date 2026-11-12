"""executor 工具分派：入参来自结构化数据、结果落可引用证据、缺数据显式阻塞。

用真的 FakeTools 算，不 mock 数值；治理与 MCP 往返另有 test_mcp_tools.py 覆盖。
"""

from adapters.tools.fake import FakeTools
from core.graph.events import node_summary
from core.graph.nodes.roles import _with_food_tools, make_executor
from core.schemas.dag import NodeSpec, TaskDAG

READINGS = [5.6, 10.2, 7.8, 3.5, 14.2]
FOODS = [
    {"name": "米饭", "grams_low": 130, "grams_high": 170, "carbs_g_low": 35, "carbs_g_high": 43},
    {"name": "莲藕", "grams_low": 80, "grams_high": 120, "carbs_g_low": 10, "carbs_g_high": 14},
]
PROFILE = {"height_cm": 170, "weight_kg": 72, "activity": "轻度活动", "goal": "控制餐后血糖"}


def _state(tool: str, instruction: str = "", **extra) -> dict:
    dag = TaskDAG(
        question="问题",
        nodes=[NodeSpec(node_id="x1", role="executor", tool=tool, instruction=instruction)],
    )
    return {
        "question": "问题",
        "dag": dag.model_dump(),
        "evidence": {},
        "node_results": {},
        "steps": 0,
        **extra,
    }


def _run(tool: str, instruction: str = "", **extra):
    state = _state(tool, instruction, **extra)
    out = make_executor(FakeTools())(state)
    return out, out["node_results"]["x1"]


def test_glucose_summary_uses_personal_readings_and_lands_evidence():
    out, result = _run("glucose_summary", glucose_values=READINGS)
    assert result["status"] == "done"
    assert result["output"]["args"] == {"values": READINGS}
    eid = result["evidence_used"][0]
    ev = out["evidence"][eid]
    assert ev["channel"] == "tool" and ev["source"]["file_path"] == "tool://glucose_summary"
    assert "均值 8.26 mmol/L" in ev["quote"]
    assert "CV 50.3%" in ev["quote"] and "极差 10.7" in ev["quote"]
    assert "达标 40%" in ev["quote"]
    assert "读数占比" in ev["quote"] and "不是动态血糖的时间占比" in ev["quote"]


def test_glucose_summary_blocks_without_readings():
    _, result = _run("glucose_summary")
    assert result["status"] == "blocked"
    assert result["block_reason"] == "个人记录里没有血糖读数，无法统计"


def test_meal_gl_total_sums_whole_plate_and_flags_missing():
    out, result = _run("meal_gl_total", food_items=FOODS)
    assert result["status"] == "done"
    # 碳水取识别区间中值：米饭 39g、莲藕 12g
    assert result["output"]["args"] == {
        "foods": [{"name": "米饭", "carbs_g": 39.0}, {"name": "莲藕", "carbs_g": 12.0}]
    }
    quote = out["evidence"][result["evidence_used"][0]]["quote"]
    assert "合计 GL≈32.4" in quote
    assert "碳水合计 51.0g" in quote
    assert "GI 未收录：莲藕 约12.0g碳水" in quote and "不编造 GI" in quote


def test_meal_gl_total_flags_food_outside_table():
    foods = [*FOODS, {"name": "红油汤底", "grams_low": 50, "grams_high": 80, "carbs_g_low": 2, "carbs_g_high": 6}]
    out, result = _run("meal_gl_total", food_items=foods)
    quote = out["evidence"][result["evidence_used"][0]]["quote"]
    assert "未收录：红油汤底" in quote and "仅按已收录食物估算" in quote


def test_food_nutrition_quote_says_gi_unknown_instead_of_none():
    out, result = _run("query_food_nutrition", food_items=[FOODS[1]])
    assert result["status"] == "done"
    quote = out["evidence"][result["evidence_used"][0]]["quote"]
    assert "每100g碳水 16.4g" in quote
    assert "GI 未收录（不估算 GL）" in quote and "GI None" not in quote
    assert "id 516" in quote


def test_calculate_gl_blocks_when_gi_unknown():
    _, result = _run("calculate_gl", food_items=[FOODS[1]])
    assert result["status"] == "blocked"
    assert "GI 未收录" in result["block_reason"]


def test_calculate_gl_keeps_known_item_and_warns_on_unknown():
    out, result = _run("calculate_gl", food_items=FOODS)
    assert result["status"] == "done"
    assert len(result["evidence_used"]) == 1
    assert any("GI 未收录" in w for w in result["warnings"])
    assert "GL≈32.4" in out["evidence"][result["evidence_used"][0]]["quote"]


def test_meal_gl_total_blocks_without_food():
    _, result = _run("meal_gl_total")
    assert result["status"] == "blocked"
    assert result["block_reason"] == "没有可计算的餐食"


def test_carb_target_uses_profile_and_keeps_range_caveat():
    out, result = _run("carb_target", profile=PROFILE)
    assert result["status"] == "done"
    assert result["output"]["args"] == {
        "height_cm": 170.0, "activity": "轻度活动", "weight_kg": 72.0, "goal": "控制餐后血糖"
    }
    quote = out["evidence"][result["evidence_used"][0]]["quote"]
    assert "每日碳水约 219–341g" in quote
    assert "早餐 44–68g" in quote and "午餐 88–136g" in quote
    assert "需由医生或营养师" in quote


def test_carb_target_blocks_without_profile():
    _, result = _run("carb_target", profile={"weight_kg": 72})
    assert result["status"] == "blocked"
    assert result["block_reason"] == "档案缺身高或活动量，无法估算每日碳水"


def test_unknown_tool_degrades_to_blocked():
    _, result = _run("insulin_dose")
    assert result["status"] == "blocked"
    assert result["block_reason"] == "工具不可用：insulin_dose"


def test_tool_failure_is_reported_not_swallowed():
    class _Broken:
        def list_tools(self):
            return ["glucose_summary"]

        def call(self, name, args):
            return {"ok": False, "error": "食物库未收录"}

    state = _state("glucose_summary", glucose_values=READINGS)
    result = make_executor(_Broken())(state)["node_results"]["x1"]
    assert result["status"] == "blocked"
    assert result["block_reason"] == "工具执行失败：食物库未收录"


def test_sum_takes_carbs_when_task_mentions_carbs():
    _, result = _run("sum", instruction="合计这餐碳水", food_items=FOODS, glucose_values=READINGS)
    assert result["status"] == "done"
    assert result["output"]["args"] == {"values": [39.0, 12.0]}
    assert result["output"]["result"] == 51.0


def test_avg_takes_glucose_readings_by_default():
    _, result = _run("avg", instruction="算平均血糖", glucose_values=READINGS)
    assert result["status"] == "done"
    assert result["output"]["args"] == {"values": READINGS}
    assert result["output"]["result"] == 8.26


def test_numeric_tool_blocks_without_any_source():
    _, result = _run("sum", instruction="合计这餐碳水")
    assert result["status"] == "blocked"
    assert result["block_reason"] == "个人记录中没有可计算的数值"


def test_photo_plan_auto_adds_meal_gl_total():
    dag = TaskDAG(question="这餐怎么样", nodes=[NodeSpec(node_id="a1", role="analyst", instruction="评估这餐")])
    out = _with_food_tools(dag, FOODS)
    tools = {n.tool for n in out.nodes if n.role == "executor"}
    assert {"query_food_nutrition", "calculate_gl", "meal_gl_total"} <= tools
    analyst = next(n for n in out.nodes if n.role == "analyst")
    assert "整餐血糖负荷以整餐合计工具证据为准" in analyst.instruction


def test_photo_plan_does_not_duplicate_existing_meal_gl_node():
    dag = TaskDAG(question="这餐怎么样", nodes=[
        NodeSpec(node_id="a1", role="analyst"),
        NodeSpec(node_id="mine", role="executor", tool="meal_gl_total"),
    ])
    out = _with_food_tools(dag, FOODS)
    assert [n.node_id for n in out.nodes if n.tool == "meal_gl_total"] == ["mine"]


def test_executor_summary_surfaces_new_tool_numbers():
    for tool, extra, expected in [
        ("glucose_summary", {"glucose_values": READINGS}, "平均血糖 8.26 mmol/L"),
        ("meal_gl_total", {"food_items": FOODS}, "整餐 GL 合计 32.4"),
        ("carb_target", {"profile": PROFILE}, "每日碳水估算 219–341g"),
    ]:
        state = _state(tool, **extra)
        out = make_executor(FakeTools())(state)
        delta = {"node_results": out["node_results"]}
        summary = node_summary("executor", delta, {**state, **delta}, state)
        assert "成功 1 次" in summary
        assert expected in summary