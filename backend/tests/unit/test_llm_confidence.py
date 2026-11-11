"""llm_score：模型评分成功/低分拒答/异常回退公式（显式降级）/空断言短路。"""

import pytest
from pydantic import ValidationError

from core.schemas.deliverable import Assertion
from core.schemas.evidence import Evidence
from core.schemas.prompt import PromptBundle
from core.services.confidence import LLMConfidence, llm_score


def _pool() -> dict[str, Evidence]:
    quotes = [("E1", "结论一：公司营收稳步增长。"), ("E2", "结论二：毛利率保持稳定。")]
    return {
        eid: Evidence(doc_id=f"d{eid}", quote=q, score=0.5, evidence_id=eid)
        for eid, q in quotes
    }


def _assertions() -> list[Assertion]:
    return [
        Assertion(text="结论一：公司营收稳步增长", cites=["E1"]),
        Assertion(text="结论二：毛利率保持稳定", cites=["E2"]),
    ]


class FakeLLM:
    def __init__(self, result: LLMConfidence | None = None, exc: Exception | None = None):
        self._result = result
        self._exc = exc
        self.calls: list[dict] = []

    def complete(self, prompt, tier, schema=None):
        self.calls.append({"prompt": prompt, "tier": tier, "schema": schema})
        if self._exc is not None:
            raise self._exc
        return self._result


def test_high_llm_score_not_refused_and_source_llm():
    llm = FakeLLM(LLMConfidence(score=0.8, reason="证据充分"))

    res = llm_score(llm, "问题", _assertions(), _pool())

    assert res.score == pytest.approx(0.8)
    assert res.refused is False
    assert res.source == "llm"
    assert res.degraded is False
    assert res.reason == "证据充分"
    # 评分是短 JSON 任务，走快档并要求结构化输出（延迟优化）
    assert llm.calls[0]["tier"] == "fast"
    assert llm.calls[0]["schema"] is LLMConfidence
    assert isinstance(llm.calls[0]["prompt"], PromptBundle)


def test_low_llm_score_refused_with_default_threshold():
    llm = FakeLLM(LLMConfidence(score=0.2, reason="证据关联弱"))

    res = llm_score(llm, "问题", _assertions(), _pool())

    assert res.score == pytest.approx(0.2)
    assert res.refused is True
    assert res.source == "llm"
    assert res.reason


def test_llm_failure_falls_back_to_formula_and_marks_degraded():
    llm = FakeLLM(exc=RuntimeError("模型不可用"))

    res = llm_score(llm, "问题", _assertions(), _pool())

    # 回退公式且显式降级，不冒充模型评分
    assert res.source == "formula"
    assert res.degraded is True
    assert res.score > 0.8
    assert res.refused is False
    assert res.reason and "回退公式" in res.reason


def test_empty_assertions_short_circuits_without_calling_llm():
    llm = FakeLLM(exc=AssertionError("不应被调用"))

    res = llm_score(llm, "问题", [], _pool())

    assert res.score == 0.0
    assert res.refused is True
    assert res.reason
    assert llm.calls == []


def test_llm_confidence_score_constrained_to_unit_interval():
    with pytest.raises(ValidationError):
        LLMConfidence(score=1.2)
    with pytest.raises(ValidationError):
        LLMConfidence(score=-0.1)


def test_low_confidence_photo_evidence_caps_delivery_score():
    pool = {
        "E1": Evidence(
            doc_id="photo",
            quote="拍照识别：红油汤底 30-60g，碳水 1.5-3.0g（依据：估算）",
            score=0.4,
            evidence_id="E1",
            channel="image",
        )
    }
    assertions = [Assertion(text="红油汤底碳水低，但油和能量不低", cites=["E1"])]
    llm = FakeLLM(LLMConfidence(score=0.9, reason="引用成立"))

    res = llm_score(llm, "吃这个需要注意什么？", assertions, pool)

    # 0.4 的识别项不能靠引用成立撑到 0.9：封顶 0.4 + 0.2
    assert res.score == pytest.approx(0.6)
    assert res.refused is False
    assert res.reason and "封顶" in res.reason


def test_uncited_low_confidence_photo_item_does_not_cap():
    pool = {
        "E1": Evidence(
            doc_id="local",
            quote="主食定量，粗细搭配。",
            score=0.4,
            evidence_id="E1",
        ),
        "E2": Evidence(
            doc_id="photo",
            quote="拍照识别：红油汤底 30-60g（依据：估算）",
            score=0.4,
            evidence_id="E2",
            channel="image",
        ),
    }
    assertions = [Assertion(text="主食定量，粗细搭配", cites=["E1"])]
    llm = FakeLLM(LLMConfidence(score=0.9, reason="引用成立"))

    res = llm_score(llm, "主食怎么吃？", assertions, pool)

    # 只按被引用的证据封顶，没被引用的低置信项不影响这条结论
    assert res.score == pytest.approx(0.9)

