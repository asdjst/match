/**
 * 健康档案：基础信息 + 健康趋势。
 * 基础信息只存浏览器；餐食记录统一在「饮食日记」本书里管理，这里只为趋势读取记录。
 */
import { useCallback, useEffect, useMemo, useState, type RefObject } from "react";
import { createPortal } from "react-dom";
import { Banner, Button } from "@astryxdesign/core";
import { listMeals } from "../api/client";
import { AuthDialog } from "../components/AuthDialog";
import HealthTrends from "../components/HealthTrends";
import { useAuth } from "../store/auth";
import { useRuns } from "../store/runs";
import type { MealRecord } from "../types";

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
  const [meals, setMeals] = useState<MealRecord[]>([]);
  const [loadFailed, setLoadFailed] = useState(false);

  useEffect(() => {
    try {
      localStorage.setItem(KEY, JSON.stringify(profile));
    } catch {
      // 隐私模式下写入失败不影响填写
    }
  }, [profile]);

  const refresh = useCallback(async () => {
    try {
      setMeals(await listMeals(100));
      setLoadFailed(false);
    } catch {
      // 读不到 ≠ 没有记录：保留旧数据并显式报错，别把空档案当成事实
      setLoadFailed(true);
    }
  }, []);

  // 换账号或重连都先清掉手上这份记录：不能让上一个人的数据留在屏幕上
  useEffect(() => {
    setMeals([]);
    setLoadFailed(false);
    if (transportKind === "live") void refresh();
  }, [account?.user_id, transportKind, refresh]);

  // 读失败且手上没有任何记录：不渲染空态，免得把故障说成空档案
  const noData = loadFailed && meals.length === 0;

  const height = Number(profile.height);
  const weight = Number(profile.weight);
  const bmi = useMemo(() => {
    if (!height || !weight || height < 80 || weight < 20) return null;
    return weight / (height / 100) ** 2;
  }, [height, weight]);
  const bmiLevel =
    bmi == null ? null : bmi < 18.5 ? "偏低" : bmi < 24 ? "正常" : bmi < 28 ? "偏重" : "肥胖";

  const authDialog = (
    <AuthDialog
      open={authMode !== null}
      initialMode={authMode ?? "login"}
      onClose={() => setAuthMode(null)}
    />
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

        {transportKind === "offline" ? (
          <Banner status="warning" title="后端未连接" description="连接后端后才能查看健康趋势；启动后端后点「重新连接」。" />
        ) : null}
        {transportKind === "unauthorized" ? (
          <Banner
            status="warning"
            title="登录已过期"
            description="重新登录后才能查看这个账号的健康趋势。"
            endContent={<Button label="重新登录" variant="secondary" size="sm" onClick={() => setAuthMode("login")} />}
          />
        ) : null}
        {loadFailed ? (
          <Banner
            status="error"
            title="餐食记录没读到"
            description={
              noData
                ? "后端连接正常但记录接口返回失败，健康趋势暂时显示不了。"
                : "后端连接正常但记录接口返回失败，下面显示的不一定是全部记录。"
            }
            endContent={<Button label="重试" variant="secondary" size="sm" onClick={() => void refresh()} />}
          />
        ) : null}

        {embedded ? (
          <div className="health-file-section-head" id="health-trend">
            <span>02 / 健康趋势</span>
            <span className="health-file-section-meta">可选 6 小时 – 全部</span>
          </div>
        ) : null}

        {!noData ? <HealthTrends meals={meals} /> : null}
      </div>

      {embedded ? createPortal(authDialog, document.body) : authDialog}
    </div>
  );
}
