/**
 * 个人餐食 / 血糖图表：档案页和回答里的统计共用一套自绘 SVG。
 * 只画个人记录，不补点、不预测。
 */
import { useMemo } from "react";
import { EmptyState } from "@astryxdesign/core";
import type { MealRecord } from "../types";

const W = 680;
const WEEKDAYS = ["日", "一", "二", "三", "四", "五", "六"];

function pad(n: number): string {
  return String(n).padStart(2, "0");
}

function dayKey(d: Date): string {
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

function mealCarbs(meal: MealRecord): number {
  if (typeof meal.carbs_g === "number") return meal.carbs_g;
  return meal.foods.reduce((sum, food) => sum + (food.carbs_g ?? 0), 0);
}

function foodsText(meal: MealRecord): string {
  return meal.foods.map((f) => `${f.name} ${Math.round(f.grams)}g`).join("、");
}

function glucoseTiming(minutes: number): string {
  if (minutes <= 0) return "餐前";
  if (minutes % 60 === 0) return `餐后 ${minutes / 60} 小时`;
  return `餐后 ${minutes} 分钟`;
}

/** 近 N 天每日碳水合计（柱状） */
export function DailyCarbsChart({ meals, days = 7 }: { meals: MealRecord[]; days?: number }) {
  const data = useMemo(() => {
    const today = new Date();
    today.setHours(0, 0, 0, 0);
    const slots = Array.from({ length: days }, (_, i) => {
      const d = new Date(today);
      d.setDate(d.getDate() - (days - 1 - i));
      return {
        key: dayKey(d),
        label: `${d.getMonth() + 1}/${d.getDate()}`,
        weekday: `周${WEEKDAYS[d.getDay()]}`,
        isToday: i === days - 1,
        carbs: 0,
        count: 0,
      };
    });
    const byDay = new Map(slots.map((slot) => [slot.key, slot]));
    for (const meal of meals) {
      const slot = byDay.get(meal.eaten_at.slice(0, 10));
      if (!slot) continue;
      slot.carbs += mealCarbs(meal);
      slot.count += 1;
    }
    return slots.map((slot) => ({ ...slot, carbs: Math.round(slot.carbs * 10) / 10 }));
  }, [meals, days]);

  const H = 176;
  const padBox = { l: 34, r: 10, t: 20, b: 30 };
  const values = data.map((d) => d.carbs);
  const yMax = Math.max(60, Math.ceil(Math.max(...values, 0) / 20) * 20);
  const plotW = W - padBox.l - padBox.r;
  const plotH = H - padBox.t - padBox.b;
  const slotW = plotW / data.length;
  const barW = Math.min(34, slotW * 0.46);
  const y = (v: number) => padBox.t + (1 - v / yMax) * plotH;
  const grid = [0, yMax / 2, yMax];

  if (values.every((v) => v === 0)) {
    return <p className="chart-empty">最近 {days} 天还没有带碳水的餐食记录。</p>;
  }

  return (
    <div className="bar-chart">
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`最近 ${days} 天每日碳水合计`}>
        {grid.map((v) => (
          <g key={v}>
            <line x1={padBox.l} x2={W - padBox.r} y1={y(v)} y2={y(v)} className="trend-grid" />
            <text x={padBox.l - 8} y={y(v) + 3} textAnchor="end" className="trend-axis">
              {Math.round(v)}
            </text>
          </g>
        ))}
        {data.map((slot, i) => {
          const x = padBox.l + slotW * i + (slotW - barW) / 2;
          const top = y(slot.carbs);
          return (
            <g key={slot.key}>
              <rect
                x={x}
                y={top}
                width={barW}
                height={Math.max(0, padBox.t + plotH - top)}
                rx={3}
                className={`bar-rect${slot.isToday ? " is-today" : ""}`}
              >
                <title>
                  {slot.label} {slot.weekday} · 碳水 {slot.carbs}g（{slot.count} 餐）
                </title>
              </rect>
              {slot.carbs > 0 ? (
                <text x={x + barW / 2} y={top - 5} textAnchor="middle" className="bar-value">
                  {slot.carbs}
                </text>
              ) : null}
              <text x={x + barW / 2} y={H - 8} textAnchor="middle" className="trend-axis">
                {slot.label}
              </text>
            </g>
          );
        })}
      </svg>
    </div>
  );
}

/** 某几餐的碳水横向对比（用于“今天吃了什么”） */
export function MealCarbsChart({ meals }: { meals: MealRecord[] }) {
  if (meals.length === 0) {
    return <p className="chart-empty">今天还没有餐食记录。</p>;
  }
  const rows = [...meals]
    .sort((a, b) => a.eaten_at.localeCompare(b.eaten_at))
    .slice(0, 5)
    .map((meal) => ({ meal, carbs: Math.round(mealCarbs(meal) * 10) / 10 }));
  const max = Math.max(...rows.map((row) => row.carbs), 1);
  const rowH = 30;
  const H = rows.length * rowH + 16;
  const left = 104;
  const right = 44;
  const barMax = W - left - right;

  return (
    <div className="bar-chart">
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label="各餐碳水对比">
        {rows.map((row, i) => {
          const cy = 12 + i * rowH;
          const width = (row.carbs / max) * barMax;
          return (
            <g key={row.meal.meal_id}>
              <text x={0} y={cy + 12} className="bar-label">
                {row.meal.meal_type} {row.meal.eaten_at.slice(11, 16)}
              </text>
              <rect x={left} y={cy + 2} width={barMax} height={12} rx={3} className="bar-track" />
              <rect x={left} y={cy + 2} width={Math.max(0, width)} height={12} rx={3} className="bar-rect">
                <title>{`${foodsText(row.meal)} · 碳水 ${row.carbs}g`}</title>
              </rect>
              <text x={left + barMax + 6} y={cy + 12} className="bar-value">
                {row.carbs}g
              </text>
            </g>
          );
        })}
      </svg>
    </div>
  );
}

/** 最近 N 天血糖折线 */
export function GlucoseTrendChart({
  meals,
  days = 14,
  hideWhenEmpty = false,
}: {
  meals: MealRecord[];
  days?: number;
  hideWhenEmpty?: boolean;
}) {
  const points = useMemo(() => {
    const cutoff = Date.now() - days * 24 * 3600 * 1000;
    const items: { t: number; v: number; label: string }[] = [];
    for (const meal of meals) {
      for (const reading of meal.readings) {
        const t = Date.parse(reading.measured_at);
        if (Number.isNaN(t) || t < cutoff) continue;
        items.push({
          t,
          v: reading.value_mmol,
          label: `${foodsText(meal)} · ${glucoseTiming(reading.minutes_after)} ${reading.value_mmol} mmol/L`,
        });
      }
    }
    return items.sort((a, b) => a.t - b.t);
  }, [meals, days]);

  if (points.length === 0) {
    if (hideWhenEmpty) return null;
    return (
      <EmptyState
        title="还没有血糖记录"
        description="在餐食记录里补一个餐前或餐后 1/2 小时血糖，这里会画出最近 14 天的变化。"
      />
    );
  }

  const H = 180;
  const padBox = { l: 38, r: 14, t: 14, b: 26 };
  const values = points.map((p) => p.v);
  const yMin = Math.min(4, Math.floor(Math.min(...values) - 1));
  const yMax = Math.max(12, Math.ceil(Math.max(...values) + 1));
  const tMin = points[0].t;
  const tMax = points[points.length - 1].t;
  const x = (t: number) =>
    tMax === tMin
      ? (padBox.l + W - padBox.r) / 2
      : padBox.l + ((t - tMin) / (tMax - tMin)) * (W - padBox.l - padBox.r);
  const y = (v: number) => padBox.t + ((yMax - v) / (yMax - yMin)) * (H - padBox.t - padBox.b);
  const grid = [4, 7, 10, 13].filter((v) => v >= yMin && v <= yMax);
  const path = points.map((p) => `${x(p.t)},${y(p.v)}`).join(" ");
  const first = new Date(tMin).toLocaleDateString("zh-CN", { month: "2-digit", day: "2-digit" });
  const last = new Date(tMax).toLocaleDateString("zh-CN", { month: "2-digit", day: "2-digit" });

  return (
    <div className="trend-chart">
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`最近 ${days} 天血糖折线`}>
        {grid.map((v) => (
          <g key={v}>
            <line x1={padBox.l} x2={W - padBox.r} y1={y(v)} y2={y(v)} className="trend-grid" />
            <text x={padBox.l - 8} y={y(v) + 3} textAnchor="end" className="trend-axis">
              {v}
            </text>
          </g>
        ))}
        <polyline points={path} className="trend-line" fill="none" />
        {points.map((p, i) => (
          <circle key={i} cx={x(p.t)} cy={y(p.v)} r={3.5} className="trend-dot">
            <title>{p.label}</title>
          </circle>
        ))}
        <text x={padBox.l} y={H - 6} className="trend-axis">
          {first}
        </text>
        <text x={W - padBox.r} y={H - 6} textAnchor="end" className="trend-axis">
          {last}
        </text>
      </svg>
    </div>
  );
}

type ChartKind = "glucose" | "carbs" | "meals";

/** 只在问题确实在问“我的记录”时给图，知识问答不抢版面 */
function pickChart(question: string): ChartKind | null {
  if (!/(我|我的|今天|今日|昨天|这周|本周|最近|近\s*\d+\s*天|记录|档案)/.test(question)) {
    return null;
  }
  if (/血糖|读数|波动/.test(question)) return "glucose";
  if (/碳水|摄入/.test(question)) {
    // “今天吃了多少碳水”按餐次看；“这周/最近碳水”才看 7 天柱状
    return /(今天|今日)/.test(question) ? "meals" : "carbs";
  }
  if (/吃了什么|吃了啥|三餐|饮食|餐食|记录/.test(question)) return "meals";
  return null;
}

function todayMeals(meals: MealRecord[]): MealRecord[] {
  const key = dayKey(new Date());
  return meals.filter((meal) => meal.eaten_at.slice(0, 10) === key);
}

/** 回答下方的统计图：根据问题选血糖 / 每日碳水 / 当餐碳水 */
export function AnswerChart({ question, meals }: { question: string; meals: MealRecord[] }) {
  const kind = useMemo(() => pickChart(question), [question]);
  if (!kind) return null;

  if (kind === "glucose") {
    return (
      <section className="answer-chart">
        <div className="answer-chart-head">
          <strong>血糖走势</strong>
          <span>最近 14 天 · 个人记录</span>
        </div>
        <GlucoseTrendChart meals={meals} hideWhenEmpty />
      </section>
    );
  }

  if (kind === "carbs") {
    return (
      <section className="answer-chart">
        <div className="answer-chart-head">
          <strong>每日碳水合计</strong>
          <span>最近 7 天 · 个人记录</span>
        </div>
        <DailyCarbsChart meals={meals} />
      </section>
    );
  }

  const todays = todayMeals(meals);
  if (todays.length === 0) return null;
  return (
    <section className="answer-chart">
      <div className="answer-chart-head">
        <strong>今天各餐碳水</strong>
        <span>按餐次 · 个人记录</span>
      </div>
      <MealCarbsChart meals={todays} />
    </section>
  );
}
