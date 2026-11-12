"""Budget 门控：步数/耗时超限时节点标 blocked，critic 直接放行，writer 标降级。"""

import time

from core.graph.nodes.critic import make_critic
from core.graph.nodes.roles import make_analyst, make_retriever, make_writer
from core.schemas.dag import Budget, NodeSpec, TaskDAG
from core.schemas.evidence import Evidence
from adapters.llm.fake import FakeLLM


class FakePort:
    def __init__(self):
        self.queries: list[str] = []
        self.last_report = []

    def recall(self, query, filters=None):
        self.queries.append(query)
        return [Evidence(doc_id="d1", quote="米饭每100g含碳水25.9g")]


def _dag(*nodes: NodeSpec) -> TaskDAG:
    return TaskDAG(question="米饭碳水多少？", nodes=list(nodes))


def _state(dag: TaskDAG, **extra) -> dict:
    base = {
        "question": "米饭碳水多少？",
        "round_no": 0,
        "dag": dag.model_dump(),
        "evidence": {},
        "node_results": {},
    }
    base.update(extra)
    return base


def test_step_budget_blocks_following_nodes_and_keeps_first_result():
    dag = _dag(
        NodeSpec(node_id="r1", role="retriever", query="米饭碳水", budget=Budget(max_steps=1)),
        NodeSpec(node_id="r2", role="retriever", query="馒头碳水", budget=Budget(max_steps=1)),
    )
    port = FakePort()

    out = make_retriever(port)(_state(dag))

    assert out["node_results"]["r1"]["status"] == "done"
    assert out["node_results"]["r2"]["status"] == "blocked"
    assert "步数预算用尽（1/1）" in out["node_results"]["r2"]["block_reason"]
    assert out["steps"] == 1
    assert out["budget_stop"]
    # 第二个检索节点没有再发起检索
    assert port.queries == ["米饭碳水"]


def test_timeout_budget_blocks_retrieval():
    dag = _dag(NodeSpec(node_id="r1", role="retriever", query="米饭碳水", budget=Budget(timeout_s=1)))
    port = FakePort()

    out = make_retriever(port)(
        _state(dag, started_at=time.monotonic() - 5, steps=0)
    )

    assert out["node_results"]["r1"]["status"] == "blocked"
    assert "耗时预算用尽" in out["node_results"]["r1"]["block_reason"]
    assert port.queries == []


def test_budget_uses_widest_declared_limit():
    # 真实 planner 会给各节点写不同上限（如首节点 3、检索节点 8），整体按最宽的那份算
    dag = _dag(
        NodeSpec(node_id="r1", role="retriever", query="米饭碳水", budget=Budget(max_steps=1)),
        NodeSpec(node_id="r2", role="retriever", query="馒头碳水", budget=Budget(max_steps=8)),
    )

    out = make_retriever(FakePort())(_state(dag))

    assert out["node_results"]["r1"]["status"] == "done"
    assert out["node_results"]["r2"]["status"] == "done"
    assert "budget_stop" not in out or not out["budget_stop"]


def test_critic_does_not_flag_when_planned_work_fits_budget():
    dag = _dag(NodeSpec(node_id="r1", role="retriever", query="米饭碳水", budget=Budget(max_steps=1)))

    # 计划内工作刚好用满步数上限不算耗尽：收尾只看耗时
    out = make_critic()(_state(dag, steps=1, started_at=time.monotonic(), assertions=[]))

    assert out["verdict"]["verdict"] == "pass"
    assert "budget_stop" not in out


def test_critic_passes_when_budget_exhausted_even_with_issues():
    dag = _dag(NodeSpec(node_id="r1", role="retriever", query="米饭碳水"))
    # 断言引用了不存在的证据，规则审校本应打回
    state = _state(
        dag,
        assertions=[{"text": "米饭碳水 99.9g", "cites": ["E9"]}],
        budget_stop="步数预算用尽（8/8）",
    )

    out = make_critic()(state)

    assert out["verdict"]["verdict"] == "pass"
    assert out["node_results"]["critic"]["budget_stop"] == "步数预算用尽（8/8）"


def test_writer_marks_degraded_with_budget_reason():
    dag = _dag(NodeSpec(node_id="r1", role="retriever", query="米饭碳水"))
    evidence = Evidence(evidence_id="E1", doc_id="d1", quote="米饭每100g含碳水25.9g")
    state = _state(
        dag,
        evidence={"E1": evidence.model_dump()},
        assertions=[{"text": "米饭每100g含碳水25.9g", "cites": ["E1"]}],
        verdict={"verdict": "pass", "issues": []},
        budget_stop="耗时预算用尽（130s > 120s）",
    )

    deliverable = make_writer(0.45)(state)["deliverable"]

    assert deliverable["degraded"] is True
    assert deliverable["degraded_reason"] == "耗时预算用尽（130s > 120s）"
    assert deliverable["refused"] is False


def test_analyst_falls_back_to_explicit_meal_check():
    """模型对“之前吃过吗”判空时，个人记录核对证据本身就是可交付结论。"""
    dag = _dag(NodeSpec(node_id="a1", role="analyst", instruction="汇总结论"))
    check = Evidence(
        evidence_id="E1",
        doc_id="meal-check",
        quote="个人记录核对：健康档案现有 1 条餐食记录，未发现 甜玉米、樱桃",
        channel="memory",
    )
    state = _state(dag, evidence={"E1": check.model_dump()}, assertions=[])

    out = make_analyst(FakeLLM())(state)

    assert out["assertions"] == [{"text": check.quote, "cites": ["E1"], "inferred": False}]
    assert out["node_results"]["analyst"]["evidence_used"] == ["E1"]
