from adapters.llm.fake import FakeLLM
from core.schemas.agent import AnalystOutput
from core.schemas.dag import TaskDAG
from core.schemas.prompt import ANALYST_SYSTEM, PromptBundle, system_for


def _planner_prompt(question):
    return PromptBundle(role="planner", system=system_for("planner"), task=f"QUESTION: {question}")


def _analyst_prompt(question, evidence_block):
    return PromptBundle(
        role="analyst",
        system=ANALYST_SYSTEM,
        task=f"问题：{question}",
        evidence_block=evidence_block,
    )


def test_glucose_stats_question_plans_executor_node():
    dag = FakeLLM().complete(
        _planner_prompt("我最近血糖波动大吗？平均值是多少？"), tier="strong", schema=TaskDAG
    )
    xs = dag.by_role("executor")
    assert len(xs) == 1
    assert xs[0].tool == "glucose_summary"
    assert dag.by_role("retriever") and dag.by_role("analyst")


def test_carb_target_question_plans_executor_node():
    dag = FakeLLM().complete(
        _planner_prompt("我每天该吃多少碳水？三餐怎么分？"), tier="strong", schema=TaskDAG
    )
    xs = dag.by_role("executor")
    assert len(xs) == 1
    assert xs[0].tool == "carb_target"


def test_factual_question_has_no_executor():
    dag = FakeLLM().complete(_planner_prompt("一碗米饭大概多少碳水？"), tier="strong", schema=TaskDAG)
    # 事实类问题不需要 executor
    assert dag.by_role("executor") == []
    assert len(dag.by_role("retriever")) == 1


def test_tool_intent_regex_covers_paraphrases():
    for q in ["最近血糖怎么样", "血糖平均是多少", "我的血糖控制得如何", "血糖波动大不大"]:
        dag = FakeLLM().complete(_planner_prompt(q), tier="strong", schema=TaskDAG)
        assert dag.by_role("executor")[0].tool == "glucose_summary", q
    for q in ["每天碳水吃多少克", "一天主食该吃多少", "三餐怎么分配"]:
        dag = FakeLLM().complete(_planner_prompt(q), tier="strong", schema=TaskDAG)
        assert dag.by_role("executor")[0].tool == "carb_target", q


def test_analyst_emits_per_line_assertions_with_cites():
    block = (
        "E1 :: 熟米饭每 100 克约含碳水化合物 25.9 克，GI 约 83。 :: (常见食物碳水速查_摘编.md 米饭与杂粮饭)\n"
        "E2 :: 馒头每 100 克约含碳水化合物 47 克，GI 约 88。 :: (常见食物碳水速查_摘编.md 面食与馒头)"
    )
    out = FakeLLM().complete(_analyst_prompt("米饭碳水多少", block), tier="strong", schema=AnalystOutput)
    # 逐行产断言且每条带自己的引用编号
    assert len(out.assertions) == 2
    assert out.assertions[0].text == "熟米饭每 100 克约含碳水化合物 25.9 克，GI 约 83。"
    assert out.assertions[0].cites == ["E1"]
    assert out.assertions[1].cites == ["E2"]


def test_analyst_skips_malformed_lines():
    # 非 "E编号 :: ..." 格式的行不产断言
    out = FakeLLM().complete(_analyst_prompt("q", "这是说明文字，不是证据行"), tier="strong", schema=AnalystOutput)
    assert out.assertions == []


def test_analyst_puts_own_data_before_general_knowledge():
    block = (
        "E1 :: 主食定量、不宜过多。 :: (成人糖尿病食养指南2023_八条原则_摘编.md 主食定量 · 本地库)\n"
        "E2 :: 碳水化合物供能比通常占总能量的45%～60%。 :: (中国2型糖尿病防治指南2020_医学营养治疗_摘编.md 碳水化合物 · 本地库)\n"
        "E3 :: 拍照识别整餐合计：2 样食物，碳水 43.2-58.3g :: (photo://abc · 拍照)\n"
        "E4 :: 整餐血糖负荷估算：合计 GL≈38.4 :: (tool://meal_gl_total · 工具)\n"
        "E5 :: 最近一餐米饭 150g，餐后两小时血糖 10.2 :: (meal-1 · 个人记录)"
    )
    out = FakeLLM().complete(_analyst_prompt("这餐大概多少碳水？", block), tier="strong", schema=AnalystOutput)
    # 断言上限会截断，本人数据必须先出，否则算出来的数值会被通用指南挤掉
    assert [a.cites[0] for a in out.assertions] == ["E3", "E4", "E5", "E1", "E2"]
