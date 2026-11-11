/**
 * ChatPage：SSE 流式会话 + 断言引用 + 证据卡侧栏 + 断点放行。
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Banner, Button, Card, Stack, TextArea, Text } from "@astryxdesign/core";
import { useRuns, type RunState } from "../store/runs";
import { DeliverableView } from "../components/DeliverableView";
import { AgentFeedback, ExecutionCard, EXECUTION_ICON, RunStatus } from "../components/AgentActivity";
import { MODALITY_META } from "../components/EvidenceCard";
import { MealCard } from "../components/MealCard";
import { MealLogDialog, formatEatenAt, localNow, mealTypeFor } from "../components/MealLogDialog";
import { AnswerChart } from "../components/MealCharts";
import { BrandMark } from "../components/BrandMark";
import HealthFileCard from "../components/HealthFileCard";
import { VoiceInputButton } from "../components/VoiceInputButton";
import { analyzeFood, listMeals } from "../api/client";
import {
  CHANNEL_LABELS,
  type Evidence,
  type FoodAnalysis,
  type FoodItem,
  type MealDraft,
  type MealRecord,
} from "../types";

const DEMO_QUESTIONS = [
  "一碗米饭大概多少碳水？",
  "米饭和馒头的升糖负荷哪个更高？",
  "血糖高的时候可以多吃哪些低 GI 主食？",
  "我该打多少单位胰岛素？",
];

// 明确“我吃了/这顿”才在消息下给记录按钮；单纯问食物知识不打扰
const EATING_INTENT = /(我(刚|刚刚|刚才)?(吃|喝)了|我在吃|这顿(吃|喝)|早餐吃|午餐吃|晚餐吃|加餐吃)/;

/** 最近 6 小时内的血糖读数才算“当前血糖”，更早的只能算历史记录 */
interface RecentGlucose {
  value: number;
  minutesAgo: number;
}

function latestGlucose(meals: MealRecord[], withinHours = 6): RecentGlucose | null {
  const cutoff = Date.now() - withinHours * 3600 * 1000;
  let latest: { t: number; value: number } | null = null;
  for (const meal of meals) {
    for (const reading of meal.readings) {
      const t = Date.parse(reading.measured_at);
      if (Number.isNaN(t) || t < cutoff) continue;
      if (!latest || t > latest.t) latest = { t, value: reading.value_mmol };
    }
  }
  if (!latest) return null;
  return {
    value: latest.value,
    minutesAgo: Math.max(0, Math.round((Date.now() - latest.t) / 60000)),
  };
}

/** 只发照片没打字时，用识别结果生成“这餐怎么吃”的评估问题 */
function photoQuestion(items: FoodItem[], glucose: RecentGlucose | null): string {
  const foods = items
    .map((item) => `${item.name} 约${Math.round((item.grams_low + item.grams_high) / 2)}g`)
    .join("、");
  const glucoseLine = glucose
    ? `我最近一次血糖是 ${glucose.value.toFixed(1)} mmol/L（${glucose.minutesAgo} 分钟前）。`
    : "";
  return `我刚拍了这餐：${foods}。我之前吃过这些吗？${glucoseLine}这餐现在适合我吃吗？如果不太合适，怎么调整更稳？`;
}

const ICON_PROPS = {
  width: 15,
  height: 15,
  viewBox: "0 0 24 24",
  fill: "none",
  stroke: "currentColor",
  strokeWidth: 2,
  strokeLinecap: "round" as const,
  strokeLinejoin: "round" as const,
  "aria-hidden": true,
};

const CAMERA_ICON = (
  <svg {...ICON_PROPS} width={22} height={22}>
    <path d="M23 19a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4l2-3h6l2 3h4a2 2 0 0 1 2 2z" />
    <circle cx="12" cy="13" r="4" />
  </svg>
);

const SEND_ICON = (
  <svg {...ICON_PROPS}>
    <path d="M22 2L11 13" />
    <path d="M22 2l-7 20-4-9-9-4 20-7z" />
  </svg>
);

const FILE_ICON = (
  <svg {...ICON_PROPS} width={22} height={22}>
    <path d="M6 3h9l4 4v14H6z" />
    <path d="M15 3v4h4" />
    <path d="M9 12h6M9 16h4" />
  </svg>
);

/** 拍照识别后的食物清单 → 记录弹窗的初始值（取区间中值，仍可在弹窗里改） */
function mealDraftFromItems(items: FoodItem[], imageId?: string | null): Partial<MealDraft> {
  return {
    eaten_at: localNow(),
    meal_type: mealTypeFor(),
    foods: items.map((item) => ({
      name: item.name,
      grams: Math.round((item.grams_low + item.grams_high) / 2),
      carbs_g: Math.round(((item.carbs_g_low + item.carbs_g_high) / 2) * 10) / 10,
    })),
    note: "",
    source: "photo",
    image_id: imageId ?? null,
    insulin_note: "",
  };
}

/** 单次运行（一条消息） */
function RunMessage({
  run,
  activeEvidenceId,
  onCiteClick,
  onLogMeal,
  onViewTrace,
  traceOpen,
  logged,
  meals,
}: {
  run: RunState;
  activeEvidenceId: string | null;
  onCiteClick: (id: string, run: RunState) => void;
  onLogMeal: (run: RunState) => void;
  onViewTrace: (run: RunState) => void;
  traceOpen: boolean;
  logged: boolean;
  meals: MealRecord[];
}) {
  const { approveRun } = useRuns();

  const viewTrace = () => onViewTrace(run);

  const hasMeal = Boolean(run.food);

  return (
    <div className="run-message">
      <div className="user-block">
        <div className="user-question">
          {run.question}
          {run.source === "mock" ? <span className="user-mock">（mock）</span> : null}
        </div>
        {!hasMeal && EATING_INTENT.test(run.question) ? (
          <div className="user-actions">
            <Button
              label={logged ? "已记录" : "记录"}
              variant="secondary"
              size="sm"
              isDisabled={logged}
              onClick={() => onLogMeal(run)}
            />
          </div>
        ) : null}
      </div>

      <RunStatus run={run} onOpen={viewTrace} open={traceOpen} />

      <div className="assistant-block">
        <div className="assistant-head">
          <div className="assistant-avatar">
            <BrandMark size={15} />
          </div>
          <div className="assistant-who">
            <strong>Glucoguard</strong>
            <small>{run.phase === "streaming" ? "正在分析…" : "慢病控糖膳食助手"}</small>
          </div>
        </div>

        <div className="answer-card">
          <Stack gap={4}>
            <AgentFeedback run={run} />
            {run.food ? (
              <section className="answer-meal">
                <MealCard food={run.food} run={run} />
                <div className="meal-actions">
                  <Button
                    label={logged ? "已记录" : "记录"}
                    variant="secondary"
                    size="sm"
                    isDisabled={logged}
                    onClick={() => onLogMeal(run)}
                  />
                  <Text size="2xs" color="secondary">
                    记下来，下次提问会先查这顿饭
                  </Text>
                </div>
              </section>
            ) : null}

            {run.guard && !run.guard.allowed ? (
              <Banner
                status="error"
                title="输入被安全策略拦截"
                description={run.guard.reason ?? undefined}
              />
            ) : null}

            {run.error ? <Banner status="error" title="执行出错" description={run.error} /> : null}

            {run.phase === "interrupted" ? (
              <Banner
                status="warning"
                title="流程在人工断点暂停"
                description="审校连续打回、打回轮数已用尽，图在 Writer 前挂起，等待人工放行后输出兜底结论。"
                endContent={
                  <Button
                    label="一键放行"
                    variant="primary"
                    size="sm"
                    isLoading={run.approving}
                    isDisabled={run.approving}
                    onClick={() => void approveRun(run.key)}
                  />
                }
              />
            ) : null}

            {run.deliverable ? (
              <DeliverableView
                deliverable={run.deliverable}
                activeEvidenceId={activeEvidenceId}
                onCiteClick={(id) => onCiteClick(id, run)}
              />
            ) : null}

            {run.deliverable && !run.deliverable.refused ? (
              <AnswerChart question={run.question} meals={meals} />
            ) : null}
          </Stack>
        </div>
      </div>
    </div>
  );
}

function CitationPanel({
  id,
  evidence,
  onClose,
}: {
  id: string;
  evidence: Evidence;
  onClose: () => void;
}) {
  const s = evidence.source;
  const path = s.file_path ?? evidence.doc_id;
  const isUrl = /^https?:\/\//.test(path);
  const where = [
    s.section ? (/^\d+$/.test(s.section) ? `第${s.section}段` : s.section) : "",
    s.page != null ? `第${s.page}页` : "",
    s.time_code ?? "",
  ]
    .filter(Boolean)
    .join(" · ");
  // 按段落和句末标点分条展示，长段落才有“文件行”的阅读节奏；不改动原文任何字符
  const lines = evidence.quote
    .split(/\n+/)
    .flatMap((para) => para.split(/(?<=[。！？；])/))
    .map((line) => line.trim())
    .filter(Boolean);

  return (
    <aside className="cite-panel" aria-label="引用来源">
      <div className="cite-head">
        <span className="cite-head-title">引用来源</span>
        <span className="cite-head-id">[{id}]</span>
        <button type="button" className="cite-close" aria-label="收起引用" onClick={onClose}>
          <svg viewBox="0 0 16 16" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden="true">
            <path d="m6 3 5 5-5 5" />
          </svg>
        </button>
      </div>
      <div className="cite-path">
        <div className="cite-path-row">
          <svg
            className="cite-path-icon"
            viewBox="0 0 16 16"
            width="13"
            height="13"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.3"
            aria-hidden="true"
          >
            <path d="M4.5 1.75h4.6L12.5 5v9.25h-8z" />
            <path d="M9 1.75V5h3.5" />
          </svg>
          <span className="cite-path-name" title={path}>
            {path}
          </span>
          {isUrl ? (
            <a
              className="cite-path-open"
              href={path}
              target="_blank"
              rel="noreferrer"
              aria-label="打开原文"
            >
              <svg viewBox="0 0 16 16" width="12" height="12" fill="none" stroke="currentColor" strokeWidth="1.4" aria-hidden="true">
                <path d="M6.5 3.5h-3v9h9V9.5" />
                <path d="M9 2.5h4.5V7" />
                <path d="M13.5 2.5 7.5 8.5" />
              </svg>
            </a>
          ) : null}
        </div>
        <div className="cite-path-meta">
          <span>{CHANNEL_LABELS[evidence.channel ?? "local"]}</span>
          <span>{MODALITY_META[s.modality]?.label ?? "文本"}</span>
          {where ? <span>{where}</span> : null}
        </div>
      </div>
      <div className="cite-lines">
        {lines.map((line, i) => (
          <div
            key={i}
            className={`cite-line${i === 0 && s.section && line === s.section ? " is-heading" : " is-quoted"}`}
          >
            <span className="cite-ln">{i + 1}</span>
            <span className="cite-text">{line}</span>
          </div>
        ))}
      </div>
    </aside>
  );
}

export default function ChatPage() {
  const { runs, startRun, transportKind, activeSessionId } = useRuns();
  const [input, setInput] = useState("");
  const [selected, setSelected] = useState<{ id: string; evidence: Evidence } | null>(null);
  const [traceKey, setTraceKey] = useState<string | null>(null);
  const [executionOpen, setExecutionOpen] = useState(false);
  const executionTriggerRef = useRef<HTMLButtonElement | null>(null);
  const dismissedExecutions = useRef(new Set<string>());
  const [file, setFile] = useState<File | null>(null);
  const [food, setFood] = useState<FoodAnalysis | null>(null);
  const [foodItems, setFoodItems] = useState<FoodItem[]>([]);
  const [analyzing, setAnalyzing] = useState(false);
  const [foodError, setFoodError] = useState<string | null>(null);
  const [logOpen, setLogOpen] = useState(false);
  const [logInitial, setLogInitial] = useState<Partial<MealDraft> | null>(null);
  const [logRunKey, setLogRunKey] = useState<string | null>(null);
  const [loggedRunKeys, setLoggedRunKeys] = useState<string[]>([]);
  const [savedMeal, setSavedMeal] = useState<MealRecord | null>(null);
  const [meals, setMeals] = useState<MealRecord[]>([]);
  const [voiceError, setVoiceError] = useState<string | null>(null);
  const [fileOpen, setFileOpen] = useState(false);
  const bottomRef = useRef<HTMLDivElement | null>(null);
  const fileRef = useRef<HTMLInputElement | null>(null);
  const fileTriggerRef = useRef<HTMLButtonElement | null>(null);
  // 多次选择/移除照片时，旧请求的识别结果不能覆盖新状态
  const uploadSeq = useRef(0);
  const previewUrl = useMemo(() => (file ? URL.createObjectURL(file) : null), [file]);
  // 只渲染当前会话的问答；左侧历史点开另一段会话时整列切换
  const threadRuns = useMemo(
    () => runs.filter((r) => r.sessionId === activeSessionId),
    [runs, activeSessionId],
  );

  useEffect(() => {
    return () => {
      if (previewUrl) URL.revokeObjectURL(previewUrl);
    };
  }, [previewUrl]);

  const latestRun = threadRuns.at(-1);
  const runningKey = latestRun?.phase === "streaming" ? latestRun.key : null;

  useEffect(() => {
    setSelected(null);
    setTraceKey(null);
    setExecutionOpen(false);
  }, [activeSessionId]);

  useEffect(() => {
    if (!runningKey || dismissedExecutions.current.has(runningKey)) return;
    setTraceKey(runningKey);
    setExecutionOpen(true);
    setFileOpen(false);
  }, [runningKey, activeSessionId]);

  const closeExecution = useCallback(() => {
    const key = traceKey ?? latestRun?.key;
    if (key) dismissedExecutions.current.add(key);
    setExecutionOpen(false);
  }, [traceKey, latestRun?.key]);

  const refreshMeals = useCallback(async () => {
    if (transportKind !== "live") return;
    try {
      setMeals(await listMeals(100));
    } catch {
      // 图表拿不到数据不影响问答本身
    }
  }, [transportKind]);

  useEffect(() => {
    void refreshMeals();
  }, [refreshMeals]);

  const handleCiteClick = useCallback((id: string, run: RunState) => {
    const evidence =
      run.evidencePool?.[id] ??
      run.deliverable?.citations.find((ev) => ev.evidence_id === id) ??
      null;
    if (!evidence) return;
    setExecutionOpen(false);
    dismissedExecutions.current.add(run.key);
    setSelected((cur) => (cur?.id === id ? null : { id, evidence }));
  }, []);

  const handleViewTrace = useCallback((run: RunState) => {
    if (executionOpen && (traceKey ?? latestRun?.key) === run.key) {
      closeExecution();
      return;
    }
    setSelected(null);
    setFileOpen(false);
    setTraceKey(run.key);
    setExecutionOpen(true);
  }, [closeExecution, executionOpen, traceKey, latestRun?.key]);

  const traceRun = threadRuns.find((r) => r.key === traceKey) ?? latestRun ?? null;

  /** 记录按钮不再自动弹窗：用户点哪条消息的“记录”，就带哪条的识别结果 */
  const openLogForRun = useCallback((run: RunState) => {
    setLogRunKey(run.key);
    setLogInitial(
      run.food
        ? mealDraftFromItems(run.food.food_items, run.food.image_id)
        : {
            eaten_at: localNow(),
            meal_type: mealTypeFor(),
            foods: [],
            note: run.question,
            source: "chat",
            image_id: null,
            insulin_note: "",
          },
    );
    setLogOpen(true);
  }, []);

  const clearPhoto = useCallback(() => {
    uploadSeq.current += 1;
    setAnalyzing(false);
    setFile(null);
    setFood(null);
    setFoodItems([]);
    setFoodError(null);
  }, []);

  const handleFile = useCallback(async (files: File | File[] | null) => {
    const picked = Array.isArray(files) ? (files[0] ?? null) : files;
    const seq = ++uploadSeq.current;
    setFile(picked);
    setFood(null);
    setFoodItems([]);
    setFoodError(null);
    if (!picked) return;
    if (picked.size > 8 * 1024 * 1024) {
      setFoodError("照片超过 8MB，请压缩后再试");
      return;
    }
    setAnalyzing(true);
    try {
      const analysis = await analyzeFood(picked);
      if (seq !== uploadSeq.current) return;
      setFood(analysis);
      setFoodItems(analysis.items);
      if (analysis.degraded) {
        setFoodError(analysis.notes || "自动识别不可用，请手动录入餐食");
      }
    } catch (err) {
      if (seq !== uploadSeq.current) return;
      setFoodError(err instanceof Error ? err.message : String(err));
    } finally {
      if (seq === uploadSeq.current) setAnalyzing(false);
    }
  }, []);

  const totalCarbs = useMemo(
    () =>
      foodItems.reduce(
        (acc, item) => ({
          low: acc.low + item.carbs_g_low,
          high: acc.high + item.carbs_g_high,
        }),
        { low: 0, high: 0 },
      ),
    [foodItems],
  );

  const send = useCallback(async () => {
    if (analyzing) return;
    const typed = input.trim();
    const hasFood = Boolean(food && foodItems.length > 0);
    if (!typed && !hasFood) return;
    // 引用面板留着，方便对照着追问；手动点「收起」才关闭
    setTraceKey(null);
    setSavedMeal(null);
    // 只发了照片没打字：用识别结果生成“这餐怎么吃”的评估问题
    let question = typed;
    if (!question && food) {
      let glucose: RecentGlucose | null = null;
      try {
        glucose = latestGlucose(await listMeals(30));
      } catch {
        // 记录读不到就不带血糖，评估照常进行
      }
      question = photoQuestion(foodItems, glucose);
    }
    // 发送后 previewUrl 会被回收，消息里用独立 object URL
    const photoUrl = file ? URL.createObjectURL(file) : null;
    startRun(
      question,
      food
        ? { image_id: food.image_id, food_items: foodItems, photo_url: photoUrl }
        : undefined,
    );
    setInput("");
    clearPhoto();
  }, [analyzing, clearPhoto, file, food, foodItems, input, startRun]);

  useEffect(() => {
    // 可选调用：无头/极老环境无 scrollIntoView 也不崩
    bottomRef.current?.scrollIntoView?.({ behavior: "smooth", block: "end" });
  }, [
    threadRuns.length,
    threadRuns[threadRuns.length - 1]?.nodeEvents.length,
    threadRuns[threadRuns.length - 1]?.phase,
  ]);

  return (
    <div className="chat-page page-fill">
      <div className={`chat-column${threadRuns.length === 0 ? " is-idle" : ""}`}>
        <div className="chat-scroll">
          <Stack gap={4} padding={4} maxWidth={760} style={{ margin: "0 auto", width: "100%" }}>
            {threadRuns.length === 0 ? (
              <div className="hero">
                <h1>欢迎记录您的健康！</h1>
                <Stack direction="horizontal" gap={2} wrap="wrap">
                  {DEMO_QUESTIONS.map((q) => (
                    <Button key={q} label={q} variant="secondary" size="sm" onClick={() => startRun(q)} />
                  ))}
                </Stack>
              </div>
            ) : (
              threadRuns.map((run) => (
                <RunMessage
                  key={run.key}
                  run={run}
                  activeEvidenceId={selected?.id ?? null}
                  onCiteClick={handleCiteClick}
                  onLogMeal={openLogForRun}
                  onViewTrace={handleViewTrace}
                  traceOpen={executionOpen && traceRun?.key === run.key}
                  logged={loggedRunKeys.includes(run.key)}
                  meals={meals}
                />
              ))
            )}
            <div ref={bottomRef} />
          </Stack>
      </div>

      <div className="composer-shell">
        <Card padding={2} className="chat-composer">
          <Stack gap={2}>
          {file ? (
            <div className="attach-pill">
              {previewUrl ? (
                <img className="attach-thumb" src={previewUrl} alt="餐盘照片预览" />
              ) : null}
              <div className="attach-copy">
                <div className="attach-title">
                  {analyzing
                    ? "正在识别餐盘…"
                    : food && foodItems.length > 0
                      ? `餐盘照片 · ${foodItems.length} 样`
                      : "餐盘照片"}
                </div>
                <div className="attach-sub">
                  {analyzing
                    ? "识别中，完成后即可发送，也可以继续补充文字"
                    : food && foodItems.length > 0
                      ? `合计碳水 ${totalCarbs.low.toFixed(1)}–${totalCarbs.high.toFixed(1)} g · 发送后在会话里记录`
                      : foodError
                        ? "识别未完成，可重试或移除"
                        : "可直接发送，也可以继续补充文字"}
                </div>
              </div>
              <Button label="移除照片" variant="ghost" size="sm" onClick={clearPhoto} />
            </div>
          ) : null}

          {foodError ? (
            <Banner status="warning" title="餐食识别" description={foodError} />
          ) : null}

          <div className="composer-row">
            <input
              ref={fileRef}
              type="file"
              accept="image/jpeg,image/png,image/webp"
              className="composer-file"
              onChange={(e) => {
                const picked = e.target.files?.[0] ?? null;
                e.target.value = "";
                void handleFile(picked);
              }}
            />
            <div className="composer-tool">
              <VoiceInputButton value={input} onChange={setInput} onError={setVoiceError} />
              <Button
                label={file ? "更换餐盘" : "上传餐盘"}
                variant="ghost"
                size="sm"
                icon={CAMERA_ICON}
                isIconOnly
                isLoading={analyzing}
                isDisabled={transportKind !== "live"}
                tooltip={
                  transportKind === "live"
                    ? file
                      ? "更换餐盘照片"
                      : "拍照 / 上传餐盘"
                    : "连接后端后才能识别照片"
                }
                onClick={() => fileRef.current?.click()}
              />
            </div>
            <div className="composer-input">
              <TextArea
                label="问题"
                isLabelHidden
                placeholder="输入问题，或补充烹饪方式、血糖…"
                value={input}
                rows={1}
                onChange={setInput}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !e.shiftKey) {
                    e.preventDefault();
                    void send();
                  }
                }}
              />
            </div>
            <div className="composer-action">
              <Button
                label="发送"
                variant="primary"
                size="sm"
                icon={SEND_ICON}
                isIconOnly
                tooltip="发送"
                isDisabled={analyzing || (!input.trim() && !(food && foodItems.length > 0))}
                onClick={() => void send()}
              />
            </div>
          </div>
          {voiceError ? <div className="composer-voice-error">{voiceError}</div> : null}
        </Stack>
      </Card>
        <div className="composer-note">
          Enter 发送 · Shift+Enter 换行
          {food && foodItems.length > 0 ? " · 将附带餐盘识别结果" : ""}
          {savedMeal
            ? ` · 已记入健康档案：${formatEatenAt(savedMeal.eaten_at)} ${savedMeal.meal_type}`
            : ""}
          {transportKind === "mock" ? " · 当前为 Mock 模式（后端不可达或 VITE_MOCK=1）" : ""}
        </div>
      </div>
      </div>
      <button
        ref={fileTriggerRef}
        type="button"
        className="health-file-trigger"
        aria-label={fileOpen ? "收起健康档案" : "展开健康档案"}
        aria-controls="health-file-card"
        aria-expanded={fileOpen}
        title={fileOpen ? "收起健康档案" : "健康档案"}
        onClick={() => {
          setFileOpen((value) => !value);
          closeExecution();
        }}
      >
        {FILE_ICON}
      </button>
      <HealthFileCard
        open={fileOpen}
        onClose={() => setFileOpen(false)}
        anchorRef={fileTriggerRef}
      />
      {selected ? (
        <CitationPanel
          id={selected.id}
          evidence={selected.evidence}
          onClose={() => setSelected(null)}
        />
      ) : null}
      <Button
        ref={executionTriggerRef}
        className={`execution-trigger${latestRun?.phase === "streaming" ? " is-running" : ""}`}
        label={executionOpen ? "收起执行过程" : "展开执行过程"}
        variant={executionOpen ? "secondary" : "ghost"}
        isIconOnly
        icon={EXECUTION_ICON}
        aria-controls="execution-card"
        aria-expanded={executionOpen}
        onClick={() => {
          if (executionOpen) closeExecution();
          else {
            setExecutionOpen(true);
            setFileOpen(false);
            setSelected(null);
          }
        }}
      />
      {executionOpen ? <ExecutionCard run={traceRun} onClose={closeExecution} anchorRef={executionTriggerRef} /> : null}
      <MealLogDialog
        open={logOpen}
        initial={logInitial}
        onClose={() => setLogOpen(false)}
        onSaved={(meal) => {
          setSavedMeal(meal);
          void refreshMeals();
          if (logRunKey) {
            setLoggedRunKeys((prev) =>
              prev.includes(logRunKey) ? prev : [...prev, logRunKey],
            );
          }
        }}
      />
    </div>
  );
}
