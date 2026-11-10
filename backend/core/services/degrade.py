"""W4.4 降级兜底：模型/检索不可用时，用已收集证据出模板结论并明示免责声明。"""

from core.schemas.deliverable import Assertion, Deliverable
from core.schemas.evidence import Evidence

DISCLAIMER = "系统降级运行：本结论由缓存证据模板生成，未经完整审校，请自行核对原文。"


def fallback_deliverable(question: str, evidence: dict, trace_id: str, reason: str) -> Deliverable:
    pool = {k: Evidence(**v) for k, v in (evidence or {}).items()}
    top = sorted(pool.values(), key=lambda e: e.score, reverse=True)[:5]
    if top:
        assertions = [Assertion(text=f"缓存证据：{e.quote}", cites=[e.evidence_id]) for e in top]
        return Deliverable(
            question=question,
            assertions=assertions,
            citations=sorted(pool.values(), key=lambda e: e.score, reverse=True)[:5],
            trace_id=trace_id,
            confidence=0.0,
            degraded=True,
            refused=False,
            refusal_reason=f"{reason}；{DISCLAIMER}",
        )
    return Deliverable(
        question=question,
        trace_id=trace_id,
        confidence=0.0,
        degraded=True,
        refused=True,
        refusal_reason=f"{reason}；无可用证据，无法作答",
    )
