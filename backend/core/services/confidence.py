from dataclasses import dataclass

from pydantic import BaseModel, Field

from core.schemas.deliverable import Assertion
from core.schemas.evidence import Evidence
from core.schemas.prompt import PromptBundle, system_for

DEFAULT_THRESHOLD = 0.45


class LLMConfidence(BaseModel):
    score: float = Field(ge=0.0, le=1.0, description="0-1 的交付置信度")
    reason: str = ""


@dataclass
class ConfidenceResult:
    score: float
    refused: bool
    reason: str | None = None
    source: str = "formula"


def score(
    assertions: list[Assertion], pool: dict[str, Evidence], threshold: float = DEFAULT_THRESHOLD
) -> ConfidenceResult:
    """公式兜底：引用覆盖率 0.5 + 证据相关度均值 0.3 + 证据广度 0.2。"""
    if not assertions:
        return ConfidenceResult(0.0, True, "没有任何带引用的结论")
    cited = [a for a in assertions if a.cites]
    coverage = len(cited) / len(assertions)
    scores = [
        min(pool[c].score / 3.0, 1.0)
        for a in cited
        for c in a.cites
        if c in pool
    ]
    relevance = sum(scores) / len(scores) if scores else 0.0
    breadth = min(len(pool), 5) / 5
    value = 0.5 * coverage + 0.3 * relevance + 0.2 * breadth
    if value < threshold:
        return ConfidenceResult(round(value, 3), True, f"置信度 {value:.2f} 低于阈值 {threshold}")
    return ConfidenceResult(round(value, 3), False)


def llm_score(
    llm,
    question: str,
    assertions: list[Assertion],
    pool: dict[str, Evidence],
    threshold: float = DEFAULT_THRESHOLD,
) -> ConfidenceResult:
    """大模型评分：把断言与全量证据交给 LLM 逐条核对后打 0-1 分；
    调用/解析失败时回退确定性公式，source 标明来源。"""
    if not assertions:
        return ConfidenceResult(0.0, True, "没有任何带引用的结论")
    claims = "\n".join(f"- {a.text}（引用：{a.cites or '无'}）" for a in assertions)
    evidence_block = "\n".join(
        f"{eid} :: {ev.quote} :: ({ev.source.label()} · {ev.channel})" for eid, ev in pool.items()
    )
    prompt = PromptBundle(
        role="writer",
        system=system_for("writer"),
        task=f"问题：{question}\n待评估断言：\n{claims}",
        evidence_block=evidence_block,
        format_hint='{"score": 0.0-1.0, "reason": "一句话评分理由"}',
    )
    try:
        out: LLMConfidence = llm.complete(prompt, tier="strong", schema=LLMConfidence)
        value = round(float(out.score), 3)
    except Exception:
        fallback = score(assertions, pool, threshold)
        fallback.reason = (fallback.reason or "公式兜底") + "（模型评分失败，已回退公式）"
        return fallback
    if value < threshold:
        return ConfidenceResult(value, True, out.reason or f"置信度 {value:.2f} 低于阈值 {threshold}", source="llm")
    return ConfidenceResult(value, False, out.reason or None, source="llm")
