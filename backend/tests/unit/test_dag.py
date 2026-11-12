"""TaskDAG：拓扑排序与 depends_on 门控。

planner 产出的 depends_on 必须真的影响执行：上游检索/计算没成功，下游节点直接 blocked。
"""

from core.graph.nodes.roles import make_executor, make_retriever
from core.schemas.dag import NodeSpec, TaskDAG


def _dag(*nodes: NodeSpec) -> dict:
    return TaskDAG(question="问题", nodes=list(nodes)).model_dump()


def test_order_respects_depends_on():
    dag = TaskDAG(
        question="问题",
        nodes=[
            NodeSpec(node_id="r3", role="retriever", depends_on=["r2"]),
            NodeSpec(node_id="r1", role="retriever"),
            NodeSpec(node_id="r2", role="retriever", depends_on=["r1"]),
        ],
    )
    assert [n.node_id for n in dag.order()] == ["r1", "r2", "r3"]


def test_order_falls_back_on_cycle():
    dag = TaskDAG(
        question="问题",
        nodes=[
            NodeSpec(node_id="a", role="retriever", depends_on=["b"]),
            NodeSpec(node_id="b", role="retriever", depends_on=["a"]),
        ],
    )
    # 成环时退回声明顺序，保证节点不丢、不卡死
    assert [n.node_id for n in dag.order()] == ["a", "b"]


def test_retriever_ignores_self_dependency():
    port = _Port()
    state = {
        "question": "问题",
        "round_no": 0,
        "dag": _dag(NodeSpec(node_id="r1", role="retriever", query="米饭碳水", depends_on=["r1"])),
        "evidence": {},
        "node_results": {},
    }
    out = make_retriever(port)(state)
    assert out["node_results"]["r1"]["status"] == "done"
    assert port.queries == ["米饭碳水"]


class _Port:
    def __init__(self):
        self.queries: list[str] = []

    def recall(self, query, filters=None):
        self.queries.append(query)
        return []


def test_retriever_skips_node_whose_dependency_is_blocked():
    port = _Port()
    state = {
        "question": "问题",
        "round_no": 0,
        "dag": _dag(
            NodeSpec(node_id="x1", role="executor", tool="growth_rate"),
            NodeSpec(node_id="r1", role="retriever", query="第一轮", depends_on=["x1"]),
            NodeSpec(node_id="r2", role="retriever", query="第二轮", depends_on=["r1"]),
        ),
        "evidence": {},
        "node_results": {},
    }
    out = make_retriever(port)(state)
    # x1 是 executor，检索阶段必然还没跑 → r1 被门控，r2 再被 r1 连带门控
    assert out["node_results"]["r1"]["status"] == "blocked"
    assert out["node_results"]["r1"]["block_reason"] == "依赖未完成：x1"
    assert out["node_results"]["r2"]["block_reason"] == "依赖未完成：r1"
    assert port.queries == []


def test_executor_skips_when_upstream_retrieval_blocked():
    class _Tools:
        def list_tools(self):
            return ["growth_rate"]

        def call(self, name, args):
            raise AssertionError("上游阻塞时不该调用工具")

    state = {
        "question": "问题",
        "dag": _dag(
            NodeSpec(node_id="r1", role="retriever"),
            NodeSpec(node_id="x1", role="executor", tool="growth_rate", depends_on=["r1"]),
        ),
        "evidence": {},
        "node_results": {"r1": {"node_id": "r1", "status": "blocked", "block_reason": "检索失败"}},
    }
    out = make_executor(_Tools())(state)
    assert out["node_results"]["x1"]["status"] == "blocked"
    assert out["node_results"]["x1"]["block_reason"] == "依赖未完成：r1"
    assert out["evidence"] == {}
