"""make_retriever：把渠道检索报告写进 node_results，且 Evidence.channel 透传。"""

from core.graph.nodes.roles import make_retriever
from core.schemas.dag import NodeSpec, TaskDAG
from core.schemas.evidence import Evidence

REPORT = [{"channel": "local", "hits": 2, "latency_ms": 30, "status": "ok"}]


class FakePort:
    """假检索端口：带 recall 与 last_report 属性。"""

    def __init__(self, hits: list[Evidence]):
        self._hits = hits
        self.last_report = [dict(item) for item in REPORT]
        self.queries: list[str] = []

    def recall(self, query: str, filters: dict | None = None) -> list[Evidence]:
        self.queries.append(query)
        return list(self._hits)


def _state() -> dict:
    dag = TaskDAG(
        question="问题",
        nodes=[NodeSpec(node_id="r1", role="retriever", instruction="检索", query="米饭碳水")],
    )
    return {
        "question": "问题",
        "round_no": 0,
        "dag": dag.model_dump(),
        "evidence": {},
        "node_results": {},
    }


def test_retriever_writes_channel_report_to_node_results():
    port = FakePort(
        [
            Evidence(doc_id="d1", quote="本地证据", channel="local"),
            Evidence(doc_id="d2", quote="网页证据", channel="web"),
        ]
    )

    out = make_retriever(port)(_state())

    # 检索节点把 port.last_report 原样写入 node_results[spec.node_id]["retrievals"]
    result = out["node_results"]["r1"]
    assert result["status"] == "done"
    assert result["retrievals"] == port.last_report
    assert result["evidence_used"] == ["E1", "E2"]
    assert port.queries == ["米饭碳水"]
    # 分配 evidence_id 后 channel 字段仍保留
    assert out["evidence"]["E1"]["channel"] == "local"
    assert out["evidence"]["E2"]["channel"] == "web"


def test_retrievals_empty_when_port_has_no_report():
    class NoReportPort:
        def recall(self, query, filters=None):
            return []

    out = make_retriever(NoReportPort())(_state())

    assert out["node_results"]["r1"]["retrievals"] == []


def test_evidence_model_copy_preserves_channel():
    ev = Evidence(doc_id="d1", quote="证据", channel="cloud")

    copied = ev.model_copy(update={"evidence_id": "E9"})

    assert copied.channel == "cloud"
    assert copied.evidence_id == "E9"
