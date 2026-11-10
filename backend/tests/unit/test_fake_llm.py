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


def test_calc_question_plans_executor_node():
    dag = FakeLLM().complete(_planner_prompt("2024年营收同比增长多少？"), tier="strong", schema=TaskDAG)
    # 计算类问题（含"同比"）DAG 必须含 executor 节点且带工具名
    xs = dag.by_role("executor")
    assert len(xs) == 1
    assert xs[0].tool == "growth_rate"
    assert dag.by_role("retriever") and dag.by_role("analyst")


def test_factual_question_has_no_executor():
    dag = FakeLLM().complete(_planner_prompt("公司2024年营业收入是多少？"), tier="strong", schema=TaskDAG)
    # 事实类问题不需要 executor
    assert dag.by_role("executor") == []
    assert len(dag.by_role("retriever")) == 1


def test_calc_regex_covers_all_triggers():
    # 同比|环比|增长|变化|计算 任一命中都加 executor
    for q in ["环比变化如何", "营收增长情况", "帮我计算毛利率", "两期数据有什么变化"]:
        dag = FakeLLM().complete(_planner_prompt(q), tier="strong", schema=TaskDAG)
        assert dag.by_role("executor"), q


def test_analyst_emits_per_line_assertions_with_cites():
    block = (
        "E1 :: 2024年公司实现营业收入120亿元。 :: (A公司2024年报.pdf 第87段)\n"
        "E2 :: 2023年公司实现营业收入100亿元。 :: (A公司2024年报.pdf 第88段)"
    )
    out = FakeLLM().complete(_analyst_prompt("营收是多少", block), tier="strong", schema=AnalystOutput)
    # 逐行产断言且每条带自己的引用编号
    assert len(out.assertions) == 2
    assert out.assertions[0].text == "2024年公司实现营业收入120亿元。"
    assert out.assertions[0].cites == ["E1"]
    assert out.assertions[1].cites == ["E2"]


def test_analyst_skips_malformed_lines():
    # 非 "E编号 :: ..." 格式的行不产断言
    out = FakeLLM().complete(_analyst_prompt("q", "这是说明文字，不是证据行"), tier="strong", schema=AnalystOutput)
    assert out.assertions == []
