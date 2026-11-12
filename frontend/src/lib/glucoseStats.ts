/**
 * 血糖统计口径：全部基于手动点测读数，不是动态血糖（CGM）。
 * 因此 TIR/TAR/TBR 一律是「读数占比」，不估算时间占比，也不推算糖化血红蛋白。
 */
import type { MealRecord, MealType } from "../types";

export type RangeKey = "6h" | "12h" | "24h" | "3d" | "7d" | "14d" | "30d" | "all";

export const RANGES: { key: RangeKey; label: string; hours: number | null }[] = [
  { key: "6h", label: "6 小时", hours: 6 },
  { key: "12h", label: "12 小时", hours: 12 },
  { key: "24h", label: "24 小时", hours: 24 },
  { key: "3d", label: "3 天", hours: 72 },
  { key: "7d", label: "7 天", hours: 168 },
  { key: "14d", label: "14 天", hours: 336 },
  { key: "30d", label: "30 天", hours: 720 },
  { key: "all", label: "全部", hours: null },
];

export const MEAL_TYPES: MealType[] = ["早餐", "午餐", "晚餐", "加餐"];

/** 目标区间预设：通用 / 严格（妊娠等） / 宽松（老年、易低血糖） */
export const TARGETS = [
  { key: "standard", label: "3.9 – 10.0", low: 3.9, high: 10.0, note: "多数成人通用目标" },
  { key: "strict", label: "3.9 – 7.8", low: 3.9, high: 7.8, note: "严格目标，需医生确认" },
  { key: "loose", label: "3.9 – 11.1", low: 3.9, high: 11.1, note: "宽松目标，需医生确认" },
] as const;

export type TargetKey = (typeof TARGETS)[number]["key"];

export type Zone = "low2" | "low" | "ok" | "high" | "high2";

export const ZONE_ORDER: Zone[] = ["low2", "low", "ok", "high", "high2"];

export const ZONE_LABELS: Record<Zone, string> = {
  low2: "严重偏低",
  low: "偏低",
  ok: "达标",
  high: "偏高",
  high2: "明显偏高",
};

export interface Target {
  low: number;
  high: number;
}

/** 高于目标上限 3.9 mmol/L 视为明显偏高，对应 CGM 的 TAR 二级（10.0 → 13.9） */
export function zoneOf(value: number, target: Target): Zone {
  if (value < 3.0) return "low2";
  if (value < target.low) return "low";
  if (value <= target.high) return "ok";
  if (value <= target.high + 3.9) return "high";
  return "high2";
}

export interface GlucosePoint {
  id: string;
  /** 推算的测量时刻（就餐时间 + 餐后时长），毫秒 */
  t: number;
  value: number;
  minutesAfter: number;
  mealId: string;
  mealType: MealType;
  eatenAt: number;
  carbs: number | null;
  foods: string;
  note: string;
}

export function mealCarbs(meal: MealRecord): number | null {
  if (typeof meal.carbs_g === "number") return meal.carbs_g;
  const known = meal.foods.filter((f) => typeof f.carbs_g === "number");
  if (known.length === 0) return null;
  return known.reduce((sum, f) => sum + (f.carbs_g ?? 0), 0);
}

export function foodsText(meal: MealRecord): string {
  return meal.foods.map((f) => `${f.name} ${Math.round(f.grams)}g`).join("、");
}

/** 后端 measured_at 存的是录入时刻，画 24 小时轴要用餐次时间推算真实测量点 */
export function readingTime(meal: MealRecord, minutesAfter: number, measuredAt: string): number {
  const base = Date.parse(meal.eaten_at);
  if (Number.isNaN(base)) return Date.parse(measuredAt);
  return base + minutesAfter * 60_000;
}

export function toPoints(meals: MealRecord[]): GlucosePoint[] {
  const points: GlucosePoint[] = [];
  for (const meal of meals) {
    for (const reading of meal.readings) {
      const t = readingTime(meal, reading.minutes_after, reading.measured_at);
      if (Number.isNaN(t) || !Number.isFinite(reading.value_mmol)) continue;
      points.push({
        id: reading.reading_id,
        t,
        value: reading.value_mmol,
        minutesAfter: reading.minutes_after,
        mealId: meal.meal_id,
        mealType: meal.meal_type,
        eatenAt: Date.parse(meal.eaten_at),
        carbs: mealCarbs(meal),
        foods: foodsText(meal),
        note: meal.note,
      });
    }
  }
  return points.sort((a, b) => a.t - b.t);
}

export function rangeStart(range: RangeKey, now: number): number | null {
  const hours = RANGES.find((r) => r.key === range)?.hours ?? null;
  return hours == null ? null : now - hours * 3_600_000;
}

export function inRange(points: GlucosePoint[], range: RangeKey, now: number): GlucosePoint[] {
  const start = rangeStart(range, now);
  if (start == null) return points;
  return points.filter((p) => p.t >= start && p.t <= now);
}

export function pad(n: number): string {
  return String(n).padStart(2, "0");
}

export function dayKey(d: Date | number): string {
  const date = typeof d === "number" ? new Date(d) : d;
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
}

export function dayStart(t: number): number {
  const d = new Date(t);
  d.setHours(0, 0, 0, 0);
  return d.getTime();
}

export function clockOf(t: number): string {
  const d = new Date(t);
  return `${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

export function timingLabel(minutes: number): string {
  if (minutes <= 0) return "餐前";
  if (minutes % 60 === 0) return `餐后 ${minutes / 60} 小时`;
  return `餐后 ${minutes} 分钟`;
}

export interface Summary {
  n: number;
  days: number;
  mean: number | null;
  sd: number | null;
  cv: number | null;
  min: GlucosePoint | null;
  max: GlucosePoint | null;
  lage: number | null;
  counts: Record<Zone, number>;
  pct: Record<Zone, number>;
  /** 平均每天读数条数，用来说明数据够不够密 */
  perDay: number | null;
}

export function summarize(points: GlucosePoint[], target: Target): Summary {
  const counts: Record<Zone, number> = { low2: 0, low: 0, ok: 0, high: 0, high2: 0 };
  for (const p of points) counts[zoneOf(p.value, target)] += 1;
  const n = points.length;
  const pct = Object.fromEntries(
    ZONE_ORDER.map((z) => [z, n ? (counts[z] / n) * 100 : 0]),
  ) as Record<Zone, number>;
  if (n === 0) {
    return {
      n: 0,
      days: 0,
      mean: null,
      sd: null,
      cv: null,
      min: null,
      max: null,
      lage: null,
      counts,
      pct,
      perDay: null,
    };
  }
  const mean = points.reduce((s, p) => s + p.value, 0) / n;
  const sd = n > 1 ? Math.sqrt(points.reduce((s, p) => s + (p.value - mean) ** 2, 0) / (n - 1)) : null;
  let min = points[0];
  let max = points[0];
  const dayset = new Set<string>();
  for (const p of points) {
    if (p.value < min.value) min = p;
    if (p.value > max.value) max = p;
    dayset.add(dayKey(p.t));
  }
  return {
    n,
    days: dayset.size,
    mean,
    sd,
    cv: sd != null && mean > 0 ? (sd / mean) * 100 : null,
    min,
    max,
    lage: n > 1 ? max.value - min.value : null,
    counts,
    pct,
    perDay: n / dayset.size,
  };
}

export interface Bucket {
  key: string;
  label: string;
  n: number;
  mean: number | null;
  max: number | null;
  okPct: number | null;
}

const BUCKETS: { key: string; label: string; test: (m: number) => boolean }[] = [
  { key: "pre", label: "餐前", test: (m) => m <= 0 },
  { key: "h1", label: "餐后 ≤1 小时", test: (m) => m > 0 && m <= 60 },
  { key: "h2", label: "1–2 小时", test: (m) => m > 60 && m <= 120 },
  { key: "h3", label: "2–3 小时", test: (m) => m > 120 && m <= 180 },
  { key: "later", label: "3 小时以上", test: (m) => m > 180 },
];

function aggregate(points: GlucosePoint[], target: Target) {
  if (points.length === 0) return { n: 0, mean: null, max: null, okPct: null };
  const mean = points.reduce((s, p) => s + p.value, 0) / points.length;
  const max = Math.max(...points.map((p) => p.value));
  const ok = points.filter((p) => zoneOf(p.value, target) === "ok").length;
  return { n: points.length, mean, max, okPct: (ok / points.length) * 100 };
}

export function postMealBuckets(points: GlucosePoint[], target: Target): Bucket[] {
  return BUCKETS.map((b) => ({
    key: b.key,
    label: b.label,
    ...aggregate(points.filter((p) => b.test(p.minutesAfter)), target),
  }));
}

export function byMealType(points: GlucosePoint[], target: Target): Bucket[] {
  return MEAL_TYPES.map((type) => ({
    key: type,
    label: type,
    ...aggregate(points.filter((p) => p.mealType === type), target),
  }));
}

export interface DayRow {
  key: string;
  start: number;
  label: string;
  carbs: number;
  mealCount: number;
  n: number;
  mean: number | null;
  min: number | null;
  max: number | null;
}

export function dailyRows(
  points: GlucosePoint[],
  meals: MealRecord[],
  start: number,
  end: number,
): DayRow[] {
  const rows: DayRow[] = [];
  const first = dayStart(start);
  const last = dayStart(end);
  for (let t = first; t <= last; t += 86_400_000) {
    const d = new Date(t);
    // 跨夏令时时一天不一定正好 86400000 毫秒，用日期重置保证不漂移
    d.setHours(0, 0, 0, 0);
    const key = dayKey(d);
    rows.push({
      key,
      start: d.getTime(),
      label: `${d.getMonth() + 1}/${d.getDate()}`,
      carbs: 0,
      mealCount: 0,
      n: 0,
      mean: null,
      min: null,
      max: null,
    });
    if (rows.length > 62) break;
  }
  const byKey = new Map(rows.map((r) => [r.key, r]));
  for (const meal of meals) {
    const row = byKey.get(meal.eaten_at.slice(0, 10));
    if (!row) continue;
    row.carbs += mealCarbs(meal) ?? 0;
    row.mealCount += 1;
  }
  const grouped = new Map<string, number[]>();
  for (const p of points) {
    const key = dayKey(p.t);
    const list = grouped.get(key) ?? [];
    list.push(p.value);
    grouped.set(key, list);
  }
  for (const row of rows) {
    const values = grouped.get(row.key);
    row.carbs = Math.round(row.carbs * 10) / 10;
    if (!values?.length) continue;
    row.n = values.length;
    row.mean = values.reduce((s, v) => s + v, 0) / values.length;
    row.min = Math.min(...values);
    row.max = Math.max(...values);
  }
  return rows;
}

export interface HourBin {
  hour: number;
  n: number;
  mean: number;
  min: number;
  max: number;
}

/** 多日按小时叠加，对应动态血糖报告里的「每日血糖图谱」 */
export function hourlyProfile(points: GlucosePoint[]): HourBin[] {
  const grouped = new Map<number, number[]>();
  for (const p of points) {
    const hour = new Date(p.t).getHours();
    const list = grouped.get(hour) ?? [];
    list.push(p.value);
    grouped.set(hour, list);
  }
  return [...grouped.entries()]
    .map(([hour, values]) => ({
      hour,
      n: values.length,
      mean: values.reduce((s, v) => s + v, 0) / values.length,
      min: Math.min(...values),
      max: Math.max(...values),
    }))
    .sort((a, b) => a.hour - b.hour);
}

export interface FoodRow {
  name: string;
  count: number;
  mean: number;
  max: number;
  carbs: number | null;
}

export function byFood(meals: MealRecord[], mealIds: Set<string>): FoodRow[] {
  const map = new Map<string, { values: number[]; carbs: number[] }>();
  for (const meal of meals) {
    if (!mealIds.has(meal.meal_id) || meal.readings.length === 0) continue;
    const values = meal.readings.map((r) => r.value_mmol);
    const carbs = mealCarbs(meal);
    for (const name of new Set(meal.foods.map((f) => f.name))) {
      const cur = map.get(name) ?? { values: [], carbs: [] };
      cur.values.push(...values);
      if (carbs != null) cur.carbs.push(carbs);
      map.set(name, cur);
    }
  }
  return [...map.entries()]
    .map(([name, v]) => ({
      name,
      count: v.values.length,
      mean: v.values.reduce((s, x) => s + x, 0) / v.values.length,
      max: Math.max(...v.values),
      carbs: v.carbs.length ? v.carbs.reduce((s, x) => s + x, 0) / v.carbs.length : null,
    }))
    .sort((a, b) => b.count - a.count || b.mean - a.mean)
    .slice(0, 8);
}

export function readingsCsv(points: GlucosePoint[], target: Target): string {
  const head = "测量时间(推算),日期,时刻,餐次,餐后分钟,血糖mmol/L,区间,碳水g,食物,备注";
  const escape = (v: string) => `"${v.replace(/"/g, '""')}"`;
  const lines = points.map((p) => {
    const d = new Date(p.t);
    return [
      `${dayKey(d)} ${clockOf(p.t)}`,
      dayKey(d),
      clockOf(p.t),
      p.mealType,
      String(p.minutesAfter),
      p.value.toFixed(1),
      ZONE_LABELS[zoneOf(p.value, target)],
      p.carbs == null ? "" : String(Math.round(p.carbs)),
      escape(p.foods),
      escape(p.note),
    ].join(",");
  });
  return `${head}\n${lines.join("\n")}\n`;
}