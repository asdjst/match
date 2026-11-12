/**
 * 健康趋势报告：时间范围 + 单日 24 小时 + 餐后时段 + 分布与波动。
 * 口径参照动态血糖（AGP）报告，但数据是手动点测，所以占比按「读数」算，不推算糖化。
 */
import { useEffect, useMemo, useRef, useState } from "react";
import { Banner, Button, EmptyState, Text } from "@astryxdesign/core";
import type { MealRecord, MealType } from "../types";
import { buildDemoMeals } from "../lib/demoMeals";
import {
  MEAL_TYPES,
  RANGES,
  TARGETS,
  ZONE_LABELS,
  ZONE_ORDER,
  byFood,
  byMealType,
  clockOf,
  dailyRows,
  dayKey,
  dayStart,
  hourlyProfile,
  inRange,
  postMealBuckets,
  rangeStart,
  readingsCsv,
  summarize,
  timingLabel,
  toPoints,
  zoneOf,
  type Bucket,
  type DayRow,
  type GlucosePoint,
  type HourBin,
  type RangeKey,
  type Summary,
  type Target,
  type TargetKey,
  type Zone,
} from "../lib/glucoseStats";

const TARGET_STORAGE = "glucoguard.target";
const W = 340;
const WEEKDAYS = ["周日", "周一", "周二", "周三", "周四", "周五", "周六"];
const MEAL_SLUG: Record<MealType, string> = {
  早餐: "breakfast",
  午餐: "lunch",
  晚餐: "dinner",
  加餐: "snack",
};

function loadTarget(): TargetKey {
  try {
    const raw = localStorage.getItem(TARGET_STORAGE);
    return TARGETS.some((t) => t.key === raw) ? (raw as TargetKey) : "standard";
  } catch {
    return "standard";
  }
}

function fmt(value: number | null, digits = 1): string {
  return value == null ? "—" : value.toFixed(digits);
}

function dayLabel(t: number): string {
  const d = new Date(t);
  return `${d.getMonth() + 1} 月 ${d.getDate()} 日 ${WEEKDAYS[d.getDay()]}`;
}

function download(name: string, text: string) {
  const url = URL.createObjectURL(new Blob([`﻿${text}`], { type: "text/csv;charset=utf-8" }));
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  a.click();
  URL.revokeObjectURL(url);
}

/* ——————————————————— 单日 / 区间曲线 ——————————————————— */

interface CurveProps {
  points: GlucosePoint[];
  meals: MealRecord[];
  start: number;
  end: number;
  target: Target;
  ticks: { t: number; label: string }[];
  showMeals: boolean;
  selected: string | null;
  onSelect: (id: string | null) => void;
  emptyHint: string;
}

function GlucoseCurve({
  points,
  meals,
  start,
  end,
  target,
  ticks,
  showMeals,
  selected,
  onSelect,
  emptyHint,
}: CurveProps) {
  const H = 172;
  const box = { l: 28, r: 12, t: 14, b: showMeals ? 34 : 24 };
  const plotW = W - box.l - box.r;
  const plotH = H - box.t - box.b;
  const values = points.map((p) => p.value);
  const yMin = Math.min(3, Math.floor(Math.min(...values, target.low) - 0.4));
  const yMax = Math.max(target.high + 4, Math.ceil(Math.max(...values, target.high) + 0.6));
  const x = (t: number) => box.l + ((t - start) / (end - start)) * plotW;
  const y = (v: number) => box.t + ((yMax - v) / (yMax - yMin)) * plotH;
  const gridValues = [target.low, target.high, target.high + 3.9].filter(
    (v) => v > yMin && v < yMax,
  );

  // 只连相邻 3 小时内的读数：跨餐、跨夜的空白不补线
  const segments: GlucosePoint[][] = [];
  for (const p of points) {
    const last = segments[segments.length - 1];
    if (last && p.t - last[last.length - 1].t <= 180 * 60_000) last.push(p);
    else segments.push([p]);
  }

  const marks = showMeals
    ? meals
        .map((m) => ({ meal: m, t: Date.parse(m.eaten_at) }))
        .filter((m) => m.t >= start && m.t <= end)
    : [];

  return (
    <figure className="stat-fig">
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label="血糖曲线，含目标区间阴影">
        <rect
          x={box.l}
          y={y(target.high)}
          width={plotW}
          height={Math.max(0, y(target.low) - y(target.high))}
          className="stat-band"
        />
        {gridValues.map((v) => (
          <g key={v}>
            <line x1={box.l} x2={W - box.r} y1={y(v)} y2={y(v)} className="stat-grid" />
            <text x={box.l - 5} y={y(v) + 3} textAnchor="end" className="stat-axis">
              {v.toFixed(1)}
            </text>
          </g>
        ))}
        <line x1={box.l} x2={W - box.r} y1={box.t + plotH} y2={box.t + plotH} className="stat-base" />
        {ticks.map((tick) => (
          <text
            key={tick.t}
            x={x(tick.t)}
            y={box.t + plotH + 12}
            textAnchor="middle"
            className="stat-axis"
          >
            {tick.label}
          </text>
        ))}
        {segments.map((seg) =>
          seg.length > 1 ? (
            <polyline
              key={seg[0].id}
              points={seg.map((p) => `${x(p.t)},${y(p.value)}`).join(" ")}
              className="stat-line"
              fill="none"
            />
          ) : null,
        )}
        {points.map((p) => {
          const zone = zoneOf(p.value, target);
          const isOn = selected === p.id;
          return (
            <circle
              key={p.id}
              cx={x(p.t)}
              cy={y(p.value)}
              r={isOn ? 5 : 3.4}
              className={`stat-dot z-${zone}${isOn ? " is-on" : ""}`}
              tabIndex={0}
              role="button"
              aria-label={`${clockOf(p.t)} ${p.mealType} ${timingLabel(p.minutesAfter)} ${p.value} mmol/L`}
              onClick={() => onSelect(isOn ? null : p.id)}
              onKeyDown={(e) => {
                if (e.key !== "Enter" && e.key !== " ") return;
                e.preventDefault();
                onSelect(isOn ? null : p.id);
              }}
            >
              <title>{`${clockOf(p.t)} · ${p.mealType} · ${timingLabel(p.minutesAfter)} · ${p.value} mmol/L · ${ZONE_LABELS[zone]}\n${p.foods}`}</title>
            </circle>
          );
        })}
        {marks.map(({ meal, t }) => (
          <g key={meal.meal_id}>
            <line
              x1={x(t)}
              x2={x(t)}
              y1={box.t + plotH}
              y2={box.t + plotH + 4}
              className="stat-meal-tick"
            />
            <text x={x(t)} y={H - 3} textAnchor="middle" className={`stat-meal m-${MEAL_SLUG[meal.meal_type]}`}>
              {meal.meal_type[0]}
              <title>{`${clockOf(t)} ${meal.meal_type} · ${meal.foods.map((f) => f.name).join("、")}`}</title>
            </text>
          </g>
        ))}
        {points.length === 0 ? (
          <text x={W / 2} y={box.t + plotH / 2} textAnchor="middle" className="stat-empty-text">
            {emptyHint}
          </text>
        ) : null}
      </svg>
    </figure>
  );
}

/* ——————————————————— 多日按小时叠加 ——————————————————— */

function HourlyProfile({ bins, target }: { bins: HourBin[]; target: Target }) {
  const H = 150;
  const box = { l: 28, r: 12, t: 12, b: 22 };
  const plotW = W - box.l - box.r;
  const plotH = H - box.t - box.b;
  const yMin = Math.min(3, Math.floor(Math.min(...bins.map((b) => b.min), target.low) - 0.4));
  const yMax = Math.max(target.high + 4, Math.ceil(Math.max(...bins.map((b) => b.max)) + 0.6));
  const x = (hour: number) => box.l + (hour / 23) * plotW;
  const y = (v: number) => box.t + ((yMax - v) / (yMax - yMin)) * plotH;
  const gridValues = [target.low, target.high, target.high + 3.9].filter((v) => v > yMin && v < yMax);

  return (
    <figure className="stat-fig">
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label="多日按小时叠加的平均血糖与最低最高范围">
        <rect
          x={box.l}
          y={y(target.high)}
          width={plotW}
          height={Math.max(0, y(target.low) - y(target.high))}
          className="stat-band"
        />
        {gridValues.map((v) => (
          <g key={v}>
            <line x1={box.l} x2={W - box.r} y1={y(v)} y2={y(v)} className="stat-grid" />
            <text x={box.l - 5} y={y(v) + 3} textAnchor="end" className="stat-axis">
              {v.toFixed(1)}
            </text>
          </g>
        ))}
        {[0, 3, 6, 9, 12, 15, 18, 21].map((h) => (
          <text key={h} x={x(h)} y={H - 6} textAnchor="middle" className="stat-axis">
            {h}
          </text>
        ))}
        {bins.map((b) => (
          <rect
            key={b.hour}
            x={x(b.hour) - 4}
            y={y(b.max)}
            width={8}
            height={Math.max(2, y(b.min) - y(b.max))}
            rx={4}
            className="stat-whisker"
          >
            <title>{`${b.hour}:00–${b.hour}:59 · ${b.n} 条 · 平均 ${b.mean.toFixed(1)} · ${b.min.toFixed(1)}–${b.max.toFixed(1)}`}</title>
          </rect>
        ))}
        <polyline
          points={bins.map((b) => `${x(b.hour)},${y(b.mean)}`).join(" ")}
          className="stat-line"
          fill="none"
        />
        {bins.map((b) => (
          <circle key={b.hour} cx={x(b.hour)} cy={y(b.mean)} r={2.6} className="stat-dot z-ok is-solid" />
        ))}
      </svg>
    </figure>
  );
}

/* ——————————————————— 每日碳水 + 平均血糖 ——————————————————— */

function DailyChart({ rows, target }: { rows: DayRow[]; target: Target }) {
  const H = 176;
  const box = { l: 26, r: 26, t: 16, b: 24 };
  const plotW = W - box.l - box.r;
  const plotH = H - box.t - box.b;
  const carbMax = Math.max(60, Math.ceil(Math.max(...rows.map((r) => r.carbs), 0) / 30) * 30);
  const gMax = Math.max(target.high + 4, Math.ceil(Math.max(...rows.map((r) => r.max ?? 0)) + 1));
  const gMin = 3;
  const slot = plotW / rows.length;
  const barW = Math.max(3, Math.min(16, slot * 0.5));
  const yC = (v: number) => box.t + (1 - v / carbMax) * plotH;
  const yG = (v: number) => box.t + ((gMax - v) / (gMax - gMin)) * plotH;
  const labelEvery = Math.ceil(rows.length / 7);
  const withGlucose = rows.filter((r) => r.mean != null);

  return (
    <figure className="stat-fig">
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label="每日碳水合计柱状与当日平均血糖折线">
        <rect
          x={box.l}
          y={yG(target.high)}
          width={plotW}
          height={Math.max(0, yG(target.low) - yG(target.high))}
          className="stat-band"
        />
        {[0, carbMax / 2, carbMax].map((v) => (
          <g key={v}>
            <line x1={box.l} x2={W - box.r} y1={yC(v)} y2={yC(v)} className="stat-grid" />
            <text x={box.l - 5} y={yC(v) + 3} textAnchor="end" className="stat-axis">
              {Math.round(v)}
            </text>
          </g>
        ))}
        {[gMax, target.high, gMin].map((v) => (
          <text key={v} x={W - box.r + 5} y={yG(v) + 3} className="stat-axis stat-axis--g">
            {v.toFixed(0)}
          </text>
        ))}
        {rows.map((row, i) => {
          const cx = box.l + slot * i + slot / 2;
          const top = yC(row.carbs);
          return (
            <g key={row.key}>
              <rect
                x={cx - barW / 2}
                y={top}
                width={barW}
                height={Math.max(0, box.t + plotH - top)}
                rx={2}
                className="stat-carb-bar"
              >
                <title>{`${row.label} · 碳水 ${row.carbs}g（${row.mealCount} 餐）${row.mean == null ? " · 无血糖读数" : ` · 平均血糖 ${row.mean.toFixed(1)}`}`}</title>
              </rect>
              {i % labelEvery === 0 ? (
                <text x={cx} y={H - 7} textAnchor="middle" className="stat-axis">
                  {row.label}
                </text>
              ) : null}
            </g>
          );
        })}
        {withGlucose.length > 1 ? (
          <polyline
            points={withGlucose
              .map((r) => `${box.l + slot * rows.indexOf(r) + slot / 2},${yG(r.mean as number)}`)
              .join(" ")}
            className="stat-line stat-line--mean"
            fill="none"
          />
        ) : null}
        {withGlucose.map((r) => (
          <circle
            key={r.key}
            cx={box.l + slot * rows.indexOf(r) + slot / 2}
            cy={yG(r.mean as number)}
            r={3}
            className={`stat-dot z-${zoneOf(r.mean as number, target)} is-solid`}
          >
            <title>{`${r.label} 平均 ${r.mean?.toFixed(1)} · ${r.n} 条 · ${r.min?.toFixed(1)}–${r.max?.toFixed(1)}`}</title>
          </circle>
        ))}
      </svg>
      <figcaption className="stat-legend">
        <span className="stat-key">
          <i className="sw sw-carb" />
          碳水 g（左轴）
        </span>
        <span className="stat-key">
          <i className="sw sw-line" />
          当日平均血糖（右轴）
        </span>
      </figcaption>
    </figure>
  );
}

/* ——————————————————— 碳水 × 餐后血糖散点 ——————————————————— */

function CarbScatter({ points, target }: { points: GlucosePoint[]; target: Target }) {
  const usable = points.filter((p) => p.carbs != null && p.minutesAfter > 0);
  if (usable.length < 3) {
    return <p className="chart-empty">餐后读数配上碳水的记录满 3 条，这里才画散点。</p>;
  }
  const H = 168;
  const box = { l: 28, r: 12, t: 12, b: 28 };
  const plotW = W - box.l - box.r;
  const plotH = H - box.t - box.b;
  const xMax = Math.max(60, Math.ceil(Math.max(...usable.map((p) => p.carbs as number)) / 20) * 20);
  const yMin = Math.min(3, Math.floor(Math.min(...usable.map((p) => p.value)) - 0.4));
  const yMax = Math.max(target.high + 4, Math.ceil(Math.max(...usable.map((p) => p.value)) + 0.6));
  const x = (v: number) => box.l + (v / xMax) * plotW;
  const y = (v: number) => box.t + ((yMax - v) / (yMax - yMin)) * plotH;

  return (
    <figure className="stat-fig">
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label="同一餐碳水与该餐餐后血糖的散点">
        <rect
          x={box.l}
          y={y(target.high)}
          width={plotW}
          height={Math.max(0, y(target.low) - y(target.high))}
          className="stat-band"
        />
        {[target.low, target.high].map((v) => (
          <g key={v}>
            <line x1={box.l} x2={W - box.r} y1={y(v)} y2={y(v)} className="stat-grid" />
            <text x={box.l - 5} y={y(v) + 3} textAnchor="end" className="stat-axis">
              {v.toFixed(1)}
            </text>
          </g>
        ))}
        {[0, xMax / 2, xMax].map((v) => (
          <text key={v} x={x(v)} y={H - 12} textAnchor="middle" className="stat-axis">
            {Math.round(v)}
          </text>
        ))}
        <text x={W - box.r} y={H - 1} textAnchor="end" className="stat-axis">
          该餐碳水 g
        </text>
        {usable.map((p) => (
          <circle
            key={p.id}
            cx={x(p.carbs as number)}
            cy={y(p.value)}
            r={3.6}
            className={`stat-scatter m-${MEAL_SLUG[p.mealType]}`}
          >
            <title>{`${p.mealType} · 碳水 ${Math.round(p.carbs as number)}g · ${timingLabel(p.minutesAfter)} ${p.value} mmol/L\n${p.foods}`}</title>
          </circle>
        ))}
      </svg>
      <figcaption className="stat-legend">
        {MEAL_TYPES.map((type) => (
          <span className="stat-key" key={type}>
            <i className={`sw m-${MEAL_SLUG[type]}`} />
            {type}
          </span>
        ))}
      </figcaption>
    </figure>
  );
}

/* ——————————————————— 分布与分时段 ——————————————————— */

function Distribution({ summary, target }: { summary: Summary; target: Target }) {
  const goals: Record<Zone, string> = {
    low2: "< 1%",
    low: "< 4%",
    ok: "> 70%",
    high: "< 25%",
    high2: "< 5%",
  };
  return (
    <div className="stat-dist">
      <div className="stat-dist-bar" role="img" aria-label="各区间读数占比">
        {ZONE_ORDER.map((zone) =>
          summary.pct[zone] > 0 ? (
            <span
              key={zone}
              className={`stat-seg z-${zone}`}
              style={{ flexGrow: summary.pct[zone] }}
              title={`${ZONE_LABELS[zone]} ${summary.counts[zone]} 条 · ${summary.pct[zone].toFixed(0)}%`}
            >
              {summary.pct[zone] >= 12 ? `${summary.pct[zone].toFixed(0)}%` : ""}
            </span>
          ) : null,
        )}
      </div>
      <ul className="stat-dist-legend">
        {ZONE_ORDER.map((zone) => (
          <li key={zone}>
            <i className={`sw z-${zone}`} />
            <span className="stat-dist-name">{ZONE_LABELS[zone]}</span>
            <span className="stat-dist-num">{summary.counts[zone]} 条</span>
            <span className="stat-dist-pct">{summary.pct[zone].toFixed(0)}%</span>
            <span className="stat-dist-goal">参考 {goals[zone]}</span>
          </li>
        ))}
      </ul>
      <Text size="2xs" color="secondary">
        区间按目标 {target.low.toFixed(1)}–{target.high.toFixed(1)} mmol/L 划分。这里是读数占比，不是动态血糖的时间占比。
      </Text>
    </div>
  );
}

function BucketRows({ rows, target }: { rows: Bucket[]; target: Target }) {
  const scaleMax = Math.max(target.high + 4, ...rows.map((r) => r.max ?? 0));
  const live = rows.filter((r) => r.n > 0);
  if (live.length === 0) return <p className="chart-empty">这个范围里还没有血糖读数。</p>;
  return (
    <ul className="stat-buckets">
      {rows.map((row) => (
        <li key={row.key} className={row.n === 0 ? "is-void" : ""}>
          <span className="stat-bucket-label">{row.label}</span>
          <span className="stat-bucket-track">
            {row.n > 0 ? (
              <>
                <i
                  className="stat-bucket-band"
                  style={{ left: `${(target.low / scaleMax) * 100}%`, width: `${((target.high - target.low) / scaleMax) * 100}%` }}
                />
                <i
                  className={`stat-bucket-fill z-${zoneOf(row.mean as number, target)}`}
                  style={{ width: `${((row.mean as number) / scaleMax) * 100}%` }}
                />
                <i className="stat-bucket-peak" style={{ left: `${((row.max as number) / scaleMax) * 100}%` }} />
              </>
            ) : null}
          </span>
          <span className="stat-bucket-value">
            {row.n === 0 ? "无记录" : `${fmt(row.mean)} · 峰 ${fmt(row.max)}`}
          </span>
          <span className="stat-bucket-meta">
            {row.n === 0 ? "—" : `${row.n} 条 · 达标 ${(row.okPct as number).toFixed(0)}%`}
          </span>
        </li>
      ))}
    </ul>
  );
}

/* ——————————————————— 主组件 ——————————————————— */

export default function HealthTrends({ meals }: { meals: MealRecord[] }) {
  const [range, setRange] = useState<RangeKey>("24h");
  const [targetKey, setTargetKey] = useState<TargetKey>(loadTarget);
  const [demo, setDemo] = useState(false);
  const [mode, setMode] = useState<"day" | "span">("day");
  const [anchor, setAnchor] = useState<number | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const rangeTouched = useRef(false);

  // 记录很稀疏，默认 24 小时可能一条都没有：首次拿到数据时退到最近有读数的范围
  useEffect(() => {
    if (rangeTouched.current || meals.length === 0) return;
    const points = toPoints(meals);
    if (points.length === 0) return;
    const at = Date.now();
    const fit = RANGES.filter((r) => r.hours == null || r.hours >= 24).find((r) => {
      const hours = r.hours;
      return hours == null || points.some((p) => p.t >= at - hours * 3_600_000);
    });
    rangeTouched.current = true;
    if (fit && fit.key !== range) setRange(fit.key);
  }, [meals, range]);

  useEffect(() => {
    try {
      localStorage.setItem(TARGET_STORAGE, targetKey);
    } catch {
      // 隐私模式下写入失败不影响本次选择
    }
  }, [targetKey]);

  const now = useMemo(() => Date.now(), [meals, demo, range]);
  const target = useMemo(() => {
    const preset = TARGETS.find((t) => t.key === targetKey) ?? TARGETS[0];
    return { low: preset.low, high: preset.high };
  }, [targetKey]);

  const demoMeals = useMemo(() => (demo ? buildDemoMeals(now) : []), [demo, now]);
  const source = demo ? demoMeals : meals;
  const allPoints = useMemo(() => toPoints(source), [source]);
  const points = useMemo(() => inRange(allPoints, range, now), [allPoints, range, now]);
  const summary = useMemo(() => summarize(points, target), [points, target]);
  const buckets = useMemo(
    () => postMealBuckets(points, target).filter((b) => b.key !== "later" || b.n > 0),
    [points, target],
  );
  const mealTypes = useMemo(() => byMealType(points, target), [points, target]);
  const mealIds = useMemo(() => new Set(points.map((p) => p.mealId)), [points]);
  const foods = useMemo(() => byFood(source, mealIds), [source, mealIds]);

  const earliest = allPoints.length ? dayStart(allPoints[0].t) : dayStart(now);
  const latest = allPoints.length ? dayStart(allPoints[allPoints.length - 1].t) : dayStart(now);
  const day = Math.min(Math.max(anchor ?? latest, earliest), dayStart(now));
  const dayEnd = day + 86_400_000;
  const dayPoints = useMemo(
    () => allPoints.filter((p) => p.t >= day && p.t < dayEnd),
    [allPoints, day, dayEnd],
  );
  const daySummary = useMemo(() => summarize(dayPoints, target), [dayPoints, target]);

  const spanStart = rangeStart(range, now) ?? (allPoints.length ? allPoints[0].t : now - 86_400_000);
  const spanEnd = range === "all" && allPoints.length ? allPoints[allPoints.length - 1].t + 3_600_000 : now;
  const span = Math.max(spanEnd - spanStart, 3_600_000);
  const spanPoints = range === "all" ? allPoints : points;

  const dayTicks = useMemo(
    () => Array.from({ length: 9 }, (_, i) => ({ t: day + i * 3 * 3_600_000, label: String(i * 3) })),
    [day],
  );
  const spanTicks = useMemo(() => {
    const out: { t: number; label: string }[] = [];
    if (span <= 36 * 3_600_000) {
      const step = (span <= 12 * 3_600_000 ? 2 : 4) * 3_600_000;
      const first = Math.ceil(spanStart / step) * step;
      for (let t = first; t <= spanEnd; t += step) {
        out.push({ t, label: `${new Date(t).getHours()}时` });
      }
      return out;
    }
    const days = Math.max(1, Math.round(span / 86_400_000));
    const every = Math.max(1, Math.ceil(days / 6));
    for (let i = 0; i < days; i += every) {
      const t = dayStart(spanStart) + i * 86_400_000 + 12 * 3_600_000;
      if (t > spanEnd) break;
      const d = new Date(t);
      out.push({ t, label: `${d.getMonth() + 1}/${d.getDate()}` });
    }
    return out;
  }, [span, spanStart, spanEnd]);

  const earliestMeal = useMemo(() => {
    const times = source.map((m) => Date.parse(m.eaten_at)).filter((t) => !Number.isNaN(t));
    return times.length ? dayStart(Math.min(...times)) : dayStart(now);
  }, [source, now]);
  const dailyStart = rangeStart(range, now) ?? earliestMeal;
  const rows = useMemo(
    () => dailyRows(points, source, Math.max(dailyStart, now - 31 * 86_400_000), now),
    [points, source, dailyStart, now],
  );
  const bins = useMemo(() => hourlyProfile(points), [points]);
  const selectedPoint = useMemo(
    () => allPoints.find((p) => p.id === selected) ?? null,
    [allPoints, selected],
  );

  const rangeLabel = RANGES.find((r) => r.key === range)?.label ?? "";
  const rangeCaption = range === "all" ? "全部记录" : `近 ${rangeLabel}`;
  const multiDay = summary.days >= 2;
  const cvLevel = summary.cv == null ? "" : summary.cv < 36 ? "is-ok" : "is-warn";
  const tirLevel = summary.n === 0 ? "" : summary.pct.ok >= 70 ? "is-ok" : "is-warn";

  return (
    <div className={`stat-report${demo ? " is-demo" : ""}`}>
      <div className="stat-controls">
        <div className="stat-chips" role="group" aria-label="统计时间范围">
          {RANGES.map((r) => (
            <button
              key={r.key}
              type="button"
              className={`stat-chip${range === r.key ? " is-active" : ""}`}
              aria-pressed={range === r.key}
              onClick={() => {
                rangeTouched.current = true;
                setRange(r.key);
                setSelected(null);
                if (r.hours != null && r.hours <= 24) setMode("span");
                else setMode("day");
              }}
            >
              {r.label}
            </button>
          ))}
        </div>
        <div className="stat-control-row">
          <label className="stat-target">
            <span>目标区间</span>
            <select value={targetKey} onChange={(e) => setTargetKey(e.target.value as TargetKey)}>
              {TARGETS.map((t) => (
                <option key={t.key} value={t.key}>
                  {t.label}
                </option>
              ))}
            </select>
          </label>
          <button
            type="button"
            className={`stat-toggle${demo ? " is-active" : ""}`}
            aria-pressed={demo}
            onClick={() => {
              setDemo(!demo);
              setSelected(null);
              setAnchor(null);
            }}
          >
            示例数据
          </button>
          <button
            type="button"
            className="stat-toggle"
            disabled={points.length === 0}
            onClick={() => download(`血糖记录-${rangeLabel}-${dayKey(now)}.csv`, readingsCsv(points, target))}
          >
            导出 CSV
          </button>
        </div>
      </div>

      {demo ? (
        <Banner
          status="warning"
          title="正在看示例数据"
          description="14 天模拟记录，只用于展示统计口径，不写入健康档案，也不参与问答记忆。再点一次「示例数据」回到自己的记录。"
        />
      ) : null}

      {summary.n === 0 ? (
        <div className="stat-empty">
          <EmptyState
            title={`${rangeCaption}没有血糖读数`}
            description="在上面的餐食记录里给某一餐补一个餐前或餐后血糖，这里就会出报告；也可以先用示例数据看看完整口径。"
            actions={
              <Button label="看示例报告" variant="secondary" size="sm" onClick={() => setDemo(true)} />
            }
          />
        </div>
      ) : (
        <>
          <section className="stat-block">
            <div className="stat-overview">
              <div className="stat-hero">
                <span className="stat-hero-label">平均血糖</span>
                <strong className="stat-hero-value">{fmt(summary.mean)}</strong>
                <span className="stat-hero-unit">mmol/L</span>
                <span className="stat-hero-note">参考 &lt; 8.5 · {rangeCaption}</span>
              </div>
              <div className="stat-tiles">
                <div className={`stat-tile ${tirLevel}`}>
                  <span>达标读数占比</span>
                  <strong>{summary.pct.ok.toFixed(0)}%</strong>
                  <small>参考 &gt; 70%</small>
                </div>
                <div className={`stat-tile ${cvLevel}`}>
                  <span>波动系数 CV</span>
                  <strong>{summary.cv == null ? "—" : `${summary.cv.toFixed(0)}%`}</strong>
                  <small>参考 &lt; 36%</small>
                </div>
                <div className="stat-tile">
                  <span>读数条数</span>
                  <strong>{summary.n}</strong>
                  <small>覆盖 {summary.days} 天 · 日均 {fmt(summary.perDay)} 条</small>
                </div>
                <div className="stat-tile">
                  <span>区间极差</span>
                  <strong>{fmt(summary.lage)}</strong>
                  <small>最高 {fmt(summary.max?.value ?? null)} · 最低 {fmt(summary.min?.value ?? null)}</small>
                </div>
              </div>
            </div>
            {summary.max && summary.min ? (
              <p className="stat-extremes">
                最高 {summary.max.value.toFixed(1)}（{dayKey(summary.max.t).slice(5)} {clockOf(summary.max.t)} ·{" "}
                {summary.max.mealType} {timingLabel(summary.max.minutesAfter)}） · 最低{" "}
                {summary.min.value.toFixed(1)}（{dayKey(summary.min.t).slice(5)} {clockOf(summary.min.t)} ·{" "}
                {summary.min.mealType} {timingLabel(summary.min.minutesAfter)}）
              </p>
            ) : null}
          </section>

          <section className="stat-block">
            <div className="stat-head">
              <strong>读数分布</strong>
              <span>{rangeCaption} · {summary.n} 条</span>
            </div>
            <Distribution summary={summary} target={target} />
          </section>
        </>
      )}

      <section className="stat-block">
        <div className="stat-head">
          <strong>血糖曲线</strong>
          <div className="stat-modes" role="group" aria-label="曲线视图">
            <button
              type="button"
              className={mode === "day" ? "is-active" : ""}
              aria-pressed={mode === "day"}
              onClick={() => setMode("day")}
            >
              单日 24 小时
            </button>
            <button
              type="button"
              className={mode === "span" ? "is-active" : ""}
              aria-pressed={mode === "span"}
              onClick={() => setMode("span")}
            >
              区间
            </button>
          </div>
        </div>

        {mode === "day" ? (
          <div className="stat-stepper">
            <button
              type="button"
              aria-label="前一天"
              disabled={day <= earliest}
              onClick={() => setAnchor(day - 86_400_000)}
            >
              ‹
            </button>
            <span>
              {dayLabel(day)}
              {day === dayStart(now) ? " · 今天" : ""}
            </span>
            <button
              type="button"
              aria-label="后一天"
              disabled={day >= dayStart(now)}
              onClick={() => setAnchor(day + 86_400_000)}
            >
              ›
            </button>
            <em>
              {daySummary.n} 条 · 平均 {fmt(daySummary.mean)} · 达标 {daySummary.pct.ok.toFixed(0)}%
            </em>
          </div>
        ) : (
          <div className="stat-stepper is-span">
            <span>
              {rangeCaption} · {spanPoints.length} 条读数
            </span>
            <em>横轴为真实时刻，只连相邻 3 小时内的点</em>
          </div>
        )}

        <GlucoseCurve
          points={mode === "day" ? dayPoints : spanPoints}
          meals={source}
          start={mode === "day" ? day : spanStart}
          end={mode === "day" ? dayEnd : spanEnd}
          target={target}
          ticks={mode === "day" ? dayTicks : spanTicks}
          showMeals={mode === "day" || span <= 36 * 3_600_000}
          selected={selected}
          onSelect={setSelected}
          emptyHint={mode === "day" ? "这一天没有血糖读数" : "这个范围没有血糖读数"}
        />

        <div className="stat-legend stat-legend--zones">
          {ZONE_ORDER.map((zone) => (
            <span className="stat-key" key={zone}>
              <i className={`sw z-${zone}`} />
              {ZONE_LABELS[zone]}
            </span>
          ))}
          <span className="stat-key">
            <i className="sw sw-band" />
            目标区间
          </span>
        </div>

        {selectedPoint ? (
          <div className={`stat-detail z-${zoneOf(selectedPoint.value, target)}`}>
            <div>
              <strong>{selectedPoint.value.toFixed(1)}</strong>
              <span>mmol/L · {ZONE_LABELS[zoneOf(selectedPoint.value, target)]}</span>
            </div>
            <p>
              {dayKey(selectedPoint.t)} {clockOf(selectedPoint.t)} · {selectedPoint.mealType} ·{" "}
              {timingLabel(selectedPoint.minutesAfter)}
              {selectedPoint.carbs != null ? ` · 该餐碳水约 ${Math.round(selectedPoint.carbs)}g` : ""}
            </p>
            <p className="stat-detail-foods">{selectedPoint.foods}</p>
            <button type="button" onClick={() => setSelected(null)} aria-label="取消选中">
              收起
            </button>
          </div>
        ) : (
          <p className="stat-hint">点曲线上的圆点看这一针对应的餐食；下方 早/午/晚/加 是就餐时刻。</p>
        )}
      </section>

      {multiDay ? (
        <section className="stat-block">
          <div className="stat-head">
            <strong>多日同时段叠加</strong>
            <span>{summary.days} 天 · 按小时</span>
          </div>
          {bins.length >= 2 ? (
            <>
              <HourlyProfile bins={bins} target={target} />
              <p className="stat-hint">
                竖条是该小时所有读数的最低–最高，折线是平均。看哪个时段反复偏高，比单看某一天更稳。
              </p>
            </>
          ) : (
            <p className="chart-empty">读数集中在同一小时，换一个更大的范围再看。</p>
          )}
        </section>
      ) : null}

      <div className="stat-cols">
        <section className="stat-block">
          <div className="stat-head">
            <strong>餐后时段</strong>
            <span>{rangeCaption}</span>
          </div>
          <BucketRows rows={buckets} target={target} />
        </section>

        <section className="stat-block">
          <div className="stat-head">
            <strong>按餐次</strong>
            <span>{rangeCaption}</span>
          </div>
          <BucketRows rows={mealTypes} target={target} />
        </section>
      </div>

      <section className="stat-block">
        <div className="stat-head">
          <strong>每日碳水与平均血糖</strong>
          <span>最多 31 天</span>
        </div>
        {rows.some((r) => r.carbs > 0 || r.n > 0) ? (
          <DailyChart rows={rows} target={target} />
        ) : (
          <p className="chart-empty">这个范围里还没有餐食记录。</p>
        )}
      </section>

      <div className="stat-cols">
        <section className="stat-block">
          <div className="stat-head">
            <strong>碳水 × 餐后血糖</strong>
            <span>{points.filter((p) => p.carbs != null && p.minutesAfter > 0).length} 个点</span>
          </div>
          <CarbScatter points={points} target={target} />
          <p className="stat-hint">同一餐的碳水量和餐后读数配对，只是分布，不代表因果，也不做拟合预测。</p>
        </section>

        <section className="stat-block">
          <div className="stat-head">
            <strong>按食物看记录</strong>
            <span>最多 8 项</span>
          </div>
          {foods.length === 0 ? (
            <p className="chart-empty">这个范围里的餐食还没有配血糖读数。</p>
          ) : (
            <ul className="stat-foods">
              {foods.map((row) => (
                <li key={row.name}>
                  <strong>{row.name}</strong>
                  <span>{row.count} 条读数</span>
                  <span>平均 {row.mean.toFixed(1)}</span>
                  <span>最高 {row.max.toFixed(1)}</span>
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>

      <p className="stat-foot">
        口径说明：读数时刻按「就餐时间 + 餐后时长」推算；占比按读数条数计算，不是动态血糖的时间占比。
        手动点测无法估算糖化血红蛋白（GMI 需要连续 14 天、有效率 70% 以上的动态血糖数据），因此这里不给该指标。
        所有数字只描述已记录的数据，不补点、不预测，也不构成用药建议。
      </p>
    </div>
  );
}