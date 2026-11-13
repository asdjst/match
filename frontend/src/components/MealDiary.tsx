/**
 * 饮食日记：一页一天，按日期翻页。
 * 复用餐食列表的条目样式；页眉是日期 + 当天小统计（几餐 / 碳水合计 / 血糖最高最低）。
 */
import { useMemo, useState, type ReactNode } from "react";
import { formatEatenAt } from "./MealLogDialog";
import type { MealRecord, MealType } from "../types";

const WEEKDAYS = ["周日", "周一", "周二", "周三", "周四", "周五", "周六"];

/** 餐次印章颜色：复用健康趋势的餐次配色（--zone） */
const MEAL_STAMP: Record<MealType, string> = {
  早餐: "breakfast",
  午餐: "lunch",
  晚餐: "dinner",
  加餐: "snack",
};

function dayKeyOf(eatenAt: string): string {
  return (eatenAt || "").slice(0, 10);
}

function todayKey(): string {
  const now = new Date();
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;
}

function dayLabel(key: string): string {
  const d = new Date(`${key}T00:00:00`);
  if (Number.isNaN(d.getTime())) return key;
  return `${d.getMonth() + 1} 月 ${d.getDate()} 日 ${WEEKDAYS[d.getDay()]}`;
}

function mealCarbs(meal: MealRecord): number {
  if (typeof meal.carbs_g === "number") return meal.carbs_g;
  return meal.foods.reduce((sum, f) => sum + (f.carbs_g ?? 0), 0);
}

function foodsText(meal: MealRecord): string {
  return meal.foods.map((f) => `${f.name} ${Math.round(f.grams)}g`).join("、");
}

function carbsText(meal: MealRecord): string {
  if (meal.carbs_g == null) return "碳水未填";
  const estimated = meal.foods.filter((f) => f.estimated).length;
  const tag = estimated === 0 ? "" : estimated === meal.foods.length ? "（估算）" : "（含估算）";
  return `碳水约 ${meal.carbs_g}g${tag}`;
}

function timingLabel(minutes: number): string {
  if (minutes <= 0) return "餐前";
  if (minutes % 60 === 0) return `餐后 ${minutes / 60} 小时`;
  return `餐后 ${minutes} 分钟`;
}

export interface MealDiaryProps {
  /** 已按餐次/关键词过滤的记录 */
  meals: MealRecord[];
  /** 传了才显示 编辑/补血糖/删除 操作（日记本只读模式不传） */
  onEdit?: (meal: MealRecord) => void;
  onAddGlucose?: (meal: MealRecord) => void;
  onDelete?: (meal: MealRecord) => void;
  /** 补血糖表单等额外内容，渲染在当天条目下方 */
  footer?: ReactNode;
}

export function MealDiary({ meals, onEdit, onAddGlucose, onDelete, footer }: MealDiaryProps) {
  const [page, setPage] = useState(0);

  const days = useMemo(() => {
    const byDay = new Map<string, MealRecord[]>();
    for (const meal of meals) {
      const key = dayKeyOf(meal.eaten_at);
      const arr = byDay.get(key) ?? [];
      arr.push(meal);
      byDay.set(key, arr);
    }
    return [...byDay.entries()]
      .sort((a, b) => (a[0] < b[0] ? 1 : -1))
      .map(([key, list]) => ({
        key,
        meals: [...list].sort((a, b) => a.eaten_at.localeCompare(b.eaten_at)),
      }));
  }, [meals]);

  if (days.length === 0) return null;
  const safe = Math.min(page, days.length - 1);
  const day = days[safe];
  const dayCarbs = Math.round(day.meals.reduce((s, m) => s + mealCarbs(m), 0) * 10) / 10;
  const readings = day.meals.flatMap((m) => m.readings);
  const maxR = readings.length ? Math.max(...readings.map((r) => r.value_mmol)) : null;
  const minR = readings.length ? Math.min(...readings.map((r) => r.value_mmol)) : null;

  return (
    <div className="diary">
      <section className="diary-day" aria-label={dayLabel(day.key)}>
        <div className="diary-head">
          <span className="diary-date">
            {dayLabel(day.key)}
            {day.key === todayKey() ? <small> · 今天</small> : null}
          </span>
          <span className="diary-stats">
            {day.meals.length} 餐 · 碳水合计 {dayCarbs}g
            {maxR != null ? ` · 血糖最高 ${maxR.toFixed(1)} / 最低 ${minR!.toFixed(1)}` : ""}
          </span>
        </div>

        <div className="meal-record-list">
          {day.meals.map((meal) => (
            <div className="meal-record" key={meal.meal_id}>
              <div className="meal-record-time diary-entry-time">
                <span className={`diary-stamp m-${MEAL_STAMP[meal.meal_type]}`}>{meal.meal_type}</span>
                <strong>{formatEatenAt(meal.eaten_at).slice(11)}</strong>
              </div>
              <div className="meal-record-main">
                <strong>{foodsText(meal)}</strong>
                <small>
                  {carbsText(meal)}
                  {meal.gl != null ? ` · GL 约 ${meal.gl}` : ""}
                  {meal.note ? ` · ${meal.note}` : ""}
                </small>
                {meal.image_id ? (
                  <img
                    className="diary-photo"
                    src={`/api/food/images/${meal.image_id}`}
                    alt="餐食照片"
                    onError={(e) => {
                      e.currentTarget.style.display = "none";
                    }}
                  />
                ) : null}
                {meal.readings.length > 0 ? (
                  <div className="meal-record-readings">
                    {meal.readings.map((r) => (
                      <span className="reading-chip" key={r.reading_id}>
                        {timingLabel(r.minutes_after)} {r.value_mmol.toFixed(1)}
                      </span>
                    ))}
                  </div>
                ) : null}
              </div>
              {onEdit && onAddGlucose && onDelete ? (
                <div className="meal-record-actions">
                  <button type="button" className="row-action" onClick={() => onEdit(meal)}>
                    编辑
                  </button>
                  <button type="button" className="row-action" onClick={() => onAddGlucose(meal)}>
                    补血糖
                  </button>
                  <button type="button" className="row-action row-action--danger" onClick={() => onDelete(meal)}>
                    删除
                  </button>
                </div>
              ) : null}
            </div>
          ))}
        </div>
        {footer}
      </section>

      {days.length > 1 ? (
        <div className="meal-pager">
          <button
            type="button"
            className="row-action"
            disabled={safe === 0}
            onClick={() => setPage(safe - 1)}
          >
            ‹ 上一天
          </button>
          <span>
            {safe + 1} / {days.length} 天
          </span>
          <button
            type="button"
            className="row-action"
            disabled={safe >= days.length - 1}
            onClick={() => setPage(safe + 1)}
          >
            下一天 ›
          </button>
        </div>
      ) : null}
    </div>
  );
}
