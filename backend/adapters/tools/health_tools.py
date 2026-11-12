"""控糖领域确定性计算：血糖统计、整餐血糖负荷、每日碳水估算。

MCP server 与 FakeTools 共用同一份算法，保证在线/离线两条路径数值一致。
血糖统计口径与前端 frontend/src/lib/glucoseStats.ts 逐项对齐：
手动点测读数只能算「读数占比」，不是动态血糖的时间占比，也不推算糖化血红蛋白。
"""

from __future__ import annotations

import math

try:  # mcp_server.py 作为脚本启动时 sys.path 只含本目录
    from adapters.tools.food_data import SOURCE, lookup
except ModuleNotFoundError:
    from food_data import SOURCE, lookup

# 多数成人通用目标；严格/宽松目标由调用方传 low/high 覆盖
DEFAULT_LOW = 3.9
DEFAULT_HIGH = 10.0
# 高于上限 3.9 mmol/L 视为明显偏高，对应 CGM 的 TAR 二级（10.0 → 13.9）
HIGH2_OFFSET = 3.9
SEVERE_LOW = 3.0

ZONE_ORDER = ("low2", "low", "ok", "high", "high2")
ZONE_LABELS = {
    "low2": "严重偏低",
    "low": "偏低",
    "ok": "达标",
    "high": "偏高",
    "high2": "明显偏高",
}

GLUCOSE_SOURCE = (
    "口径：手动点测读数统计。占比按读数条数计算，不是动态血糖的时间占比；"
    "标准差用 n-1，CV=SD/均值，LAGE=最高−最低。不补点、不预测、不推算糖化血红蛋白。"
)

# 理想体重简易公式与活动系数（kcal/kg 理想体重），中国糖尿病膳食指南常见口径
ACTIVITY_KCAL = {"久坐": (25, 30), "轻度活动": (30, 35), "规律运动": (35, 40)}
CARB_RATIO = (0.45, 0.60)
KCAL_PER_CARB_G = 4.0
# 三餐碳水分配 1/5、2/5、2/5
MEAL_SHARE = {"早餐": 0.2, "午餐": 0.4, "晚餐": 0.4}
CARB_SOURCE = (
    "估算口径：理想体重=身高cm−105；每日能量=理想体重×活动系数（久坐25-30、轻度活动30-35、"
    "规律运动35-40 kcal/kg）；碳水供能比45%-60%，1g碳水=4kcal；三餐按1/5、2/5、2/5分配。"
)


def zone_of(value: float, low: float = DEFAULT_LOW, high: float = DEFAULT_HIGH) -> str:
    if value < SEVERE_LOW:
        return "low2"
    if value < low:
        return "low"
    if value <= high:
        return "ok"
    if value <= high + HIGH2_OFFSET:
        return "high"
    return "high2"


def glucose_summary(
    values: list[float], low: float = DEFAULT_LOW, high: float = DEFAULT_HIGH
) -> dict | None:
    """均值/标准差/CV/极差/五区间读数占比；空列表或非法目标区间返回 None。"""
    if not values or high <= low or low <= 0:
        return None
    nums = [float(v) for v in values]
    if any(not math.isfinite(v) for v in nums):
        return None
    n = len(nums)
    counts = {zone: 0 for zone in ZONE_ORDER}
    for value in nums:
        counts[zone_of(value, low, high)] += 1
    mean = sum(nums) / n
    sd = math.sqrt(sum((v - mean) ** 2 for v in nums) / (n - 1)) if n > 1 else None
    lowest, highest = min(nums), max(nums)
    return {
        "n": n,
        "mean": round(mean, 2),
        "sd": round(sd, 2) if sd is not None else None,
        "cv": round(sd / mean * 100, 1) if sd is not None and mean > 0 else None,
        "min": lowest,
        "max": highest,
        "lage": round(highest - lowest, 1) if n > 1 else None,
        "target": {"low": low, "high": high},
        "counts": counts,
        "pct": {zone: round(counts[zone] / n * 100, 1) for zone in ZONE_ORDER},
        "source": GLUCOSE_SOURCE,
    }


def meal_gl_total(foods: list[dict]) -> dict | None:
    """整餐血糖负荷合计：逐项 GI×碳水/100 再相加。

    未收录的食物进 missing，GI 未收录但碳水已知的进 unknown_gi：
    碳水合计覆盖两者，GL 合计只覆盖 GI 已收录项（partial=True），
    避免把单点 GL 当成整餐值。全部未收录或碳水为负返回 None。
    """
    items: list[dict] = []
    unknown: list[dict] = []
    missing: list[str] = []
    for food in foods or []:
        name = str(food.get("name") or "").strip()
        if not name:
            continue
        carbs = float(food.get("carbs_g") or 0)
        if carbs < 0:
            return None
        item = lookup(name)
        if item is None:
            missing.append(name)
            continue
        if item["gi"] is None:
            unknown.append({"name": name, "carbs_g": round(carbs, 1)})
            continue
        items.append({
            "name": name,
            "carbs_g": round(carbs, 1),
            "gi": item["gi"],
            "gl": round(item["gi"] * carbs / 100, 1),
        })
    if not items and not unknown:
        return None
    return {
        # 没有 GI 已收录项时给 None，而不是 0，免得被读成“整餐 GL 为 0”
        "total_gl": round(sum(i["gl"] for i in items), 1) if items else None,
        "total_carbs_g": round(sum(i["carbs_g"] for i in items) + sum(u["carbs_g"] for u in unknown), 1),
        "items": items,
        "unknown_gi": unknown,
        "missing": missing,
        "partial": bool(missing or unknown),
        "source": SOURCE,
    }


def carb_target(
    height_cm: float | None = None,
    activity: str | None = None,
    weight_kg: float | None = None,
    goal: str | None = None,
) -> dict | None:
    """按身高与活动量估算每日碳水区间与三餐分配；缺身高或活动量返回 None。"""
    if height_cm is None or activity not in ACTIVITY_KCAL:
        return None
    ideal = float(height_cm) - 105
    if ideal <= 0:
        return None
    kcal_low, kcal_high = ACTIVITY_KCAL[activity]
    energy = (ideal * kcal_low, ideal * kcal_high)
    carbs = (
        energy[0] * CARB_RATIO[0] / KCAL_PER_CARB_G,
        energy[1] * CARB_RATIO[1] / KCAL_PER_CARB_G,
    )
    note = "通用估算区间，需由医生或营养师按本人情况确认，不是用药或诊断依据。"
    if goal == "减重":
        note += "减重目标通常还需下调总能量，本估算未自动下调。"
    out = {
        "ideal_weight_kg": round(ideal, 1),
        "activity": activity,
        "kcal_per_kg": [kcal_low, kcal_high],
        "energy_kcal": [round(energy[0]), round(energy[1])],
        "carb_ratio_pct": [round(CARB_RATIO[0] * 100), round(CARB_RATIO[1] * 100)],
        "carbs_g_per_day": [round(carbs[0]), round(carbs[1])],
        "per_meal_carbs_g": {
            meal: [round(carbs[0] * share), round(carbs[1] * share)]
            for meal, share in MEAL_SHARE.items()
        },
        "goal": goal,
        "note": note,
        "source": CARB_SOURCE,
    }
    if weight_kg is not None:
        out["actual_weight_kg"] = round(float(weight_kg), 1)
    return out