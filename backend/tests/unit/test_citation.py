from core.schemas.deliverable import Assertion
from core.schemas.evidence import Evidence
from core.services.citation import attach_citations, parse_citations, renumber, validate_assertions


def _ev(doc_id, score, quote="q"):
    return Evidence(doc_id=doc_id, quote=quote, score=score)


def test_renumber_orders_by_score_desc():
    evs = [_ev("a", 1.0), _ev("b", 3.0), _ev("c", 2.0)]
    pool = renumber(evs)
    # 编号按 score 降序：E1 最高分
    assert list(pool) == ["E1", "E2", "E3"]
    assert pool["E1"].doc_id == "b" and pool["E1"].evidence_id == "E1"
    assert pool["E2"].doc_id == "c"
    assert pool["E3"].doc_id == "a"
    # 原始 Evidence 不被就地修改
    assert evs[0].evidence_id == ""


def test_parse_citations_finds_all_ids():
    # 多编号（含重复、两位数）都要被解析出来
    text = "依据[E1]与[E2]，另见[E10]，重复[E1]。"
    assert parse_citations(text) == ["E1", "E2", "E10", "E1"]
    assert parse_citations("没有引用") == []


def test_validate_assertions_clean():
    pool = {"E1": _ev("d", 1.0)}
    ok = [Assertion(text="有据断言", cites=["E1"])]
    # 引用真实存在 → 无 issue
    assert validate_assertions(ok, pool) == []


def test_validate_assertions_unknown_cite():
    pool = {"E1": _ev("d", 1.0)}
    issues = validate_assertions([Assertion(text="乱引编号的断言", cites=["E9"])], pool)
    # 引用不存在 → 报 issue
    assert len(issues) == 1 and "不存在" in issues[0]


def test_validate_assertions_missing_cite():
    pool = {"E1": _ev("d", 1.0)}
    issues = validate_assertions([Assertion(text="没有任何引用的断言")], pool)
    # 空引用断言视同违规
    assert len(issues) == 1 and "缺引用" in issues[0]


def test_attach_citations_dedup_and_order():
    pool = {
        "E1": Evidence(doc_id="d1", quote="q1", score=3.0, evidence_id="E1"),
        "E2": Evidence(doc_id="d2", quote="q2", score=2.0, evidence_id="E2"),
    }
    assertions = [
        Assertion(text="a", cites=["E2", "E1"]),
        Assertion(text="b", cites=["E2"]),
    ]
    got = attach_citations(assertions, pool)
    # 按断言引用首现顺序输出且去重
    assert [e.evidence_id for e in got] == ["E2", "E1"]


def test_attach_citations_skips_unknown():
    pool = {"E1": Evidence(doc_id="d1", quote="q1", score=1.0, evidence_id="E1")}
    got = attach_citations([Assertion(text="a", cites=["EX", "E1"])], pool)
    # 池中不存在的编号被跳过，不进引用表
    assert [e.evidence_id for e in got] == ["E1"]
