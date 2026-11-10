"""W2.5 评测 + 消融：金标 50 条上跑三组指标。

1. 检索指标（不花 LLM，全量 50）：Recall@5 / MRR（库外题跳过）
2. 管线指标（走完整图，默认抽样 --n）：引用准确率 / 无源断言率 / 库外拒答正确率
3. 消融（同子集）：直连大模型 vs 走检索，LLM-as-judge 打分出对比表

用法:
  .venv/bin/python eval/run_metrics.py            # 仅检索指标（快）
  .venv/bin/python eval/run_metrics.py --n 20     # + 管线指标 + 消融（子集 20 题）
"""
import argparse
import json
import sys
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from adapters.retrieval.r2r_client import R2RClient
from core.graph.builder import build_graph
from core.schemas.deliverable import Assertion
from core.schemas.evidence import Evidence
from core.schemas.prompt import GENERIC_SYSTEM, PromptBundle
from core.services import citation
from infra.config import get_settings

RESULTS = ROOT / "eval" / "results"


def load_golden() -> list[dict]:
    import csv

    with open(ROOT / "eval" / "golden_50.csv", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def parse_expected(src: str) -> list[tuple[str, str]]:
    return [tuple(tok.partition("#")[::2]) for tok in src.split() if "#" in tok]


def source_hit(src, file: str, loc: str) -> bool:
    if src.file_path != file:
        return False
    if loc.endswith("段"):
        return src.section == loc
    if loc.endswith("页"):
        return src.page == int(loc[1:-1])
    if ":" in loc:
        return src.time_code == loc
    return not loc  # 空定位（如 tool://growth_rate#）只要求来源匹配


def hits_expected(ev: Evidence, expected: list[tuple[str, str]]) -> bool:
    return any(source_hit(ev.source, f, loc) for f, loc in expected)


def retrieval_metrics(rows: list[dict], retriever: R2RClient) -> dict:
    hits5 = mrr = n = 0
    per_type: dict[str, list] = {}
    for row in rows:
        if row["qtype"] == "库外":
            continue
        expected = parse_expected(row["expected_sources"])
        evs = retriever.recall(row["question"])
        rank = next((i + 1 for i, ev in enumerate(evs) if hits_expected(ev, expected)), None)
        n += 1
        ok5 = rank is not None and rank <= 5
        hits5 += ok5
        mrr += (1.0 / rank) if rank else 0.0
        per_type.setdefault(row["qtype"], []).append(ok5)
    return {
        "n": n,
        "recall_at_5": round(hits5 / n, 4) if n else 0.0,
        "mrr": round(mrr / n, 4) if n else 0.0,
        "per_type": {k: f"{sum(v)}/{len(v)}" for k, v in per_type.items()},
    }


class Judge:
    """LLM-as-judge：fast 档打 0 / 0.5 / 1 分。"""

    def __init__(self, llm) -> None:
        from pydantic import BaseModel

        class JudgeOut(BaseModel):
            score: float
            reason: str = ""

        self._schema = JudgeOut
        self._llm = llm
        self.system = "你是评测裁判。只依据参考答案要点判断待评答案是否正确，只输出 JSON。"

    def score(self, question: str, ref: str, answer: str) -> float:
        if not answer:
            return 0.0
        prompt = PromptBundle(
            role="writer",
            system=self.system,
            task=f"问题：{question}\n参考答案要点：{ref}\n待评答案：{answer}\n答案正确=1，部分正确=0.5，错误/无关=0",
            format_hint='{"score": 0 或 0.5 或 1, "reason": "…"}',
        )
        try:
            return float(self._llm.complete(prompt, tier="fast", schema=self._schema).score)
        except Exception:
            return 0.0


def run_pipeline(rows: list[dict], app) -> list[dict]:
    """走完整图跑子集，返回逐题结果。"""
    graph = app.state.graph
    out = []
    for row in rows:
        t0 = time.time()
        init = {
            "session_id": "eval",
            "question": row["question"],
            "trace_id": str(uuid.uuid4()),
            "round_no": 0,
            "evidence": {},
            "node_results": {},
        }
        final: dict = dict(init)
        for chunk in graph.stream(init, {"configurable": {"thread_id": init["trace_id"]}, "recursion_limit": 30}, stream_mode="updates"):
            for delta in chunk.values():
                final.update(delta)
        d = final.get("deliverable") or {}
        out.append({
            "qid": row["qid"],
            "qtype": row["qtype"],
            "expected": row,
            "deliverable": d,
            "assertions": [Assertion(**a) for a in d.get("assertions", [])],
            "evidence_pool": {k: Evidence(**v) for k, v in final.get("evidence", {}).items()},
            "latency_s": round(time.time() - t0, 1),
        })
    return out


def pipeline_metrics(results: list[dict], judge: Judge) -> dict:
    cite_ok = cite_all = refused_ok = refused_n = 0
    scores = []
    for r in results:
        row, d = r["expected"], r["deliverable"]
        pool = r["evidence_pool"]
        stats = citation.assertion_stats(r["assertions"], pool)
        expected = parse_expected(row["expected_sources"])
        if row["qtype"] == "库外":
            refused_n += 1
            refused_ok += 1 if d.get("refused") else 0
            continue
        for a in r["assertions"]:
            for c in a.cites:
                if c in pool:
                    cite_all += 1
                    cite_ok += 1 if hits_expected(pool[c], expected) else 0
        ans = "；".join(a.text for a in r["assertions"]) or ""
        scores.append(judge.score(row["question"], row["expected_answer"], ans))
    return {
        "n": len(results),
        "citation_accuracy": round(cite_ok / cite_all, 4) if cite_all else 0.0,
        "no_source_rate": round(
            sum(citation.assertion_stats(r["assertions"], r["evidence_pool"])["total"] - citation.assertion_stats(r["assertions"], r["evidence_pool"])["cited"] for r in results)
            / max(sum(citation.assertion_stats(r["assertions"], r["evidence_pool"])["total"] for r in results), 1),
            4,
        ),
        "answer_score": round(sum(scores) / len(scores), 4) if scores else 0.0,
        "offtopic_refusal": f"{refused_ok}/{refused_n}" if refused_n else "n/a",
    }


def ablation(results: list[dict], llm, judge: Judge) -> dict:
    """同子集：直连大模型 vs 走检索，各自答案分 + 平均延迟。"""
    direct_scores, direct_lat = [], 0.0
    rag_scores = []
    for r in results:
        row = r["expected"]
        if row["qtype"] == "库外":
            continue
        t0 = time.time()
        prompt = PromptBundle(role="writer", system=GENERIC_SYSTEM, task=row["question"], evidence_block="", format_hint="")
        ans = llm.complete(prompt, tier="strong").text
        direct_lat += time.time() - t0
        direct_scores.append(judge.score(row["question"], row["expected_answer"], ans))
        ans_rag = "；".join(a.text for a in r["assertions"]) or ""
        rag_scores.append(judge.score(row["question"], row["expected_answer"], ans_rag))
    n = len(direct_scores) or 1
    return {
        "n": n,
        "direct": {"answer_score": round(sum(direct_scores) / n, 4), "avg_latency_s": round(direct_lat / n, 1)},
        "rag": {"answer_score": round(sum(rag_scores) / n, 4), "avg_latency_s": round(sum(r["latency_s"] for r in results if r["expected"]["qtype"] != "库外") / n, 1)},
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=0, help="管线+消融子集大小（0=只跑检索指标）")
    args = ap.parse_args()
    rows = load_golden()
    settings = get_settings()
    retriever = R2RClient(settings.r2r_base_url, settings.r2r_collection, settings.r2r_api_key, top_k=50)

    retrieval = retrieval_metrics(rows, retriever)
    print("[检索]", json.dumps(retrieval, ensure_ascii=False))
    report = {"retrieval": retrieval}

    if args.n > 0:
        n = args.n
        subset = rows[:n] + [r for r in rows if r["qtype"] == "库外"][:3]
        from app.main import create_app

        app = create_app()
        judge = Judge(app.state.llm)
        results = run_pipeline(subset, app)
        pipe = pipeline_metrics(results, judge)
        abl = ablation(results, app.state.llm, judge)
        print("[管线]", json.dumps(pipe, ensure_ascii=False))
        print("[消融]", json.dumps(abl, ensure_ascii=False))
        report |= {"pipeline": pipe, "ablation": abl, "per_question": [
            {"qid": r["qid"], "qtype": r["qtype"], "refused": r["deliverable"].get("refused", False), "confidence": r["deliverable"].get("confidence"), "latency_s": r["latency_s"]}
            for r in results
        ]}

    RESULTS.mkdir(exist_ok=True)
    out = RESULTS / f"metrics_{time.strftime('%m%d_%H%M')}.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("saved ->", out)


if __name__ == "__main__":
    main()
