/** 餐食记录弹窗：拍照识别、对话意图和健康档案手动录入共用一套字段。 */
import { useEffect, useState } from "react";
import { Banner, Button, Card, Stack, Text } from "@astryxdesign/core";
import { createMeal, updateMeal } from "../api/client";
import type { MealDraft, MealFood, MealRecord, MealType } from "../types";

const MEAL_TYPES: MealType[] = ["早餐", "午餐", "晚餐", "加餐"];
const EMPTY_FOOD: MealFood = { name: "", grams: 150, carbs_g: null };

export function localNow(): string {
  const d = new Date();
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

export function mealTypeFor(date = new Date()): MealType {
  const h = date.getHours();
  if (h < 10) return "早餐";
  if (h < 15) return "午餐";
  if (h < 21) return "晚餐";
  return "加餐";
}

export function formatEatenAt(value: string): string {
  return (value || "").replace("T", " ").slice(0, 16);
}

export interface MealLogDialogProps {
  open: boolean;
  initial?: Partial<MealDraft> | null;
  /** 传了就是改这条已有记录，走 PATCH；不传是新增 */
  mealId?: string | null;
  title?: string;
  dismissLabel?: string;
  onClose: () => void;
  onSaved: (meal: MealRecord) => void;
}

export function MealLogDialog({
  open,
  initial,
  mealId = null,
  title = "记这一顿吗？",
  dismissLabel = "只是问问",
  onClose,
  onSaved,
}: MealLogDialogProps) {
  const [eatenAt, setEatenAt] = useState(localNow);
  const [mealType, setMealType] = useState<MealType>(mealTypeFor);
  const [foods, setFoods] = useState<MealFood[]>([EMPTY_FOOD]);
  const [note, setNote] = useState("");
  const [insulinNote, setInsulinNote] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    setEatenAt(initial?.eaten_at || localNow());
    setMealType(initial?.meal_type || mealTypeFor());
    setFoods(initial?.foods?.length ? initial.foods.map((f) => ({ ...f })) : [{ ...EMPTY_FOOD }]);
    setNote(initial?.note || "");
    setInsulinNote(initial?.insulin_note || "");
    setError(null);
  }, [open, initial]);

  if (!open) return null;

  const patchFood = (index: number, patch: Partial<MealFood>) => {
    setFoods((prev) =>
      prev.map((food, i) => {
        if (i !== index) return food;
        const next = { ...food, ...patch };
        // 名字或克数一改，原来折算的碳水就不成立了：留空让后端按新克数重算
        if (food.estimated && (patch.name !== undefined || patch.grams !== undefined)) {
          next.carbs_g = null;
          next.gl = null;
          next.estimated = false;
        }
        if (patch.carbs_g !== undefined) next.estimated = false;
        return next;
      }),
    );
  };

  const save = async () => {
    const clean = foods
      .map((f) => ({
        ...f,
        name: f.name.trim(),
        grams: Number(f.grams) || 0,
        carbs_g: f.carbs_g == null ? null : Number(f.carbs_g),
      }))
      .filter((f) => f.name && f.grams > 0);
    if (clean.length === 0) {
      setError("至少填一样食物和克数");
      return;
    }
    setSaving(true);
    setError(null);
    try {
      const meal = mealId
        ? await updateMeal(mealId, {
            eaten_at: eatenAt,
            meal_type: mealType,
            foods: clean,
            note: note.trim(),
            insulin_note: insulinNote.trim(),
          })
        : await createMeal({
            eaten_at: eatenAt,
            meal_type: mealType,
            foods: clean,
            note: note.trim(),
            source: initial?.source ?? "manual",
            image_id: initial?.image_id ?? null,
            insulin_note: insulinNote.trim(),
          });
      onSaved(meal);
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="meal-dialog-backdrop" role="presentation">
      <Card padding={5} className="meal-dialog" role="dialog" aria-modal="true" aria-label={title}>
        <Stack gap={4}>
          <div className="meal-dialog-head">
            <div>
              <div className="food-title">{title}</div>
              <Text size="2xs" color="secondary">
                记录会进入健康档案，并作为下次提问时可以先查的个人记忆。
              </Text>
            </div>
            <Button label={dismissLabel} variant="ghost" size="sm" onClick={onClose} />
          </div>

          <div className="field-grid">
            <label className="field">
              <span>时间</span>
              <input
                className="field-input"
                type="datetime-local"
                value={eatenAt}
                onChange={(e) => setEatenAt(e.target.value)}
              />
            </label>
            <label className="field">
              <span>餐次</span>
              <select
                className="field-input"
                value={mealType}
                onChange={(e) => setMealType(e.target.value as MealType)}
              >
                {MEAL_TYPES.map((t) => (
                  <option key={t}>{t}</option>
                ))}
              </select>
            </label>
          </div>

          <Stack gap={2}>
            <Text size="2xs" weight="semibold" color="secondary">
              吃了什么（碳水留空会按食物库折算）
            </Text>
            {foods.map((food, i) => (
              <div className="meal-food-row" key={i}>
                <input
                  className="field-input meal-food-name"
                  placeholder="食物名，如 米饭"
                  value={food.name}
                  onChange={(e) => patchFood(i, { name: e.target.value })}
                />
                <input
                  className="field-input meal-food-num"
                  inputMode="decimal"
                  placeholder="克数"
                  value={food.grams || ""}
                  onChange={(e) => patchFood(i, { grams: Number(e.target.value) })}
                />
                <input
                  className="field-input meal-food-num"
                  inputMode="decimal"
                  placeholder="碳水g"
                  value={food.carbs_g ?? ""}
                  onChange={(e) =>
                    patchFood(i, {
                      carbs_g: e.target.value === "" ? null : Number(e.target.value),
                    })
                  }
                />
                <Button
                  label="删除"
                  variant="ghost"
                  size="sm"
                  onClick={() => setFoods((prev) => (prev.length > 1 ? prev.filter((_, j) => j !== i) : prev))}
                />
              </div>
            ))}
            <div>
              <Button
                label="再加一样"
                variant="secondary"
                size="sm"
                onClick={() => setFoods((prev) => [...prev, { ...EMPTY_FOOD }])}
              />
            </div>
          </Stack>

          <label className="field">
            <span>备注（可选）</span>
            <input
              className="field-input"
              placeholder="例如 食堂、聚餐、饭后散步 20 分钟"
              value={note}
              onChange={(e) => setNote(e.target.value)}
            />
          </label>

          <details className="meal-dialog-private">
            <summary>用药记录（仅本人可见，不参与问答）</summary>
            <input
              className="field-input"
              placeholder="如 8 单位；只记录，不建议、不比较"
              value={insulinNote}
              onChange={(e) => setInsulinNote(e.target.value)}
            />
          </details>

          {error ? <Banner status="error" title={mealId ? "保存失败" : "记录失败"} description={error} /> : null}

          <Stack direction="horizontal" gap={2} justify="end">
            <Button label={dismissLabel} variant="secondary" onClick={onClose} />
            <Button label={mealId ? "保存修改" : "记下来"} variant="primary" isLoading={saving} isDisabled={saving} onClick={() => void save()} />
          </Stack>
        </Stack>
      </Card>
    </div>
  );
}
