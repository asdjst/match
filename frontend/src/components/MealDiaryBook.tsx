/**
 * 饮食日记本书浮窗：左下角日记图标打开，一本小日记的样子——
 * 左侧螺旋装订线、顶部和纸胶带、横线纸底色，内容为一页一天的 MealDiary。
 * 可拖动（拖页眉，点按钮不拖），Escape 收起；支持记一顿 / 编辑 / 补血糖 / 删除。
 */
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type PointerEvent as ReactPointerEvent,
} from "react";
import { AlertDialog, Banner, Button, EmptyState } from "@astryxdesign/core";
import { MealDiary } from "./MealDiary";
import { MealLogDialog, formatEatenAt } from "./MealLogDialog";
import { addGlucose, deleteMeal } from "../api/client";
import type { MealDraft, MealRecord } from "../types";

const clamp = (value: number, min: number, max: number) => Math.max(min, Math.min(value, max));

function foodsText(meal: MealRecord): string {
  return meal.foods.map((f) => `${f.name} ${Math.round(f.grams)}g`).join("、");
}

export interface MealDiaryBookProps {
  open: boolean;
  onClose: () => void;
  meals: MealRecord[];
  mealsError: boolean;
  /** 有记录被新增/修改/删除后通知父级刷新 */
  onChanged: () => void;
}

export default function MealDiaryBook({ open, onClose, meals, mealsError, onChanged }: MealDiaryBookProps) {
  const bookRef = useRef<HTMLElement | null>(null);
  const drag = useRef<{ id: number; startX: number; startY: number; x: number; y: number } | null>(null);
  const moved = useRef(false);
  const [pos, setPos] = useState<{ x: number; y: number } | null>(null);
  const [dragging, setDragging] = useState(false);

  const [createOpen, setCreateOpen] = useState(false);
  const [editing, setEditing] = useState<MealRecord | null>(null);
  const [pendingDelete, setPendingDelete] = useState<MealRecord | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [glucoseFor, setGlucoseFor] = useState<MealRecord | null>(null);
  const [glucoseValue, setGlucoseValue] = useState("");
  const [glucoseMinutes, setGlucoseMinutes] = useState(120);
  const [error, setError] = useState<string | null>(null);

  // 默认从右侧书签处展开
  const defaultPos = useCallback(() => {
    const parent = bookRef.current?.parentElement;
    const book = bookRef.current;
    if (!parent || !book) return { x: 8, y: 32 };
    return {
      x: Math.max(8, parent.clientWidth - book.offsetWidth - 20),
      y: 32,
    };
  }, []);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  const place = useCallback((x: number, y: number) => {
    const book = bookRef.current;
    const parent = book?.parentElement;
    if (!book || !parent) return;
    const next = {
      x: clamp(x, 8, Math.max(8, parent.clientWidth - book.offsetWidth - 8)),
      y: clamp(y, 8, Math.max(8, parent.clientHeight - book.offsetHeight - 8)),
    };
    setPos(next);
  }, []);

  useEffect(() => {
    if (open && !moved.current) place(defaultPos().x, defaultPos().y);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  const onPointerDown = (e: ReactPointerEvent<HTMLElement>) => {
    if (e.button !== 0 || !pos) return;
    // 点在按钮/输入框上时不进入拖动，否则 pointer capture 会让按钮收不到 click
    if ((e.target as HTMLElement).closest("button, a, input, select, textarea")) return;
    e.preventDefault();
    drag.current = { id: e.pointerId, startX: e.clientX, startY: e.clientY, x: pos.x, y: pos.y };
    e.currentTarget.setPointerCapture(e.pointerId);
    setDragging(true);
  };

  const onPointerMove = (e: ReactPointerEvent<HTMLElement>) => {
    const state = drag.current;
    if (!state || state.id !== e.pointerId) return;
    moved.current = true;
    place(state.x + e.clientX - state.startX, state.y + e.clientY - state.startY);
  };

  const endDrag = (e: ReactPointerEvent<HTMLElement>) => {
    if (!drag.current) return;
    drag.current = null;
    setDragging(false);
    if (e.currentTarget.hasPointerCapture(e.pointerId)) e.currentTarget.releasePointerCapture(e.pointerId);
  };

  const editInitial = useMemo<Partial<MealDraft> | null>(
    () =>
      editing
        ? {
            eaten_at: editing.eaten_at,
            meal_type: editing.meal_type,
            foods: editing.foods,
            note: editing.note,
            insulin_note: editing.insulin_note,
            source: editing.source,
            image_id: editing.image_id,
          }
        : null,
    [editing],
  );

  const saveGlucose = async (meal: MealRecord) => {
    const value = Number(glucoseValue);
    if (!value || value < 1 || value > 40) {
      setError("血糖请填 1–40 之间的数值（mmol/L）");
      return;
    }
    try {
      // 24 小时视图要的是「就餐时间 + 餐后时长」
      const base = Date.parse(meal.eaten_at);
      const measuredAt = Number.isNaN(base)
        ? undefined
        : new Date(base + glucoseMinutes * 60_000).toISOString();
      await addGlucose(meal.meal_id, value, glucoseMinutes, measuredAt);
      setGlucoseFor(null);
      setGlucoseValue("");
      setError(null);
      onChanged();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  };

  const confirmDelete = async () => {
    if (!pendingDelete) return;
    setDeleting(true);
    try {
      await deleteMeal(pendingDelete.meal_id);
      setPendingDelete(null);
      onChanged();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setDeleting(false);
    }
  };

  if (!open) return null;
  const style = pos ? { left: pos.x, top: pos.y } : { right: 20, top: 32 };

  const dialogOpen = createOpen || editing !== null;
  const closeDialog = () => {
    setCreateOpen(false);
    setEditing(null);
  };

  return (
    <section
      ref={bookRef}
      id="meal-diary-book"
      className={`diary-book${dragging ? " is-dragging" : ""}`}
      style={style}
      role="dialog"
      aria-modal="false"
      aria-label="饮食日记"
      tabIndex={-1}
    >
      <header
        className="diary-book-head"
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={endDrag}
        onPointerCancel={endDrag}
      >
        <div className="diary-book-title">
          <strong>饮食日记</strong>
          <small>MEAL DIARY · {meals.length ? `${meals.length} 条` : ""}</small>
        </div>
        <Button label="记一顿" variant="secondary" size="sm" onClick={() => setCreateOpen(true)} />
        <button type="button" className="diary-book-close" aria-label="收起日记" onClick={onClose}>
          <svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" aria-hidden="true">
            <path d="m7 7 10 10M17 7 7 17" />
          </svg>
        </button>
      </header>

      <div className="diary-book-body">
        {error ? <Banner status="error" title="操作失败" description={error} /> : null}
        {mealsError ? (
          <div className="profile-empty">
            <EmptyState title="餐食记录没读到" description="后端连接正常但记录接口返回失败，日记暂时打不开。" />
          </div>
        ) : meals.length === 0 ? (
          <div className="profile-empty">
            <EmptyState
              title="日记还是空白页"
              description="拍一张餐盘照片后点「记下来」，或点右上角「记一顿」，今天的第一页就有了。"
              actions={<Button label="记一顿" variant="primary" size="sm" onClick={() => setCreateOpen(true)} />}
            />
          </div>
        ) : (
          <MealDiary
            meals={meals}
            onEdit={setEditing}
            onAddGlucose={(meal) => {
              setGlucoseFor(meal);
              setGlucoseValue("");
              setGlucoseMinutes(120);
            }}
            onDelete={setPendingDelete}
            footer={
              glucoseFor ? (
                <div className="glucose-form">
                  <input
                    className="field-input"
                    inputMode="decimal"
                    placeholder="血糖 mmol/L"
                    value={glucoseValue}
                    onChange={(e) => setGlucoseValue(e.target.value)}
                  />
                  <select
                    className="field-input"
                    value={glucoseMinutes}
                    onChange={(e) => setGlucoseMinutes(Number(e.target.value))}
                  >
                    <option value={0}>餐前</option>
                    <option value={30}>餐后 30 分钟</option>
                    <option value={60}>餐后 1 小时</option>
                    <option value={90}>餐后 1.5 小时</option>
                    <option value={120}>餐后 2 小时</option>
                    <option value={180}>餐后 3 小时</option>
                  </select>
                  <Button label="保存" variant="primary" size="sm" onClick={() => void saveGlucose(glucoseFor)} />
                  <Button label="取消" variant="ghost" size="sm" onClick={() => setGlucoseFor(null)} />
                </div>
              ) : null
            }
          />
        )}
      </div>

      <MealLogDialog
        open={dialogOpen}
        mealId={editing?.meal_id ?? null}
        initial={editInitial}
        title={editing ? "编辑这顿记录" : "记一顿"}
        dismissLabel="取消"
        onClose={closeDialog}
        onSaved={() => onChanged()}
      />
      <AlertDialog
        isOpen={pendingDelete !== null}
        onOpenChange={(o) => {
          if (!o && !deleting) setPendingDelete(null);
        }}
        title="删除这条记录？"
        description={
          pendingDelete
            ? `${formatEatenAt(pendingDelete.eaten_at)} ${pendingDelete.meal_type} · ${foodsText(pendingDelete)}。记录和它下面的血糖读数会一起删除，不可恢复。`
            : ""
        }
        cancelLabel="取消"
        actionLabel="删除"
        actionVariant="destructive"
        isActionLoading={deleting}
        onAction={() => void confirmDelete()}
      />
    </section>
  );
}
