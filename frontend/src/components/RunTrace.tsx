/**
 * 会话内联执行轨迹：问题下方一条可折叠的时间线，
 * 流式时逐节点点亮并计时，完成后收成一行，完整细节去合规审计页。
 */
import { useEffect, useRef, useState } from "react";
import type { RunState } from "../store/runs";
import type { GraphNodeName } from "../types";
import { buildSteps, type Step } from "./ThinkingTimeline";

const STEP_LABEL: Record<GraphNodeName, string> = {
  planner: "规划任务",
  retriever: "检索取证",
  executor: "工具计算",
  analyst: "分析断言",
  critic: "审校核验",
  writer: "生成交付",
};

const STATUS_TEXT: Record<Step["status"], string> = {
  done: "已完成",
  running: "进行中",
  pending: "待执行",
  skipped: "已跳过",
  waiting: "等待放行",
};

function useTick(active: boolean) {
  const [, setTick] = useState(0);
  useEffect(() => {
    if (!active) return;
    const timer = window.setInterval(() => setTick((n) => n + 1), 1000);
    return () => window.clearInterval(timer);
  }, [active]);
}

function durationText(step: Step): string {
  if (step.status === "running") return "进行中";
  if (step.status === "skipped") return "跳过";
  if (step.status === "waiting") return "待放行";
  if (step.status === "pending") return "";
  return step.durationMs > 0 ? `${(step.durationMs / 1000).toFixed(1)}s` : "";
}

function StatusIcon({ status }: { status: Step["status"] }) {
  if (status === "done") {
    return (
      <span className="rt-icon is-done" aria-hidden="true">
        <svg viewBox="0 0 16 16">
          <path d="M3.2 8.4l3 3.1 6.6-7.2" />
        </svg>
      </span>
    );
  }
  if (status === "running") {
    return (
      <span className="rt-icon is-running" aria-hidden="true">
        <span className="rt-pulse" />
      </span>
    );
  }
  if (status === "waiting") return <span className="rt-icon is-waiting" aria-hidden="true" />;
  if (status === "skipped") return <span className="rt-icon is-skipped" aria-hidden="true" />;
  return <span className="rt-icon is-pending" aria-hidden="true" />;
}

export function RunTrace({ run }: { run: RunState }) {
  const streaming = run.phase === "streaming";
  useTick(streaming);

  const [open, setOpen] = useState(streaming);
  const prevPhase = useRef(run.phase);
  useEffect(() => {
    // 跑完自动收起，把版面让给结论；用户仍可点开回看
    if (prevPhase.current === "streaming" && run.phase !== "streaming") setOpen(false);
    prevPhase.current = run.phase;
  }, [run.phase]);

  const steps = buildSteps(run);
  const running = steps.find((s) => s.status === "running");
  const hasEvents = run.nodeEvents.length > 0;
  const elapsed = Math.max(0, ((run.finishedAt ?? Date.now()) - run.startedAt) / 1000);
  const timeText = streaming
    ? `${Math.floor(elapsed)}s`
    : hasEvents
      ? `${elapsed.toFixed(1)}s`
      : "历史记录";

  const title =
    run.phase === "streaming"
      ? "正在执行中"
      : run.phase === "interrupted"
        ? "等待人工放行"
        : run.phase === "error"
          ? "执行出错"
          : "已完成分析";

  // 只列出已经发生（或正在发生）的步骤，待执行的不占版面
  const visible = steps.filter((s) => s.status !== "pending");
  const rounds = run.roundNo ?? 0;

  return (
    <div className={`run-trace is-${run.phase}${open ? " is-open" : ""}`}>
      <button
        type="button"
        className="run-trace-head"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
      >
        <span className="run-trace-state">
          {streaming ? (
            <span className="rt-spinner" aria-hidden="true" />
          ) : run.phase === "done" ? (
            <StatusIcon status="done" />
          ) : run.phase === "interrupted" ? (
            <StatusIcon status="waiting" />
          ) : (
            <span className="rt-icon is-error" aria-hidden="true" />
          )}
          <span className="run-trace-title">{title}</span>
          <span className="run-trace-time">{timeText}</span>
          {!open && streaming && running ? (
            <span className="run-trace-now">· {STEP_LABEL[running.node]}…</span>
          ) : null}
        </span>
        <svg className="run-trace-chevron" viewBox="0 0 16 16" aria-hidden="true">
          <path d="M4 6l4 4 4-4" />
        </svg>
      </button>

      {open ? (
        <div className="run-trace-body">
          {visible.length > 0 ? (
            <div className="rt-steps">
              {visible.map((step) => (
                <div key={step.node} className={`rt-step is-${step.status}`}>
                  <StatusIcon status={step.status} />
                  <div className="rt-copy">
                    <div className="rt-line">
                      <span className="rt-name">{STEP_LABEL[step.node]}</span>
                      {step.count > 1 ? <span className="rt-rep">×{step.count}</span> : null}
                      <span className="rt-dur">{durationText(step)}</span>
                    </div>
                    <div className="rt-detail">
                      {step.detail ?? (step.status === "running" ? "正在处理…" : STATUS_TEXT[step.status])}
                    </div>
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <div className="rt-waiting">正在启动任务图…</div>
          )}

          <div className="rt-foot">
            <span>
              {rounds > 0 ? `审校打回 ${rounds} 次 · ` : ""}
              {visible.length} 个步骤
            </span>
          </div>
        </div>
      ) : null}
    </div>
  );
}

/** 右侧轨迹面板：不动页面，原地展开这条运行的六角色执行细节 */
export function RunTracePanel({ run, onClose }: { run: RunState; onClose: () => void }) {
  const steps = buildSteps(run);
  const visible = steps.filter((s) => s.status !== "pending");
  const rounds = run.roundNo ?? 0;
  const elapsed = Math.max(0, ((run.finishedAt ?? Date.now()) - run.startedAt) / 1000);
  const timeText = run.nodeEvents.length > 0 ? `${elapsed.toFixed(1)} 秒` : "历史记录";
  const statusText =
    run.phase === "streaming"
      ? "进行中"
      : run.phase === "interrupted"
        ? "等待放行"
        : run.phase === "error"
          ? "执行出错"
          : "已完成";

  return (
    <aside className="cite-panel trace-panel" aria-label="执行轨迹">
      <div className="cite-head">
        <span className="cite-head-title">执行轨迹</span>
        <span className={`trace-panel-state is-${run.phase}`}>{statusText}</span>
        <button type="button" className="cite-close" aria-label="收起轨迹" onClick={onClose}>
          <svg viewBox="0 0 16 16" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden="true">
            <path d="m6 3 5 5-5 5" />
          </svg>
        </button>
      </div>

      <div className="trace-panel-meta">
        <span>{timeText}</span>
        <span>{visible.length} 个步骤</span>
        {rounds > 0 ? <span>审校打回 {rounds} 次</span> : null}
      </div>

      <div className="trace-panel-body">
        {visible.length > 0 ? (
          <div className="rt-steps">
            {visible.map((step) => (
              <div key={step.node} className={`rt-step is-${step.status}`}>
                <StatusIcon status={step.status} />
                <div className="rt-copy">
                  <div className="rt-line">
                    <span className="rt-name">{STEP_LABEL[step.node]}</span>
                    {step.count > 1 ? <span className="rt-rep">×{step.count}</span> : null}
                    <span className="rt-dur">{durationText(step)}</span>
                  </div>
                  <div className="rt-detail">
                    {step.detail ?? (step.status === "running" ? "正在处理…" : STATUS_TEXT[step.status])}
                  </div>
                </div>
              </div>
            ))}
          </div>
        ) : (
          <div className="rt-waiting">正在启动任务图…</div>
        )}
      </div>
    </aside>
  );
}
