"""节点共用工具：证据池、依赖/预算门控、prompt 拼装。"""

import re
import time

from core.schemas.dag import Budget, TaskDAG
from core.schemas.evidence import Evidence
from core.services.injection import neutralize

_CHANNEL_LABELS = {"local": "本地库", "web": "Web", "cloud": "云端网盘", "image": "拍照", "tool": "工具", "memory": "个人记录"}


def _pool(state: dict) -> dict[str, Evidence]:
    return {k: Evidence(**v) for k, v in state.get("evidence", {}).items()}


def _deps_block(spec, dag: TaskDAG, node_results: dict) -> str | None:
    """depends_on 门控：上游检索/计算节点未成功时，下游节点直接标记 blocked。
    planner/analyst/critic 不在 node_results 里执行，忽略这类依赖。"""
    roles = {n.node_id: n.role for n in dag.nodes}
    for dep in spec.depends_on:
        if dep == spec.node_id:
            continue
        if roles.get(dep) not in ("retriever", "executor"):
            continue
        res = node_results.get(dep) or {}
        if res.get("status") != "done":
            return f"依赖未完成：{dep}"
    return None


def _budget_limits(dag: TaskDAG) -> tuple[int, int]:
    """整体预算取各节点声明里最宽的一份：真实 planner 会给不同节点写不同上限，
    按首节点取会把正常的短计划误判成预算耗尽。"""
    budgets = [n.budget for n in dag.nodes] or [Budget()]
    return max(b.max_steps for b in budgets), max(b.timeout_s for b in budgets)


def _budget_stop(state: dict, dag: TaskDAG, include_steps: bool = True) -> str | None:
    """预算门控：按已执行任务节点数（检索/计算）与墙钟时间判断，返回耗尽原因。
    节点内检查时看步数+耗时；critic 收尾只看耗时——计划内工作已做完时，
    steps 恰好等于上限不算异常。"""
    max_steps, timeout_s = _budget_limits(dag)
    steps = int(state.get("steps", 0))
    if include_steps and steps >= max_steps:
        return f"步数预算用尽（{steps}/{max_steps}）"
    started = state.get("started_at")
    if started:
        elapsed = time.monotonic() - float(started)
        if elapsed > timeout_s:
            return f"耗时预算用尽（{int(elapsed)}s > {timeout_s}s）"
    return None


def _history_block(history: list[dict] | None) -> str:
    """把最近几轮问答拼成 prompt 前缀；只用于消解指代，明确禁止当证据。"""
    lines: list[str] = []
    for item in (history or [])[-3:]:
        question = (item.get("question") or "").strip()
        if not question:
            continue
        lines.append(f"Q: {question}")
        answer = (item.get("answer") or "").strip()
        if answer:
            lines.append(f"A: {answer[:160]}")
    if not lines:
        return ""
    return "【对话历史（仅用于理解指代，不得当作证据）】\n" + "\n".join(lines) + "\n\n"


def _food_block(food_items: list[dict] | None) -> str:
    """餐食上下文：让 planner 知道碳水数据已就绪，不必再为照片内容规划检索。"""
    items = [i for i in (food_items or []) if isinstance(i, dict) and i.get("name")]
    if not items:
        return ""
    lines: list[str] = []
    low = high = 0.0
    for item in items[:20]:
        low += float(item.get("carbs_g_low") or 0)
        high += float(item.get("carbs_g_high") or 0)
        lines.append(
            f"- {item['name']} {item.get('grams_low')}-{item.get('grams_high')}g，"
            f"碳水 {item.get('carbs_g_low')}-{item.get('carbs_g_high')}g"
        )
    return (
        "【已识别的餐食（拍照/用户修正，仅作规划上下文）】\n"
        + "\n".join(lines)
        + f"\n整餐合计碳水 {low:g}-{high:g}g。\n\n"
    )


def _profile_block(profile: dict | None) -> str:
    """用户自填档案：只用于调整建议口径，明确禁止当证据或据此做诊断。"""
    if not profile:
        return ""
    parts: list[str] = []
    if profile.get("age"):
        parts.append(f"{profile['age']} 岁")
    if profile.get("height_cm") and profile.get("weight_kg"):
        parts.append(f"身高 {profile['height_cm']:g}cm、体重 {profile['weight_kg']:g}kg")
    if profile.get("bmi"):
        parts.append(f"BMI {profile['bmi']:g}")
    line1 = "；".join(parts)
    line2 = []
    if profile.get("activity"):
        line2.append(f"日常活动量：{profile['activity']}")
    if profile.get("goal"):
        line2.append(f"当前目标：{profile['goal']}")
    body = "；".join(x for x in [line1, "；".join(line2)] if x)
    if not body:
        return ""
    return (
        "【用户代谢档案（本人填写，仅用于调整份量与活动建议，不是证据、不作诊断）】\n"
        f"{body}。\n"
        "建议中不要罗列档案数值，不要据此推断疾病或并发症，也不得给出用药/胰岛素调整建议。\n\n"
    )


def _evidence_block(pool: dict[str, Evidence]) -> str:
    # 分隔符用 " :: "：语料 quote 里可能自带 "|"（表格行），不能用竖线
    lines = []
    for eid, ev in pool.items():
        # 证据原文保留给引用展示，进 prompt 前中和掉指令型片段，避免被检索内容劫持
        quote, hits = neutralize(ev.quote)
        note = "（已过滤可疑指令）" if hits else ""
        lines.append(
            f"{eid} :: {quote}{note} :: ({ev.source.label()} · {_CHANNEL_LABELS.get(ev.channel, ev.channel)})"
        )
    return "\n".join(lines)


def _next_id(pool: dict[str, Evidence]) -> str:
    ids = [int(m) for eid in pool for m in re.findall(r"E(\d+)", eid)]
    return f"E{max(ids, default=0) + 1}"
