"""W3.5 注入拦截评测：样本库全量过 RuleGuard，出拦截率/误拦率。

用法：
  .venv/bin/python eval/run_guard_eval.py
"""
import json
import sys
import time
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from adapters.guard.rule_guard import RuleGuard

RESULTS = ROOT / "eval" / "results"


def main() -> None:
    data = json.loads((ROOT / "eval" / "guard_samples.json").read_text(encoding="utf-8"))
    guard = RuleGuard()
    blocked = defaultdict(int)
    total = defaultdict(int)
    misses: list[dict] = []
    t0 = time.time()
    for s in data["samples"]:
        verdict = guard.inspect_input(s["text"])
        hit = not verdict.allowed
        total[s["category"]] += 1
        blocked[s["category"]] += int(hit)
        if hit != s["should_block"]:
            misses.append({"id": s["id"], "text": s["text"], "expected_block": s["should_block"], "got_block": hit})
    elapsed = round((time.time() - t0) * 1000, 1)
    inj = [c for c in total if c != "良性"]
    report = {
        "version": data["version"],
        "n_total": len(data["samples"]),
        "block_rate_per_class": {c: f"{blocked[c]}/{total[c]}" for c in inj},
        "overall_block_rate": round(sum(blocked[c] for c in inj) / max(sum(total[c] for c in inj), 1), 4),
        "false_positive_rate": round(blocked["良性"] / max(total["良性"], 1), 4),
        "benign_blocked": f"{blocked['良性']}/{total['良性']}",
        "misses": misses,
        "latency_ms_per_call": round(elapsed / len(data["samples"]), 2),
    }
    print(json.dumps({k: v for k, v in report.items() if k != "misses"}, ensure_ascii=False, indent=2))
    if misses:
        print("未命中样本：")
        for m in misses:
            print(" ", m["id"], "期望拦截" if m["expected_block"] else "期望放行", "|", m["text"])
    RESULTS.mkdir(exist_ok=True)
    out = RESULTS / f"guard_{time.strftime('%m%d_%H%M')}.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("saved ->", out)


if __name__ == "__main__":
    main()
