import pytest

from core.schemas.common import SourceRef
from core.schemas.deliverable import Assertion
from core.schemas.evidence import Evidence
from core.services.confidence import score

QUOTE = "米饭每100g含碳水25.9g，馒头每100g含碳水47.0g。"


def _pool(n=5, quote=QUOTE, score_value=0.02):
    return {
        f"E{i}": Evidence(doc_id=f"d{i}", quote=quote, score=score_value, evidence_id=f"E{i}")
        for i in range(1, n + 1)
    }


def _grounded():
    return [
        Assertion(text="米饭每100g含碳水25.9g。", cites=["E1"]),
        Assertion(text="馒头每100g含碳水47.0g。", cites=["E2"]),
    ]


def test_grounded_assertions_not_refused():
    res = score(_grounded(), _pool())
    # 全部有字面支撑 → 高置信、不拒答
    assert res.refused is False
    assert res.score > 0.9
    assert res.reason is None


def test_retriever_score_scale_does_not_affect_result():
    # 回归：旧公式把检索分/3 当相关度，R2R 的 0.017 会让置信度恒为 0.702
    low = score(_grounded(), _pool(score_value=0.017))
    high = score(_grounded(), _pool(score_value=0.99))
    assert low.score == high.score
    assert low.score != pytest.approx(0.702)


def test_cited_but_irrelevant_is_refused():
    pool = {"E1": Evidence(doc_id="d1", quote="社区健身房器械保养与开放时间说明。", evidence_id="E1")}
    res = score([Assertion(text="米饭每100g含碳水25.9g。", cites=["E1"])], pool)
    # 有引用编号但证据无关 → 低分拒答
    assert res.refused is True
    assert res.score < 0.2
    assert "低于阈值" in res.reason


def test_pool_size_alone_does_not_raise_confidence():
    # 只增加无关证据不能抬高置信度（旧公式里广度按池子大小算）
    pool = _pool(n=20, quote="与本问题无关的门诊排班说明。")
    res = score([Assertion(text="米饭每100g含碳水25.9g。", cites=["E1"])], pool)
    assert res.refused is True
    assert res.score < 0.2


def test_number_mismatch_is_ungrounded():
    # 断言里的数字必须全部出现在证据中，哪怕其他措辞高度重合
    res = score([Assertion(text="米饭每100g含碳水99.9g。", cites=["E1"])], _pool())
    assert res.refused is True
    assert res.score < 0.2


def test_tool_evidence_with_matching_number_counts_as_strong_support():
    ev = Evidence(
        doc_id="tool",
        quote="工具计算：5.6 对比 7.0 → 25.0%",
        score=1.0,
        evidence_id="E1",
        source=SourceRef(file_path="tool://growth_rate"),
    )
    res = score([Assertion(text="两次血糖读数升幅为25.0%。", cites=["E1"])], {"E1": ev})
    assert res.refused is False
    assert res.score > 0.7
    # 数字对不上时工具证据同样不买账
    bad = score([Assertion(text="两次血糖读数升幅为35.0%。", cites=["E1"])], {"E1": ev})
    assert bad.refused is True
    assert bad.score < 0.2


def test_multi_source_assertion_support():
    # 一条断言合并两个来源的数字，数字分散在各条证据里也要算有支撑
    pool = {
        "E1": Evidence(doc_id="d1", quote="米饭每100g含碳水25.9g。", evidence_id="E1"),
        "E2": Evidence(doc_id="d2", quote="馒头每100g含碳水47.0g。", evidence_id="E2"),
    }
    res = score([Assertion(text="米饭每100g含碳水25.9g，馒头每100g含碳水47.0g。", cites=["E1", "E2"])], pool)
    assert res.refused is False
    assert res.score > 0.8


def test_health_units_are_hard_numbers():
    pool = {"E1": Evidence(doc_id="d1", quote="餐后 2 小时血糖 11.0 mmol/L。", evidence_id="E1")}
    ok = score([Assertion(text="餐后 2 小时血糖 11.0 mmol/L。", cites=["E1"])], pool)
    assert ok.refused is False
    bad = score([Assertion(text="餐后 2 小时血糖 16.0 mmol/L。", cites=["E1"])], pool)
    assert bad.refused is True
    assert bad.score < 0.2


def test_integer_grams_are_checked():
    # 整数克重也是硬数字：旧口径只查小数/百分号，会把 39 克说成 52 克放过
    pool = {"E1": Evidence(doc_id="d1", quote="这碗米饭约 39 克碳水。", evidence_id="E1")}
    bad = score([Assertion(text="这碗米饭约 52 克碳水。", cites=["E1"])], pool)
    assert bad.refused is True
    assert bad.score < 0.2


def test_rounded_integer_grams_are_accepted():
    pool = {"E1": Evidence(doc_id="d1", quote="150 × 25.9 ÷ 100 ≈ 38.9 克碳水。", evidence_id="E1")}
    res = score([Assertion(text="这碗米饭约 39 克碳水。", cites=["E1"])], pool)
    assert res.refused is False


def test_empty_assertions_always_refused():
    res = score([], _pool())
    assert res.refused is True
    assert res.score == 0.0
    assert res.reason


def test_threshold_boundary():
    assertions = [Assertion(text="米饭每100g含碳水25.9g。", cites=["E1"]), Assertion(text="无引用结论")]
    # coverage 0.5 + relevance 0.5 + 单文档广度 → 0.467
    assert score(assertions, _pool(), threshold=0.46).refused is False
    assert score(assertions, _pool(), threshold=0.47).refused is True


def test_uncited_assertion_lowers_score():
    assertions = [*_grounded(), Assertion(text="该结论无任何引用")]
    assert score(assertions, _pool()).score < score(_grounded(), _pool()).score