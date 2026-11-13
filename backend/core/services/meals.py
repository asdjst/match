"""个人餐食记录 → 可引用证据。

与本地/联网检索不同，这里查的是用户自己的结构化记录（时间、食物、克数、餐前/餐后血糖），
只作为“一次观察”呈现，不据此推断因果或药物建议。
"""

import re
from datetime import date, datetime, timedelta

from core.schemas.common import SourceRef
from core.schemas.evidence import Evidence
from core.schemas.prompt import PromptBundle
from core.services.store import MealStore

# 没有点名食物、但明确在问“以前那顿”时，回退到最近几条记录。
# 用正则覆盖自然说法（上一餐 / 上顿饭 / 前一顿 …），子串列表容易漏词导致该召回却没召回
_RECALL_CUE_RE = re.compile(
    r"[上前]\s*一?\s*[餐顿]"  # 上一餐 / 上顿饭 / 前一顿 …
    r"|上次|上一次|上回|之前|以前|吃过|那次|这顿|记得|记录|记忆"
)


def recall_cue_hit(question: str) -> bool:
    """规则 cue 是否命中；正则没覆盖的回忆性问法由调用方用模型意图分类补判。"""
    return bool(_RECALL_CUE_RE.search(question))


_INTENT_SYSTEM = (
    "你是个人历史意图分类器。判断用户的问题是否在询问本人（用户自己）的餐食、血糖等个人记录历史，"
    "包括回忆性问法，例如“上一餐吃了什么”“那顿饭后来怎么样”“我之前吃过燕麦吗”“我这周碳水多少”“昨天血糖怎么样”。"
    "纯饮食知识问题（“米饭多少碳水”）、泛泛的建议咨询（“血糖偏高怎么办”）、与个人历史无关的问题，都判为 false。"
    "只输出合法 JSON，不要输出任何解释。"
)


def history_intent_prompt(question: str) -> PromptBundle:
    """fast 档意图分类 prompt：正则 cue 漏掉的回忆性问法交给模型判断。"""
    return PromptBundle(
        role="planner",
        system=_INTENT_SYSTEM,
        task=f"QUESTION: {question}\n该问题是否在询问用户本人的餐食/血糖等个人记录历史？",
        format_hint='{"personal": true/false, "reason": "一句话依据"}',
    )

# “今天吃了什么”这类按天盘点：只认明确的发问方式，避免“今天血糖高怎么办”误拉餐食
_DAY_SCOPES = (("前天", 2), ("昨天", 1), ("今日", 0), ("今天", 0))
_DAY_LIST_CUES = ("吃了什么", "吃了啥", "吃什么了", "吃过什么", "吃过啥", "吃了哪些", "吃了些什么", "都有什么")


def _day_scope(question: str) -> tuple[str, int] | None:
    for label, offset in _DAY_SCOPES:
        if label in question:
            return label, offset
    return None


def _meal_date(eaten_at: str) -> date | None:
    try:
        return datetime.strptime((eaten_at or "")[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def _empty_day_evidence(target: date, label: str, has_any: bool) -> Evidence:
    quote = (
        f"个人记录：{target.isoformat()}（{label}）没有餐食记录"
        if has_any
        else "个人记录：健康档案还没有任何餐食记录"
    )
    return Evidence(
        doc_id="meal-day",
        quote=quote,
        score=1.0,
        source=SourceRef(file_path="个人餐食记录"),
        channel="memory",
    )


def _empty_archive_evidence() -> Evidence:
    """新用户问自己的历史时也要有据可依：给一条“还没有记录”，而不是让整轮变成无引用拒答。"""
    return Evidence(
        doc_id="meal-empty",
        quote="个人记录：健康档案还没有任何餐食记录，无法回答与本人饮食或血糖历史相关的问题",
        score=1.0,
        source=SourceRef(file_path="个人餐食记录"),
        channel="memory",
    )


def _meal_time(eaten_at: str) -> str:
    """ISO 本地时间 → “2026-11-08 12:30”；解析失败就原样截断。"""
    text = (eaten_at or "").replace("T", " ")
    return text[:16]


def _foods_text(foods: list[dict]) -> str:
    parts: list[str] = []
    for food in foods[:8]:
        name = str(food.get("name") or "").strip()
        if not name:
            continue
        grams = food.get("grams")
        piece = f"{name} 约{grams:g}g" if isinstance(grams, (int, float)) and grams > 0 else name
        carbs = food.get("carbs_g")
        if isinstance(carbs, (int, float)):
            piece += f"（碳水约{carbs:g}g{'，食物库估算' if food.get('estimated') else ''}）"
        parts.append(piece)
    return "、".join(parts)


def _timing_label(minutes: int) -> str:
    """0 分钟表示餐前；整小时说“餐后 X 小时”，其余说分钟。"""
    if minutes <= 0:
        return "餐前"
    if minutes % 60 == 0:
        return f"餐后 {minutes // 60} 小时"
    return f"餐后 {minutes} 分钟"


def _readings_text(readings: list[dict]) -> str:
    if not readings:
        return "未记录血糖"
    parts = [
        f"{_timing_label(int(r.get('minutes_after') or 0))} {float(r.get('value_mmol')):g} mmol/L"
        for r in readings[:3]
        if r.get("value_mmol") is not None
    ]
    return "血糖：" + "，".join(parts) if parts else "未记录血糖"


def _to_evidence(meal: dict) -> Evidence:
    quote = f"个人记录：{_meal_time(meal.get('eaten_at', ''))} {meal.get('meal_type', '')}，{_foods_text(meal.get('foods') or [])}"
    if meal.get("gl") is not None:
        quote += f"；整餐 GL 约 {float(meal['gl']):g}"
    quote += f"；{_readings_text(meal.get('readings') or [])}"
    if meal.get("note"):
        quote += f"；备注：{str(meal['note'])[:80]}"
    return Evidence(
        doc_id=f"meal-{meal.get('meal_id', '')}",
        quote=quote,
        score=1.0,
        source=SourceRef(file_path="个人餐食记录"),
        channel="memory",
    )


def _meal_summary(meal: dict) -> str:
    return f"{_meal_time(meal.get('eaten_at', ''))} {meal.get('meal_type', '')}，{_foods_text(meal.get('foods') or [])}"


_STATS_TIME_CUES = ("今天", "今日", "昨天", "这周", "本周", "最近", "近7天", "近 7 天")


def _stats_kind(question: str) -> str | None:
    personal = any(word in question for word in ("我", "记录", "档案", *_STATS_TIME_CUES))
    if not personal:
        return None
    if any(word in question for word in ("血糖", "读数", "波动")):
        return "glucose"
    if any(word in question for word in ("碳水", "摄入")):
        return "carbs"
    return None


def _stats_window(question: str, kind: str) -> tuple[date, date, str]:
    today = date.today()
    day = _day_scope(question)
    if day:
        label, offset = day
        target = today - timedelta(days=offset)
        return target, target, f"{label} {target.isoformat()}"
    if any(word in question for word in ("这周", "本周", "近7天", "近 7 天")):
        return today - timedelta(days=6), today, "最近 7 天"
    days = 14 if kind == "glucose" else 7
    return today - timedelta(days=days - 1), today, f"最近 {days} 天"


def _meal_carbs(meal: dict) -> float:
    carbs = meal.get("carbs_g")
    if isinstance(carbs, (int, float)):
        return float(carbs)
    return sum(float(food.get("carbs_g") or 0) for food in (meal.get("foods") or []))


def _stats_evidence(meals: list[dict], question: str, kind: str) -> Evidence:
    """血糖 / 碳水统计：把区间内的记录先算好，避免分析员自己做加法。"""
    start, end, label = _stats_window(question, kind)
    scoped = [
        meal for meal in meals
        if (d := _meal_date(meal.get("eaten_at", ""))) is not None and start <= d <= end
    ]

    if kind == "glucose":
        rows: list[tuple[dict, dict]] = []
        for meal in scoped:
            for reading in meal.get("readings") or []:
                if reading.get("value_mmol") is not None:
                    rows.append((meal, reading))
        rows.sort(key=lambda item: item[1].get("measured_at") or "")
        if not rows:
            quote = f"个人记录统计（{label}）：没有记录血糖。"
        else:
            parts = [
                f"{_meal_time(meal.get('eaten_at', ''))} {meal.get('meal_type', '')} "
                f"{_foods_text(meal.get('foods') or [])[:50]}："
                f"{_timing_label(int(reading.get('minutes_after') or 0))} "
                f"{float(reading.get('value_mmol')):g} mmol/L"
                for meal, reading in rows[:6]
            ]
            more = f"；另有 {len(rows) - 6} 条" if len(rows) > 6 else ""
            quote = f"个人记录统计（{label}）：共 {len(rows)} 条血糖记录；" + "；".join(parts) + more
    elif not scoped:
        quote = f"个人记录统计（{label}）：没有餐食记录。"
    else:
        daily: dict[date, dict[str, float]] = {}
        for meal in scoped:
            day = _meal_date(meal.get("eaten_at", ""))
            if day is None:
                continue
            entry = daily.setdefault(day, {"carbs": 0.0, "count": 0.0})
            entry["carbs"] += _meal_carbs(meal)
            entry["count"] += 1
        parts = [
            f"{day.strftime('%m/%d')} {entry['carbs']:g}g（{int(entry['count'])} 餐）"
            for day, entry in sorted(daily.items())
        ]
        total = sum(entry["carbs"] for entry in daily.values())
        quote = f"个人记录统计（{label}）：共 {len(scoped)} 餐，碳水合计 {total:g}g；" + "；".join(parts)

    return Evidence(
        doc_id="meal-stats",
        quote=quote,
        score=1.0,
        source=SourceRef(file_path="个人餐食记录"),
        channel="memory",
    )


def _check_evidence(meals: list[dict], targets: list[str]) -> Evidence | None:
    """核对“这份餐以前吃过吗”：直接给出命中/未命中结论，避免分析员把无关记录当答案。"""
    names = {
        str(food.get("name") or "").strip()
        for meal in meals
        for food in (meal.get("foods") or [])
        if str(food.get("name") or "").strip()
    }
    wanted = [t for t in dict.fromkeys(targets) if t]
    if not wanted:
        return None
    if not meals:
        return Evidence(
            doc_id="meal-check",
            quote="个人记录核对：健康档案中还没有任何餐食记录，无法核对这份餐是否吃过",
            score=1.0,
            source=SourceRef(file_path="个人餐食记录"),
            channel="memory",
        )
    matched = {
        t for t in wanted
        if any(t == name or (len(t) >= 2 and (t in name or name in t)) for name in names)
    }
    if matched:
        def _hits(meal: dict) -> bool:
            for food in meal.get("foods") or []:
                name = str(food.get("name") or "").strip()
                if any(t == name or (len(name) >= 2 and (t in name or name in t)) for t in matched):
                    return True
            return False

        quoted = "、".join(_meal_summary(m) for m in [m for m in meals if _hits(m)][:3])
        quote = f"个人记录核对：找到 {'、'.join(sorted(matched))} 的记录：{quoted}"
    else:
        latest = "；".join(_meal_summary(m) for m in meals[:3])
        quote = (
            f"个人记录核对：健康档案现有 {len(meals)} 条餐食记录，未发现 "
            f"{'、'.join(wanted)}；最近记录：{latest}"
        )
    return Evidence(
        doc_id="meal-check",
        quote=quote,
        score=1.0,
        source=SourceRef(file_path="个人餐食记录"),
        channel="memory",
    )


def memory_evidences(
    store: MealStore,
    user_id: str,
    question: str,
    limit: int = 4,
    target_foods: list[str] | None = None,
    semantic_cue: bool = False,
) -> list[Evidence]:
    """按食物名或“今天/昨天吃了什么”命中个人记录；明确问“上次”时回退到最近记录。

    仅凭“提到食物”不会命中——例如“米饭多少碳水”是知识问题，
    但如果用户记录过米饭，仍会附带最多一条历史，供分析员补充个人观察。
    拍照附带的食物名会额外生成一条“吃过没有”的核对证据。
    """
    if not user_id or not question:
        return []
    meals = store.list_meals(user_id, limit=60)
    # 规则 cue + 模型意图分类（semantic_cue）：宁可多召回几条个人记录，也别漏掉回忆性问法
    cue = recall_cue_hit(question) or semantic_cue
    day = _day_scope(question)
    day_list = day is not None and any(word in question for word in _DAY_LIST_CUES)
    if not meals:
        if day_list and day:
            label, offset = day
            return [_empty_day_evidence(date.today() - timedelta(days=offset), label, has_any=False)]
        if cue and target_foods:
            check = _check_evidence(meals, target_foods)
            return [check] if check else []
        if cue or _stats_kind(question):
            return [_empty_archive_evidence()]
        return []

    if day_list and day:
        label, offset = day
        target = date.today() - timedelta(days=offset)
        scoped = [meal for meal in meals if _meal_date(meal.get("eaten_at", "")) == target]
        if not scoped:
            return [_empty_day_evidence(target, label, has_any=True)]
        scoped.sort(key=lambda meal: meal.get("eaten_at") or "")
        return [_to_evidence(meal) for meal in scoped[: max(limit, 8)]]

    names = {
        str(food.get("name") or "").strip()
        for meal in meals
        for food in (meal.get("foods") or [])
        if str(food.get("name") or "").strip()
    }
    matched = {name for name in names if len(name) >= 2 and name in question}
    stats = _stats_kind(question)

    if matched:
        picked = [
            meal for meal in meals
            if any(str(food.get("name") or "").strip() in matched for food in (meal.get("foods") or []))
        ][:limit]
    elif stats:
        return [_stats_evidence(meals, question, stats)]
    elif cue:
        picked = meals[: min(limit, 3)]
    else:
        picked = []

    evidences = [_to_evidence(meal) for meal in picked]
    if cue and target_foods:
        check = _check_evidence(meals, target_foods)
        if check is not None:
            evidences.insert(0, check)
    return evidences


def recent_glucose_values(store: MealStore, user_id: str, days: int = 14) -> list[float]:
    """最近 days 天的个人血糖读数，按测量时间升序。

    给 glucose_summary 工具当确定性入参：数值直接来自记录表，
    不从证据文本里正则抠数，也不让模型自己填。
    """
    if not user_id:
        return []
    start = date.today() - timedelta(days=days - 1)
    rows: list[tuple[str, float]] = []
    for meal in store.list_meals(user_id, limit=200):
        day = _meal_date(meal.get("eaten_at", ""))
        if day is None or day < start:
            continue
        for reading in meal.get("readings") or []:
            value = reading.get("value_mmol")
            if value is not None:
                rows.append((reading.get("measured_at") or "", float(value)))
    rows.sort(key=lambda item: item[0])
    return [value for _, value in rows]
