from typing import TypedDict


class GraphState(TypedDict, total=False):
    """节点间只传 dict（checkpoint 序列化安全）；出入节点处用 schemas 转换。"""

    session_id: str
    question: str
    trace_id: str
    dag: dict
    evidence: dict          # evidence_id -> Evidence.model_dump()
    assertions: list[dict]  # Assertion.model_dump()
    node_results: dict      # node_id -> AgentResult.model_dump()
    verdict: dict | None    # ReviewVerdict.model_dump()
    round_no: int
    deliverable: dict | None
