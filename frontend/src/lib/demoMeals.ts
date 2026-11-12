/**
 * 示例数据：只在前端内存里生成，用于演示统计口径，绝不写入健康档案。
 * 固定随机种子，保证每次打开看到的曲线一致。
 */
import type { MealFood, MealRecord, MealType } from "../types";
import { pad } from "./glucoseStats";

function mulberry32(seed: number) {
  let a = seed;
  return () => {
    a |= 0;
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

const MENUS: Record<MealType, { foods: MealFood[]; at: [number, number] }[]> = {
  早餐: [
    { at: [7, 20], foods: [{ name: "全麦馒头", grams: 80, carbs_g: 36 }, { name: "鸡蛋", grams: 50, carbs_g: 0.6 }, { name: "无糖豆浆", grams: 250, carbs_g: 4 }] },
    { at: [7, 45], foods: [{ name: "白粥", grams: 300, carbs_g: 27 }, { name: "肉包", grams: 100, carbs_g: 30 }, { name: "咸菜", grams: 20, carbs_g: 1 }] },
    { at: [8, 5], foods: [{ name: "燕麦片", grams: 45, carbs_g: 27 }, { name: "牛奶", grams: 250, carbs_g: 12 }, { name: "蓝莓", grams: 60, carbs_g: 8 }] },
  ],
  午餐: [
    { at: [12, 10], foods: [{ name: "米饭", grams: 200, carbs_g: 52 }, { name: "清蒸鲈鱼", grams: 120, carbs_g: 0 }, { name: "西兰花", grams: 150, carbs_g: 6 }] },
    { at: [12, 30], foods: [{ name: "牛肉面", grams: 450, carbs_g: 78 }, { name: "卤蛋", grams: 50, carbs_g: 0.6 }] },
    { at: [11, 55], foods: [{ name: "杂粮饭", grams: 180, carbs_g: 41 }, { name: "鸡胸肉", grams: 120, carbs_g: 0 }, { name: "菠菜", grams: 150, carbs_g: 4 }] },
  ],
  晚餐: [
    { at: [18, 40], foods: [{ name: "米饭", grams: 180, carbs_g: 47 }, { name: "番茄炒蛋", grams: 160, carbs_g: 6 }, { name: "冬瓜汤", grams: 200, carbs_g: 4 }] },
    { at: [19, 15], foods: [{ name: "火锅", grams: 500, carbs_g: 62 }, { name: "虾滑", grams: 80, carbs_g: 5 }, { name: "莲藕", grams: 70, carbs_g: 11 }] },
    { at: [18, 20], foods: [{ name: "荞麦面", grams: 220, carbs_g: 46 }, { name: "凉拌豆腐", grams: 120, carbs_g: 3 }, { name: "青菜", grams: 150, carbs_g: 4 }] },
  ],
  加餐: [
    { at: [15, 30], foods: [{ name: "苹果", grams: 180, carbs_g: 24 }] },
    { at: [21, 10], foods: [{ name: "无糖酸奶", grams: 120, carbs_g: 6 }, { name: "核桃", grams: 15, carbs_g: 2 }] },
  ],
};

const NOTES = ["", "", "饭后散步 20 分钟", "食堂", "加班吃得晚", "先吃菜后吃饭"];

/** 餐后曲线形状：峰值出现在 60–90 分钟，之后回落 */
function curve(base: number, rise: number, minutes: number, jitter: number): number {
  if (minutes <= 0) return base + jitter;
  const shape = Math.exp(-((minutes - 75) ** 2) / (2 * 55 ** 2));
  const tail = minutes > 150 ? -0.4 : 0;
  return base + rise * shape + tail + jitter;
}

export function buildDemoMeals(now = Date.now(), days = 14): MealRecord[] {
  const rand = mulberry32(20261118);
  const meals: MealRecord[] = [];
  const today = new Date(now);
  today.setHours(0, 0, 0, 0);

  for (let d = days - 1; d >= 0; d -= 1) {
    const day = new Date(today);
    day.setDate(day.getDate() - d);
    const stamp = `${day.getFullYear()}-${pad(day.getMonth() + 1)}-${pad(day.getDate())}`;
    // 周末与其中两天故意做成高碳水日，让达标率与波动有差别
    const rough = day.getDay() === 0 || day.getDay() === 6 || d === 5 || d === 9;
    // 其中一天运动量大，餐前偏低，让低血糖区间也有样本
    const lowDay = d === 2;
    const dayBase = (lowDay ? 3.5 + rand() * 0.7 : 5.2 + rand() * 1.1) + (rough ? 0.7 : 0);

    const plan: MealType[] = rough ? ["早餐", "午餐", "加餐", "晚餐"] : ["早餐", "午餐", "晚餐"];
    for (const type of plan) {
      const options = MENUS[type];
      const menu = options[Math.floor(rand() * options.length)];
      const minute = menu.at[1] + Math.round((rand() - 0.5) * 24);
      const eaten = new Date(day);
      eaten.setHours(menu.at[0], Math.max(0, Math.min(59, minute)), 0, 0);
      if (eaten.getTime() > now) continue;

      const scale = rough ? 1.25 : 1;
      const foods = menu.foods.map((f) => ({
        ...f,
        grams: Math.round(f.grams * (0.9 + rand() * 0.25)),
        carbs_g: Math.round((f.carbs_g ?? 0) * scale * 10) / 10,
      }));
      const carbs = Math.round(foods.reduce((s, f) => s + (f.carbs_g ?? 0), 0) * 10) / 10;
      const rise = (carbs / 22) * (rough ? 1.5 : 1.05) + rand() * 0.8;
      const mealId = `demo-${stamp}-${type}`;
      const timings = type === "加餐" ? [0, 60] : [0, 60, 120, 180];

      const readings = timings
        .filter((m) => eaten.getTime() + m * 60_000 <= now)
        .map((m, i) => {
          const jitter = (rand() - 0.5) * 0.7;
          const value = Math.max(3.2, Math.round(curve(dayBase, rise, m, jitter) * 10) / 10);
          const at = new Date(eaten.getTime() + m * 60_000);
          return {
            reading_id: `${mealId}-${i}`,
            meal_id: mealId,
            measured_at: at.toISOString(),
            minutes_after: m,
            value_mmol: value,
            source: "manual" as const,
          };
        });

      meals.push({
        meal_id: mealId,
        user_id: "demo",
        eaten_at: `${stamp}T${pad(eaten.getHours())}:${pad(eaten.getMinutes())}`,
        meal_type: type,
        foods,
        carbs_g: carbs,
        gl: Math.round(carbs * 0.55),
        note: NOTES[Math.floor(rand() * NOTES.length)],
        source: "manual",
        image_id: null,
        insulin_note: "",
        created_at: eaten.toISOString(),
        updated_at: eaten.toISOString(),
        readings,
      });
    }
  }
  return meals.sort((a, b) => b.eaten_at.localeCompare(a.eaten_at));
}