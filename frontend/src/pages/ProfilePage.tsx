/**
 * 健康档案：基础信息 + 餐食记录 + 趋势。
 * 基础信息只存浏览器；餐食记录存后端 SQLite，既是档案也是问答记忆。
 */
import { useCallback, useEffect, useMemo, useState, type RefObject } from "react";
import { createPortal } from "react-dom";
import { Banner, Button, EmptyState, Text } from "@astryxdesign/core";
import { addGlucose, deleteGlucose, deleteMeal, listMeals } from "../api/client";
import { AuthDialog } from "../components/AuthDialog";
import { MealLogDialog, formatEatenAt } from "../components/MealLogDialog";
import HealthTrends from "../components/HealthTrends";
import { useAuth } from "../store/auth";
import { useRuns } from "../store/runs";
import type { MealDraft, MealRecord, MealType } from "../types";

interface Profile {
  height: string;
  weight: string;
  age: string;
  activity: "久坐" | "轻度活动" | "规律运动";
}

const EMPTY: Profile = {
  height: "",
  weight: "",
  age: "",
  activity: "久坐",
};

const KEY = "glucoguard.profile";

function load(): Profile {
  try {
    const raw = localStorage.getItem(KEY);
    if (!raw) return EMPTY;
    return { ...EMPTY, ...(JSON.parse(raw) as Partial<Profile>) };
  } catch {
    return EMPTY;
  }
}

function foodsText(meal: MealRecord): string {
  return meal.foods.map((f) => `${f.name} ${Math.round(f.grams)}g`).join("、");
}

/** 碳水是食物库折算的还是用户自填的，要分清楚 */
function carbsText(meal: MealRecord): string {
  if (meal.carbs_g == null) return "碳水未填";
  const estimated = meal.foods.filter((f) => f.estimated).length;
  const tag = estimated === 0 ? "" : estimated === meal.foods.length ? "（估算）" : "（含估算）";
  return `碳水约 ${meal.carbs_g}g${tag}`;
}

/** 0 分钟表示餐前；整小时按小时显示，其余按分钟 */
function glucoseTiming(minutes: number): string {
  if (minutes <= 0) return "餐前";
  if (minutes % 60 === 0) return `餐后 ${minutes / 60} 小时`;
  return `餐后 ${minutes} 分钟`;
}

export default function ProfilePage({
  embedded = false,
  scrollRef,
  onScroll,
}: {
  embedded?: boolean;
  scrollRef?: RefObject<HTMLDivElement | null>;
  onScroll?: () => void;
}) {
  const { transportKind } = useRuns();
  const { account } = useAuth();
  const [profile, setProfile] = useState<Profile>(load);
  const [authMode, setAuthMode] = useState<"login" | "register" | null>(null);
  const [tab, setTab] = useState<"records" | "trend">("records");
  const [meals, setMeals] = useState<MealRecord[]>([]);
  const [loadFailed, setLoadFailed] = useState(false);
  const [logOpen, setLogOpen] = useState(false);
  const [editing, setEditing] = useState<MealRecord | null>(null);
  const [saved, setSaved] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [glucoseFor, setGlucoseFor] = useState<string | null>(null);
  const [glucoseValue, setGlucoseValue] = useState("");
  const [glucoseMinutes, setGlucoseMinutes] = useState(120);
  const [mealFilter, setMealFilter] = useState<MealType | "全部">("全部");
  const [query, setQuery] = useState("");

  useEffect(() => {
    try {
      localStorage.setItem(KEY, JSON.stringify(profile));
    } catch {
      // 隐私模式下写入失败不影响填写
    }
  }, [profile]);

  const refresh = useCallback(async () => {
    setError(null);
    try {
      setMeals(await listMeals(100));
      setLoadFailed(false);
    } catch {
      // 读不到 ≠ 没有记录：保留旧数据并显式报错，别把空档案当成事实
      setLoadFailed(true);
    }
  }, []);

  // 换账号或重连都先清掉手上这份记录：不能让上一个人的餐食留在屏幕上
  useEffect(() => {
    setMeals([]);
    setLoadFailed(false);
    if (transportKind === "live") void refresh();
  }, [account?.user_id, transportKind, refresh]);

  // 读失败且手上没有任何记录：不渲染“还没有记录”一类空态，免得把故障说成空档案
  const noData = loadFailed && meals.length === 0;

  const height = Number(profile.height);
  const weight = Number(profile.weight);
  const bmi = useMemo(() => {
    if (!height || !weight || height < 80 || weight < 20) return null;
    return weight / (height / 100) ** 2;
  }, [height, weight]);
  const bmiLevel =
    bmi == null ? null : bmi < 18.5 ? "偏低" : bmi < 24 ? "正常" : bmi < 28 ? "偏重" : "肥胖";

  // 餐次筛选 + 关键词匹配（食物名/备注/餐次，支持空格分隔多词）
  const filteredMeals = useMemo(() => {
    const tokens = query.trim().toLowerCase().split(/\s+/).filter(Boolean);
    return meals.filter((meal) => {
      if (mealFilter !== "全部" && meal.meal_type !== mealFilter) return false;
      if (tokens.length === 0) return true;
      const hay = [meal.meal_type, meal.note, ...meal.foods.map((f) => f.name)]
        .join(" ")
        .toLowerCase();
      return tokens.every((t) => hay.includes(t));
    });
  }, [meals, mealFilter, query]);

  const saveGlucose = async (meal: MealRecord) => {
    const value = Number(glucoseValue);
    if (!value || value < 1 || value > 40) {
      setError("血糖请填 1–40 之间的数值（mmol/L）");
      return;
    }
    try {
      // 后端默认把录入时刻当测量时刻，24 小时视图要的是「就餐时间 + 餐后时长」
      const base = Date.parse(meal.eaten_at);
      const measuredAt = Number.isNaN(base)
        ? undefined
        : new Date(base + glucoseMinutes * 60_000).toISOString();
      await addGlucose(meal.meal_id, value, glucoseMinutes, measuredAt);
      setGlucoseFor(null);
      setGlucoseValue("");
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  };

  const removeMeal = async (meal: MealRecord) => {
    if (!window.confirm(`删除 ${formatEatenAt(meal.eaten_at)} 的这条餐食记录？`)) return;
    try {
      await deleteMeal(meal.meal_id);
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  };

  const removeReading = async (meal: MealRecord, readingId: string) => {
    try {
      await deleteGlucose(meal.meal_id, readingId);
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
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

  const closeDialog = () => {
    setLogOpen(false);
    setEditing(null);
  };

  const dialog = (
    <>
      <MealLogDialog
        open={logOpen || editing !== null}
        mealId={editing?.meal_id ?? null}
        initial={editInitial}
        title={editing ? "编辑这顿记录" : "手动记一顿"}
        dismissLabel="取消"
        onClose={closeDialog}
        onSaved={(meal) => {
          setSaved(`${formatEatenAt(meal.eaten_at)} ${meal.meal_type} · ${foodsText(meal)}`);
          void refresh();
        }}
      />
      <AuthDialog
        open={authMode !== null}
        initialMode={authMode ?? "login"}
        onClose={() => setAuthMode(null)}
      />
    </>
  );

  return (
    <div
      ref={embedded ? scrollRef : undefined}
      className={embedded ? "health-file-content" : "app-scroll"}
      onScroll={embedded ? onScroll : undefined}
    >
      <div className={embedded ? "health-file-body" : "page-body"}>
        <section className="profile-block" id={embedded ? "health-basics" : undefined}>
          <div className="profile-block-head">
            <h2>基础信息</h2>
            <div className="pf-bmi-inline">
              <span>BMI</span>
              {bmi == null ? (
                <em>填完身高体重后自动计算</em>
              ) : (
                <>
                  <strong>{bmi.toFixed(1)}</strong>
                  <b className={bmiLevel === "正常" ? "is-ok" : ""}>{bmiLevel}</b>
                </>
              )}
            </div>
          </div>

          <div className="pf-fields">
            <label className="pf-field">
              <span>身高</span>
              <div className="pf-box">
                <input
                  inputMode="decimal"
                  placeholder="172"
                  value={profile.height}
                  onChange={(e) => setProfile({ ...profile, height: e.target.value })}
                />
                <em>cm</em>
              </div>
            </label>
            <label className="pf-field">
              <span>体重</span>
              <div className="pf-box">
                <input
                  inputMode="decimal"
                  placeholder="68"
                  value={profile.weight}
                  onChange={(e) => setProfile({ ...profile, weight: e.target.value })}
                />
                <em>kg</em>
              </div>
            </label>
            <label className="pf-field">
              <span>年龄</span>
              <div className="pf-box">
                <input
                  inputMode="numeric"
                  placeholder="45"
                  value={profile.age}
                  onChange={(e) => setProfile({ ...profile, age: e.target.value })}
                />
                <em>岁</em>
              </div>
            </label>
            <label className="pf-field">
              <span>日常活动量</span>
              <div className="pf-box">
                <select
                  value={profile.activity}
                  onChange={(e) =>
                    setProfile({ ...profile, activity: e.target.value as Profile["activity"] })
                  }
                >
                  <option>久坐</option>
                  <option>轻度活动</option>
                  <option>规律运动</option>
                </select>
                <svg
                  className="pf-chevron"
                  width="10"
                  height="10"
                  viewBox="0 0 12 12"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="1.4"
                  aria-hidden="true"
                >
                  <path d="m3 4.5 3 3 3-3" />
                </svg>
              </div>
            </label>
          </div>

          <p className="profile-caption">
            中国成人 BMI 切点：&lt;18.5 偏低 · 18.5–23.9 正常 · 24–27.9 偏重 · ≥28 肥胖。数据只保存在本机浏览器；控糖方案以医生或营养师的评估为准。
          </p>
        </section>

        {embedded ? (
          <div className="health-file-section-head" id="health-records">
            <span>02 / 餐食记录</span>
            <button
              type="button"
              className="profile-add"
              disabled={transportKind !== "live"}
              onClick={() => setLogOpen(true)}
            >
              <svg width="11" height="11" viewBox="0 0 12 12" aria-hidden="true">
                <path d="M6 1.5v9M1.5 6h9" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
              </svg>
              手动记一顿
            </button>
          </div>
        ) : (
          <div className="profile-tabs">
            <div className="profile-tab-group">
              <button
                type="button"
                className={`profile-tab${tab === "records" ? " is-active" : ""}`}
                onClick={() => setTab("records")}
              >
                餐食记录<span>{meals.length}</span>
              </button>
              <button
                type="button"
                className={`profile-tab${tab === "trend" ? " is-active" : ""}`}
                onClick={() => setTab("trend")}
              >
                趋势
              </button>
            </div>
            <button
              type="button"
              className="profile-add"
              disabled={transportKind !== "live"}
              onClick={() => setLogOpen(true)}
            >
              <svg width="11" height="11" viewBox="0 0 12 12" aria-hidden="true">
                <path d="M6 1.5v9M1.5 6h9" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
              </svg>
              手动记一顿
            </button>
          </div>
        )}

        {error ? <Banner status="error" title="操作失败" description={error} /> : null}
        {saved ? <Banner status="success" title="已保存到健康档案" description={saved} /> : null}
        {transportKind === "offline" ? (
          <Banner status="warning" title="后端未连接" description="连接后端后才能查看和新增餐食记录；启动后端后点「重新连接」。" />
        ) : null}
        {transportKind === "unauthorized" ? (
          <Banner
            status="warning"
            title="登录已过期"
            description="重新登录后才能查看和新增这个账号的餐食记录。"
            endContent={<Button label="重新登录" variant="secondary" size="sm" onClick={() => setAuthMode("login")} />}
          />
        ) : null}
        {loadFailed ? (
          <Banner
            status="error"
            title="餐食记录没读到"
            description={
              noData
                ? "后端连接正常但记录接口返回失败，餐食记录与趋势暂时显示不了。"
                : "后端连接正常但记录接口返回失败，下面显示的不一定是全部记录。"
            }
            endContent={<Button label="重试" variant="secondary" size="sm" onClick={() => void refresh()} />}
          />
        ) : null}

        {(embedded || tab === "records") && !noData ? (
          <div className="meal-filters">
            <div className="meal-filter-chips">
              {(["全部", "早餐", "午餐", "晚餐", "加餐"] as const).map((label) => (
                <button
                  key={label}
                  type="button"
                  className={`meal-chip${mealFilter === label ? " is-active" : ""}`}
                  onClick={() => setMealFilter(label)}
                >
                  {label}
                </button>
              ))}
            </div>
            <input
              className="field-input meal-search"
              placeholder="搜索食物或备注"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
            />
            <span className="meal-filter-count">
              {filteredMeals.length} / {meals.length} 条
            </span>
          </div>
        ) : null}

        {embedded || tab === "records" ? (
          <>
            {noData ? null : meals.length === 0 ? (
              <div className="profile-empty">
                <EmptyState
                  title="还没有餐食记录"
                  description="拍照识别后点“记下来”，或在这里手动记一顿。记录会作为下次提问的个人记忆。"
                />
              </div>
            ) : filteredMeals.length === 0 ? (
              <div className="profile-empty">
                <EmptyState
                  title="没有符合条件的记录"
                  description="换个关键词，或把餐次切回“全部”再找。"
                  actions={
                    <Button
                      label="清空筛选"
                      variant="secondary"
                      size="sm"
                      onClick={() => {
                        setMealFilter("全部");
                        setQuery("");
                      }}
                    />
                  }
                />
              </div>
            ) : (
              <div className="meal-record-list">
                {filteredMeals.map((meal) => (
                  <div className="meal-record" key={meal.meal_id}>
                    <div className="meal-record-time">
                      <strong>{formatEatenAt(meal.eaten_at).slice(5, 10)}</strong>
                      <span>{formatEatenAt(meal.eaten_at).slice(11)} · {meal.meal_type}</span>
                    </div>
                    <div className="meal-record-main">
                      <strong>{foodsText(meal)}</strong>
                      <small>
                        {carbsText(meal)}
                        {meal.gl != null ? ` · GL 约 ${meal.gl}` : ""}
                        {` · ${{ photo: "拍照记录", chat: "对话记录", manual: "手动记录" }[meal.source]}`}
                        {meal.note ? ` · ${meal.note}` : ""}
                      </small>
                      <div className="meal-record-readings">
                        {meal.readings.length === 0 ? (
                          <Text size="2xs" color="secondary">未记录血糖</Text>
                        ) : (
                          meal.readings.map((r) => (
                            <span className="reading-chip" key={r.reading_id}>
                              {glucoseTiming(r.minutes_after)} {r.value_mmol.toFixed(1)}
                              <button
                                type="button"
                                aria-label="删除这条血糖"
                                onClick={() => void removeReading(meal, r.reading_id)}
                              >
                                ×
                              </button>
                            </span>
                          ))
                        )}
                      </div>
                      {glucoseFor === meal.meal_id ? (
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
                          <Button label="保存" variant="primary" size="sm" onClick={() => void saveGlucose(meal)} />
                          <Button label="取消" variant="ghost" size="sm" onClick={() => setGlucoseFor(null)} />
                        </div>
                      ) : null}
                    </div>
                    <div className="meal-record-actions">
                      <button type="button" className="row-action" onClick={() => setEditing(meal)}>
                        编辑
                      </button>
                      <button
                        type="button"
                        className="row-action"
                        onClick={() => {
                          setGlucoseFor(meal.meal_id);
                          setGlucoseValue("");
                          setGlucoseMinutes(120);
                        }}
                      >
                        补血糖
                      </button>
                      <button type="button" className="row-action row-action--danger" onClick={() => void removeMeal(meal)}>
                        删除
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </>
        ) : null}

        {embedded ? (
          <div className="health-file-section-head" id="health-trend">
            <span>03 / 健康趋势</span>
            <span className="health-file-section-meta">可选 6 小时 – 全部</span>
          </div>
        ) : null}

        {(embedded || tab === "trend") && !noData ? <HealthTrends meals={meals} /> : null}
      </div>

      {embedded ? createPortal(dialog, document.body) : dialog}
    </div>
  );
}
