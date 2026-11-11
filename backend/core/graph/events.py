import math
import time
from collections import Counter, defaultdict, deque


_CHANNELS = {"local": "本地库", "web": "网页", "cloud": "云端网盘"}
_ROLES = {"planner": "规划", "retriever": "检索", "analyst": "分析"}


def epoch_ms() -> int:
    return time.time_ns() // 1_000_000


def _role_results(role: str, delta: dict, state: dict, before: dict) -> tuple[list, int]:
    specs = [n for n in (state.get("dag") or {}).get("nodes", []) if n.get("role") == role]
    previous = before.get("node_results") or {}
    returned = delta.get("node_results") or {}
    # These roles shallow-copy node_results, replacing only the tasks handled now.
    # Identity (not equality) distinguishes a repeated identical result from a budget skip.
    current = [
        (spec, returned[spec["node_id"]]) for spec in specs
        if spec["node_id"] in returned and returned[spec["node_id"]] is not previous.get(spec["node_id"])
    ]
    return current, len(specs) - len(current)


def _numeric_results(tool: str, output: dict) -> list[str]:
    def number(value):
        return type(value) in (int, float) and math.isfinite(value)

    result = output.get("result")
    if tool == "growth_rate" and number(result):
        unit = "%" if output.get("unit") == "%" else ""
        return [f"增长率 {result}{unit}"]
    if tool == "calculate_gl" and number(result):
        return [f"GL 估算值 {result}"]
    if tool == "query_food_nutrition" and isinstance(result, dict):
        return [
            f"{label} {result[key]}{unit}"
            for key, label, unit in [("carbs_per_100g", "每100g碳水", "g"), ("gi", "GI", "")]
            if number(result.get(key))
        ]
    return []


def node_summary(node: str, delta: dict, state: dict, before: dict) -> str:
    """Only structured, completed results; never quote prompts, claims or errors."""
    if node == "planner":
        return f"已完成任务规划，生成 {len((delta.get('dag') or {}).get('nodes', []))} 项任务。"
    if node == "retriever":
        current, skipped = _role_results(node, delta, state, before)
        pool = delta.get("evidence") or {}
        old_pool = before.get("evidence") or {}
        ids = {
            eid for _, result in current for eid in result.get("evidence_used", [])
            if eid not in old_pool and eid in pool
        }
        channels = Counter(pool[eid].get("channel", "local") for eid in ids)
        counts = "、".join(f"{label} {channels[ch]} 条" for ch, label in _CHANNELS.items() if channels[ch])
        summary = f"本次检索新增 {len(ids)} 条去重证据" + (f"（{counts}）" if counts else "") + "。"
        hits = Counter()
        unavailable = set()
        for _, result in current:
            for report in result.get("retrievals") or []:
                ch = report.get("channel")
                if ch not in _CHANNELS:
                    continue
                count = report.get("hits")
                if type(count) is int and count >= 0:
                    hits[ch] += count
                if report.get("status") != "ok":
                    unavailable.add(ch)
        details = []
        if hits:
            details.append("本次通道命中：" + "、".join(
                f"{label} {hits[ch]} 条" for ch, label in _CHANNELS.items() if ch in hits
            ))
        if unavailable:
            details.append("未正常完成的通道：" + "、".join(_CHANNELS[ch] for ch in _CHANNELS if ch in unavailable))
        blocked = sum(r.get("status") == "blocked" for _, r in current)
        if blocked or skipped:
            details.append(f"检索任务阻塞 {blocked} 项、跳过 {skipped} 项")
        return summary + ("；".join(details) + "。" if details else "")
    if node == "executor":
        current, skipped = _role_results(node, delta, state, before)
        succeeded = failed = blocked = 0
        numbers = []
        for spec, result in current:
            blocked += result.get("status") == "blocked"
            output = result.get("output") or {}
            if "calls" in output:
                for call in output["calls"]:
                    if call.get("ok") is True:
                        succeeded += 1
                        numbers.extend(_numeric_results(call.get("tool"), call))
                    else:
                        failed += 1
            elif result.get("status") == "done" and output:
                succeeded += 1
                numbers.extend(_numeric_results(spec.get("tool"), output))
        summary = f"本次工具调用成功 {succeeded} 次、失败记录 {failed} 次，任务阻塞 {blocked} 项、跳过 {skipped} 项。"
        return summary + ("数值结果：" + "、".join(numbers[:2]) + "。" if numbers else "")
    if node == "analyst":
        assertions = delta.get("assertions") or []
        cites = {c for a in assertions for c in a.get("cites", [])}
        return f"本轮分析形成 {len(assertions)} 条断言，引用 {len(cites)} 个不同证据编号。"
    if node == "critic":
        verdict = delta.get("verdict") or {}
        if state.get("budget_stop"):
            return "预算限制下已转入降级交付，未执行完整审校。"
        if verdict.get("verdict") == "send_back":
            target = _ROLES.get(verdict.get("send_back_to"))
            return (
                f"本轮审校要求返工，记录 {len(verdict.get('issues') or [])} 项问题"
                + (f"，建议交由{target}处理" if target else "") + "。"
            )
        if verdict.get("verdict") == "pass":
            return "本轮流程审校通过，可进入交付；不代表医学结论已获验证。"
        return "本轮审校已返回，未记录通过结论。"
    if node == "writer":
        deliverable = delta.get("deliverable") or {}
        if not deliverable:
            return "本步已返回，未生成交付物。"
        if deliverable.get("refused"):
            return "已生成拒答式降级交付物。" if deliverable.get("degraded") else "已生成拒答结果，未给出正常结论。"
        if deliverable.get("degraded"):
            return "已生成降级交付物，不作为完整流程的正常交付。"
        return "已生成交付物。"
    return "本步执行已返回。"


class NodeEventLog:
    """Join private completion metrics with actual graph updates, preserving repeats."""

    def __init__(self, snapshot: dict | None = None, started_at: float | None = None):
        snapshot = snapshot or {}
        self.node_events = list(snapshot.get("node_events") or [])
        self.timings = list(snapshot.get("timings") or [])
        self.duration_ms = snapshot.get("duration_ms") or 0
        self.started_at = time.monotonic() if started_at is None else started_at
        self._completed = defaultdict(deque)

    def custom(self, payload: dict) -> dict | None:
        if payload.get("type") == "node" and payload.get("status") == "running":
            return {key: payload[key] for key in ("type", "node", "status", "round_no", "at")}
        if payload.get("type") == "_node_completed":
            self._completed[payload["node"]].append(payload)
        return None

    def done(self, node: str) -> dict:
        completed = self._completed[node].popleft()
        event = {
            "type": "node", "node": node, "status": "done",
            # The input round identifies the execution; a critic's new round applies to the next node.
            "round_no": completed["round_no"], "at": epoch_ms(),
            "elapsed_ms": completed["elapsed_ms"], "summary": completed["summary"],
        }
        self.node_events.append(event)
        self.timings.append({"node": node, "ms": event["elapsed_ms"], "round_no": event["round_no"], "at": event["at"]})
        return event

    def snapshot(self, state: dict) -> dict:
        return {
            **state,
            "node_events": list(self.node_events),
            "timings": list(self.timings),
            # Approval adds active resume time, not time spent waiting for a person.
            "duration_ms": self.duration_ms + int((time.monotonic() - self.started_at) * 1000),
        }
