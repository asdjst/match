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
    # 用 " | " 分隔多个来源：知识卡小标题自带空格（如"升糖指数 GI 的含义"），按空格切会把定位截断
    out = []
    for tok in src.split("|"):
        file, sep, loc = tok.strip().partition("#")
        if sep:
            out.append((file.strip(), loc.strip()))
    return out


def source_hit(src, file: str, loc: str) -> bool:
    if src.file_path != file:
        return False
    if not loc:  # 空定位（如 tool://glucose_summary#）只要求来源匹配
        return True
    if loc.endswith("页") and loc[1:-1].isdigit():
        return src.page == int(loc[1:-1])
    if ":" in loc:
        return src.time_code == loc
    # 知识卡的定位就是小标题原文，PDF 段落则是"第N段"，两者都按 section相等判断
    return src.section == loc


def hits_expected(ev: Evidence, expected: list[tuple[str, str]]) -> bool:
    return any(source_hit(ev.source, f, loc) for f, loc in expected)


def retrieval_metrics(rows: list[dict], retriever: R2RClient) -> dict:
    hits5 = mrr = n = 0
    per_type: dict[str, list] = {}
    for row in rows:
        if row["qtype"] == "库外":
            continue
        # 工具证据由 executor 现场算出，检索器不可能召回，不能算进检索指标
        expected = [(f, loc) for f, loc in parse_expected(row["expected_sources"]) if not f.startswith("tool://")]
        if not expected:
            continue
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
            # 计算题的个人读数/档案：工具入参只能来自这里，不能让模型编数
            **(json.loads(row["context"]) if row.get("context") else {}),
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


def answer_text(r: dict) -> str:
    """评用户真正读到的文本：成文回答优先，未成文时退回断言拼接。"""
    return r["deliverable"].get("answer") or "；".join(a.text for a in r["assertions"])


def pipeline_metrics(results: list[dict], judge: Judge) -> dict:
    cite_ok = cite_all = refused_ok = refused_n = 0
    gold_hit = gold_n = cite_resolved = cite_total = composed = 0
    scores = []
    for r in results:
        row, d = r["expected"], r["deliverable"]
        pool = r["evidence_pool"]
        expected = parse_expected(row["expected_sources"])
        if row["qtype"] == "库外":
            refused_n += 1
            refused_ok += 1 if d.get("refused") else 0
            continue
        cited = [c for a in r["assertions"] for c in a.cites]
        cite_total += len(cited)
        cite_resolved += sum(1 for c in cited if c in pool)
        gold_n += 1
        gold_hit += int(any(hits_expected(pool[c], expected) for c in cited if c in pool))
        for c in cited:
            if c in pool:
                cite_all += 1
                cite_ok += 1 if hits_expected(pool[c], expected) else 0
        ans = answer_text(r)
        composed += 1 if d.get("answer") else 0
        scores.append(judge.score(row["question"], row["expected_answer"], ans))
    stats = [citation.assertion_stats(r["assertions"], r["evidence_pool"]) for r in results]
    total = sum(s["total"] for s in stats)
    return {
        "n": len(results),
        # 关键来源命中率：答案是否引到了金标标注的那一段（衡量"引对没有"）
        "gold_source_coverage": round(gold_hit / gold_n, 4) if gold_n else 0.0,
        # 引用可解析率：引用编号是否都能在证据池里找到原文（衡量"能不能点开核验"）
        "citation_resolvable": round(cite_resolved / cite_total, 4) if cite_total else 0.0,
        # 严格精确率：金标只标最小关键来源集，答案附带的合理延伸引用会被算作不命中，天然偏低
        "citation_accuracy": round(cite_ok / cite_all, 4) if cite_all else 0.0,
        "no_source_rate": round((total - sum(s["cited"] for s in stats)) / max(total, 1), 4),
        "answer_score": round(sum(scores) / len(scores), 4) if scores else 0.0,
        # 成文率：多少题真的交出了连贯回答，而不是校验不过退回逐条断言
        "composed_rate": round(composed / gold_n, 4) if gold_n else 0.0,
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
        ans_rag = answer_text(r)
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
