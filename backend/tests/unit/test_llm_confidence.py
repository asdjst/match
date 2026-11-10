"""llm_score：模型评分成功/低分拒答/异常回退公式/空断言短路。"""

import pytest
from pydantic import ValidationError

from core.schemas.deliverable import Assertion
from core.schemas.evidence import Evidence
from core.schemas.prompt import PromptBundle
from core.services.confidence import LLMConfidence, llm_score


def _pool(n: int = 5, score_value: float = 3.0) -> dict[str, Evidence]:
    return {
        f"E{i}": Evidence(doc_id=f"d{i}", quote=f"证据{i}", score=score_value, evidence_id=f"E{i}")
        for i in range(1, n + 1)
    }


def _assertions() -> list[Assertion]:
    return [
        Assertion(text="结论一", cites=["E1"]),
        Assertion(text="结论二", cites=["E2"]),
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
    assert res.reason == "证据充分"
    # 走 strong 档并要求结构化输出
    assert llm.calls[0]["tier"] == "strong"
    assert llm.calls[0]["schema"] is LLMConfidence
    assert isinstance(llm.calls[0]["prompt"], PromptBundle)


def test_low_llm_score_refused_with_default_threshold():
    llm = FakeLLM(LLMConfidence(score=0.2, reason="证据关联弱"))

    res = llm_score(llm, "问题", _assertions(), _pool())

    # 0.2 < 默认阈值 0.45 → 拒答，理由非空且来源为 llm
    assert res.score == pytest.approx(0.2)
    assert res.refused is True
    assert res.source == "llm"
    assert res.reason


def test_llm_failure_falls_back_to_formula():
    llm = FakeLLM(exc=RuntimeError("模型不可用"))

    res = llm_score(llm, "问题", _assertions(), _pool())

    # 全引用 + 满广度 → 公式满分；来源标记 formula，理由注明回退
    assert res.source == "formula"
    assert res.score == pytest.approx(1.0)
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
    # pydantic 约束：score 必须落在 [0, 1]
    with pytest.raises(ValidationError):
        LLMConfidence(score=1.2)
    with pytest.raises(ValidationError):
        LLMConfidence(score=-0.1)
