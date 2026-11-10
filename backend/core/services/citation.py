import re

from core.schemas.deliverable import Assertion
from core.schemas.evidence import Evidence

CITE_RE = re.compile(r"\[(E\d+)\]")


def renumber(evidence: list[Evidence]) -> dict[str, Evidence]:
    """按给分排序后统一编号 E1..En。"""
    pool: dict[str, Evidence] = {}
    for i, ev in enumerate(sorted(evidence, key=lambda e: e.score, reverse=True), start=1):
        pool[f"E{i}"] = ev.model_copy(update={"evidence_id": f"E{i}"})
    return pool


def parse_citations(text: str) -> list[str]:
    return CITE_RE.findall(text)


def validate_assertions(assertions: list[Assertion], pool: dict[str, Evidence]) -> list[str]:
    """无源不答：引用编号必须真实存在；空引用断言视同违规。"""
    issues: list[str] = []
    for a in assertions:
        for c in a.cites:
            if c not in pool:
                issues.append(f"引用 {c} 不存在（断言：{a.text[:24]}…）")
        if not a.cites:
            issues.append(f"断言缺引用：{a.text[:32]}")
    return issues


def attach_citations(
    assertions: list[Assertion], pool: dict[str, Evidence]
) -> list[Evidence]:
    """按断言引用顺序（去重）抽出交付物引用表。"""
    ordered: list[Evidence] = []
    seen: set[str] = set()
    for a in assertions:
        for c in a.cites:
            if c in pool and c not in seen:
                seen.add(c)
                ordered.append(pool[c])
    return ordered


def assertion_stats(assertions: list[Assertion], pool: dict[str, Evidence]) -> dict:
    """评测出口：无源断言率（验收线 ≤5%）等引用健康度指标。"""
    total = len(assertions)
    cited = sum(1 for a in assertions if any(c in pool for c in a.cites))
    return {
        "total": total,
        "cited": cited,
        "no_source_rate": round(1 - cited / total, 4) if total else 0.0,
    }
