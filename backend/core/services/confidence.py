import re
from dataclasses import dataclass

from pydantic import BaseModel, Field

from core.schemas.deliverable import Assertion
from core.schemas.evidence import Evidence
from core.schemas.prompt import PromptBundle, system_for
from core.services.injection import neutralize

DEFAULT_THRESHOLD = 0.45
SUPPORT_MIN = 0.25
BREADTH_CAP = 3

_SEG_RE = re.compile(r"[a-z]+|\d+(?:\.\d+)?|[\u4e00-\u9fff]+")
_NUM_RE = re.compile(r"\d+(?:\.\d+)?")
# 「硬数字」：带单位/百分号或带小数；裸整数（年份、条数）只当语境，不做一致性校验
# 单位按控糖场景取：碳水/体重/身高/能量/血糖/份量/时间
_CLAIM_RE = re.compile(
    r"(\d+(?:\.\d+)?)\s*(?:%|％|mmol|mg|kcal|千卡|毫升|ml|克|g|kg|cm|两|斤|小时|分钟|岁)",
    re.IGNORECASE,
)
_DECIMAL_RE = re.compile(r"(?<![\d.])(\d+\.\d+)(?![\d])")


class LLMConfidence(BaseModel):
    score: float = Field(ge=0.0, le=1.0, description="0-1 的交付置信度")
    reason: str = ""


@dataclass
class ConfidenceResult:
    score: float
    refused: bool
    reason: str | None = None
    source: str = "formula"
    degraded: bool = False


def _units(text: str) -> set[str]:
    """中文按字符二元组、英文/数字按整词切分，衡量断言被证据原文覆盖的比例。"""
    out: set[str] = set()
    for seg in _SEG_RE.findall(text.lower()):
        if seg.isascii() or len(seg) == 1:
            out.add(seg)
        else:
            out.update(seg[i : i + 2] for i in range(len(seg) - 1))
    return out


def _numbers(text: str) -> set[float]:
    return {float(m) for m in _NUM_RE.findall(text.replace(",", ""))}


def claim_numbers(text: str) -> set[float]:
    text = text.replace(",", "")
    return {float(m) for m in _CLAIM_RE.findall(text)} | {float(m) for m in _DECIMAL_RE.findall(text)}


def support(assertion: str, evidence: Evidence) -> float:
    """单条证据对断言的字面支撑度（0-1）：断言里的二元组被证据原文覆盖的比例。"""
    units = _units(assertion)
    if not units:
        return 0.0
    return len(units & _units(evidence.quote)) / len(units)


def numbers_match(wanted: set[float], available: set[float]) -> bool:
    """断言里的硬数字都要能在证据里找到；整数允许是证据值的四舍五入。

    证据写「38.9 克」、断言写「约 39 克」是同一件事，不该判成无支撑；
    小数仍按原值严格比对，99.9 不会因为接近 100 就蒙混过关。
    """
    for value in wanted:
        if value in available:
            continue
        if value.is_integer() and any(round(a) == value for a in available):
            continue
        return False
    return True


def _assertion_support(a: Assertion, pool: dict[str, Evidence]) -> float:
    """断言级支撑：取所引证据里最像的一条，再用整组证据核对硬数字。

    数字必须都能在所引证据里找到——碳水、血糖这类数值才是硬事实；
    都能对上时按强支撑计（0.6 起），因为长引用里的措辞差异不该淹没数值互证。
    """
    cited = [pool[c] for c in a.cites if c in pool]
    if not cited:
        return 0.0
    text = max(support(a.text, ev) for ev in cited)
    wanted = claim_numbers(a.text)
    if not wanted:
        return text
    available: set[float] = set()
    for ev in cited:
        available |= _numbers(ev.quote)
    if not numbers_match(wanted, available):
        return min(text, 0.1)
    return max(text, 0.6)


def score(
    assertions: list[Assertion], pool: dict[str, Evidence], threshold: float = DEFAULT_THRESHOLD
) -> ConfidenceResult:
    """公式兜底：断言支撑率 0.5 + 支撑强度 0.3 + 被引文档广度 0.2。

    只读断言与证据原文，不读检索器返回的原始分：各 adapter 量纲不同
    （R2R 相似度、联网按名次、工具常数），直接平均没有可比性。
    """
    if not assertions:
        return ConfidenceResult(0.0, True, "没有任何带引用的结论")
    per_assertion = [_assertion_support(a, pool) for a in assertions]
    coverage = sum(1 for s in per_assertion if s >= SUPPORT_MIN) / len(assertions)
    relevance = sum(per_assertion) / len(per_assertion)
    cited_docs = {
        pool[c].doc_id
        for a, s in zip(assertions, per_assertion)
        if s >= SUPPORT_MIN
        for c in a.cites
        if c in pool
    }
    breadth = min(len(cited_docs), BREADTH_CAP) / BREADTH_CAP
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
    调用/解析失败时回退确定性公式，并把 degraded 置位，不静默冒充模型评分。"""
    if not assertions:
        return ConfidenceResult(0.0, True, "没有任何带引用的结论")
    claims = "\n".join(f"- {a.text}（引用：{a.cites or '无'}）" for a in assertions)
    evidence_block = "\n".join(
        f"{eid} :: {neutralize(ev.quote)[0]} :: ({ev.source.label()} · {ev.channel})" for eid, ev in pool.items()
    )
    prompt = PromptBundle(
        role="writer",
        system=system_for("writer"),
        task=f"问题：{question}\n待评估断言：\n{claims}",
        evidence_block=evidence_block,
        format_hint='{"score": 0.0-1.0, "reason": "一句话评分理由"}',
    )
    try:
        out: LLMConfidence = llm.complete(prompt, tier="fast", schema=LLMConfidence)
        value = round(float(out.score), 3)
    except Exception:
        fallback = score(assertions, pool, threshold)
        fallback.degraded = True
        fallback.reason = (fallback.reason or "公式兜底") + "（模型评分失败，已回退公式）"
        return fallback
    reason = out.reason or None
    # 拍照识别是按项估的：被引用的识别项最低置信度决定整份答案的上限，
    # 0.4 的汤底估算不能靠“引用都成立”撑到 0.9。
    image_scores = [
        pool[c].score
        for a in assertions
        for c in a.cites
        if c in pool and pool[c].channel == "image"
    ]
    if image_scores:
        cap = round(min(image_scores) + 0.2, 3)
        if value > cap:
            value = cap
            note = f"拍照识别最低置信度 {min(image_scores):.2f}，交付置信度封顶 {cap:.2f}"
            reason = f"{reason}；{note}" if reason else note
    if value < threshold:
        return ConfidenceResult(value, True, reason or f"置信度 {value:.2f} 低于阈值 {threshold}", source="llm")
    return ConfidenceResult(value, False, reason, source="llm")
