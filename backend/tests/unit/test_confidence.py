import pytest

from core.schemas.deliverable import Assertion
from core.schemas.evidence import Evidence
from core.services.confidence import score


def _pool(n=5, score_value=3.0):
    return {
        f"E{i}": Evidence(doc_id=f"d{i}", quote=f"证据{i}", score=score_value, evidence_id=f"E{i}")
        for i in range(1, n + 1)
    }


def test_high_coverage_and_relevance_not_refused():
    pool = _pool(5, 3.0)
    assertions = [
        Assertion(text="结论一", cites=["E1"]),
        Assertion(text="结论二", cites=["E2"]),
    ]
    res = score(assertions, pool)
    # 全引用 + 高相关 + 广度满格 → 不拒答且分数接近 1
    assert res.refused is False
    assert res.score == pytest.approx(1.0)
    assert res.reason is None


def test_empty_assertions_always_refused():
    res = score([], _pool())
    # 没有任何带引用的结论必须拒答
    assert res.refused is True
    assert res.score == 0.0
    assert res.reason


def test_threshold_boundary_equal_passes():
    pool = _pool(1, 0.0)
    assertions = [Assertion(text="有引用", cites=["E1"]), Assertion(text="无引用")]
    # coverage 0.5*0.5=0.25 + relevance 0 + breadth 0.2*0.2=0.04 → 0.29
    res = score(assertions, pool, threshold=0.29)
    # 分值等于阈值时不算低于，不拒
    assert res.refused is False
    assert res.score == pytest.approx(0.29, abs=1e-6)


def test_threshold_below_boundary_refuses():
    pool = _pool(1, 0.0)
    assertions = [Assertion(text="有引用", cites=["E1"]), Assertion(text="无引用")]
    res = score(assertions, pool, threshold=0.30)
    # 同样输入抬高阈值即拒，reason 里带阈值信息
    assert res.refused is True
    assert "低于阈值" in res.reason


def test_default_threshold_refuses_low_score():
    pool = _pool(1, 0.0)
    assertions = [Assertion(text="有引用", cites=["E1"]), Assertion(text="无引用")]
    # 默认阈值 0.45，0.29 分必拒
    assert score(assertions, pool).refused is True
