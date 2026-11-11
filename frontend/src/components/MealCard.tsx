/**
 * 用户消息里的餐食卡：照片 + 识别清单。
 * GI 来自执行阶段 query_food_nutrition 的真实工具返回，未跑完时显示占位。
 */
import { Badge, Text } from "@astryxdesign/core";
import type { RunState } from "../store/runs";
import type { FoodContext, FoodItem } from "../types";

interface ToolCall {
  tool: string;
  ok?: boolean;
  gi?: number | null;
  args?: { name?: string };
  result?: { gi?: number | null } | number | null;
}

function callsOf(run: RunState): ToolCall[] {
  const out: ToolCall[] = [];
  for (const result of Object.values(run.nodeResults ?? {})) {
    const calls = (result.output as { calls?: unknown } | null | undefined)?.calls;
    if (Array.isArray(calls)) out.push(...(calls as ToolCall[]));
  }
  return out;
}

function giFor(item: FoodItem, calls: ToolCall[]): number | null {
  // query_food_nutrition 把 GI 放在 result 里，calculate_gl 放在顶层
  for (const c of calls) {
    if (c.ok === false || c.args?.name !== item.name) continue;
    if (c.tool === "query_food_nutrition") {
      const gi = c.gi ?? (typeof c.result === "object" ? c.result?.gi : null);
      if (gi != null) return gi;
    }
    if (c.tool === "calculate_gl" && c.gi != null) return c.gi;
  }
  return null;
}

function glFor(item: FoodItem, calls: ToolCall[]): number | null {
  for (const c of calls) {
    if (c.tool !== "calculate_gl" || c.ok === false || c.args?.name !== item.name) continue;
    if (typeof c.result === "number") return c.result;
  }
  return null;
}

function giLevel(gi: number): "low" | "mid" | "high" {
  if (gi <= 55) return "low";
  if (gi <= 69) return "mid";
  return "high";
}

// 升糖负荷分级：≤10 低、11–19 中、≥20 高
function loadLevel(gl: number): "low" | "mid" | "high" {
  if (gl <= 10) return "low";
  if (gl < 20) return "mid";
  return "high";
}

const LOAD_LABEL = { low: "低负荷", mid: "中负荷", high: "高负荷" } as const;

export function MealCard({ food, run }: { food: FoodContext; run: RunState }) {
  const calls = callsOf(run);
  const low = food.food_items.reduce((n, i) => n + i.carbs_g_low, 0);
  const high = food.food_items.reduce((n, i) => n + i.carbs_g_high, 0);
  const gls = food.food_items.map((i) => glFor(i, calls));
  // 只有每样都拿到工具结果才给合计 GL，避免半套数据冒充全餐
  const totalGl =
    food.food_items.length > 0 && gls.every((g) => g != null)
      ? (gls as number[]).reduce((a, b) => a + b, 0)
      : null;

  return (
    <div className={`meal-card${food.photo_url ? "" : " is-solo"}`}>
      {food.photo_url ? (
        <div className="meal-photo-wrap">
          <img className="meal-photo" src={food.photo_url} alt="餐盘照片" />
        </div>
      ) : null}

      <div className="meal-body">
        <div className="meal-head">
          <span className="meal-title">餐盘识别</span>
          <Badge variant="neutral" label={`${food.food_items.length} 样`} />
        </div>

        <div className="meal-rows">
          {food.food_items.map((item, i) => {
            const grams = Math.round((item.grams_low + item.grams_high) / 2);
            const carbs = (item.carbs_g_low + item.carbs_g_high) / 2;
            const gi = giFor(item, calls);
            return (
              <div className="meal-row" key={`${item.name}-${i}`}>
                <div className="meal-icon" aria-hidden="true">
                  {item.name.slice(0, 1)}
                </div>
                <div className="meal-name">
                  <strong>{item.name}</strong>
                  <small>置信度 {Math.round(item.confidence * 100)}%</small>
                </div>
                <div className="meal-num">
                  <strong>{grams}</strong>
                  <small>g</small>
                </div>
                <div className="meal-num">
                  <strong>{carbs.toFixed(1)}</strong>
                  <small>g 碳水</small>
                </div>
                {gi != null ? (
                  <span className={`gi-tag ${giLevel(gi)}`}>GI {gi}</span>
                ) : (
                  <span className="gi-tag pending">GI 待算</span>
                )}
              </div>
            );
          })}
        </div>

        <div className="meal-foot">
          <div className="meal-total">
            <span>合计碳水</span>
            <strong>
              {low.toFixed(1)}–{high.toFixed(1)}
              <small> g</small>
            </strong>
          </div>
          {totalGl != null ? (
            <div className="meal-load">
              <strong>{totalGl.toFixed(1)}</strong>
              <small>GL</small>
              <span className={`load-tag ${loadLevel(totalGl)}`}>{LOAD_LABEL[loadLevel(totalGl)]}</span>
            </div>
          ) : (
            <span className="gi-tag pending">GL 待算</span>
          )}
          <div className="meal-disclaimer">
            <Text size="2xs" color="secondary">
              仅供饮食参考，不构成医疗建议
            </Text>
          </div>
        </div>
      </div>
    </div>
  );
}
