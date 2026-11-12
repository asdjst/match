import { useEffect, useLayoutEffect, useRef, useState, type RefObject } from "react";
import { Button, Card, Stack, Text } from "@astryxdesign/core";
import type { RunState } from "../store/runs";
import type { GraphNodeName } from "../types";
import { buildSteps, executionEntries, isGraphNode, RUNNING_HINT, STEP_LABEL } from "./ThinkingTimeline";

const NODE_CODE: Record<GraphNodeName, string> = {
  planner: "PLANNER", retriever: "RETRIEVER", executor: "EXECUTOR",
  analyst: "ANALYST", critic: "CRITIC", writer: "WRITER",
};

function clock(ms: number): string {
  const s = Math.max(0, ms) / 1000;
  const m = Math.floor(s / 60);
  const rest = s - m * 60;
  return m > 0 ? `${m}:${rest.toFixed(1).padStart(4, "0")}` : rest.toFixed(1).padStart(4, "0");
}

function useTick(active: boolean): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!active) return;
    const id = window.setInterval(() => setNow(Date.now()), 100);
    return () => window.clearInterval(id);
  }, [active]);
  return now;
}

export const EXECUTION_ICON = (
  <svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <rect x="3" y="3" width="6" height="6" rx="2" />
    <rect x="15" y="15" width="6" height="6" rx="2" />
    <path d="M6 9v6a3 3 0 0 0 3 3h6M15 5h5m-2.5-2.5v5" />
  </svg>
);
const CLOSE_ICON = <svg viewBox="0 0 20 20" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden="true"><path d="m5 8 5 5 5-5" /></svg>;

function stateTitle(run: RunState): string {
  if (run.approving) return "正在恢复执行";
  if (run.phase === "streaming") return "正在执行中";
  if (run.phase === "interrupted") return "等待人工放行";
  if (run.phase === "error") return "执行出错";
  if (run.deliverable?.refused) return "已停止 · 安全限制";
  if (run.deliverable?.degraded) return "已完成 · 降级回答";
  return "执行已完成";
}

export function AgentFeedback({ run }: { run: RunState }) {
  const entries = executionEntries(run);
  if (!entries.length && run.phase !== "streaming") return null;
  return (
    <Stack as="section" className="agent-feedback" gap={2} aria-live="polite" aria-label="智能体反馈">
      {entries.length ? <Stack as="ol" className="agent-feedback-list" gap={2}>
        {entries.map((entry, index) => <Stack as="li" key={entry.key} className="agent-feedback-row" direction="horizontal" gap={2}>
          <Text className="agent-feedback-index" size="2xs" hasTabularNumbers>{String(index + 1).padStart(2, "0")}</Text>
          <Stack gap={0} className="agent-feedback-copy">
            <Text size="2xs" color="secondary">{STEP_LABEL[entry.node]}{entry.count > 1 ? ` · 第 ${entry.count} 次` : ""} · 已完成</Text>
            <Text size="sm">{entry.summary ?? "这一步已处理完成。"}</Text>
          </Stack>
        </Stack>)}
      </Stack> : <Text size="sm" color="secondary">已收到，正在准备执行；每完成一步都会在这里保留进展。</Text>}
    </Stack>
  );
}

export function ExecutionCard({ run, onClose, anchorRef }: {
  run: RunState | null;
  onClose: () => void;
  anchorRef: RefObject<HTMLButtonElement | null>;
}) {
  const panelRef = useRef<HTMLElement | null>(null);
  const focusRef = useRef<HTMLElement | null>(null);
  const live = run?.phase === "streaming" || Boolean(run?.approving);
  const active = run?.activeNode && isGraphNode(run.activeNode) ? run.activeNode : run?.approving ? "writer" : null;
  const entries = run ? executionEntries(run) : [];
  const latest = entries.at(-1);
  const focusKey = `${run?.key}:${active}:${entries.length}:${run?.phase}:${run?.approving}`;

  useLayoutEffect(() => {
    const panel = panelRef.current;
    const parent = panel?.parentElement;
    const composer = parent?.querySelector(".composer-shell");
    if (!panel || !parent || !composer) return;
    const place = () => {
      const gap = parseFloat(getComputedStyle(document.documentElement).fontSize) * 0.75;
      const bottom = Math.max(gap, parent.getBoundingClientRect().bottom - composer.getBoundingClientRect().top + gap);
      panel.style.setProperty("--execution-bottom", `${bottom}px`);
    };
    place();
    const observer = new ResizeObserver(place);
    observer.observe(parent);
    observer.observe(composer);
    return () => observer.disconnect();
  }, []);

  useLayoutEffect(() => {
    const element = focusRef.current;
    if (!element || window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    const animation = element.animate(
      [{ opacity: 0, transform: "translateY(.6rem) scale(.98)" }, { opacity: 1, transform: "translateY(0) scale(1)" }],
      { duration: 380, easing: "cubic-bezier(.2,.7,.2,1)" },
    );
    return () => animation.cancel();
  }, [focusKey]);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== "Escape" || document.querySelector(".meal-dialog-backdrop")) return;
      event.preventDefault();
      onClose();
      anchorRef.current?.focus({ preventScroll: true });
    };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [onClose, anchorRef]);

  const close = () => {
    onClose();
    anchorRef.current?.focus({ preventScroll: true });
  };
  const steps = run ? buildSteps(run) : [];
  const elapsed = run ? Math.max(0, ((run.finishedAt ?? Date.now()) - run.startedAt) / 1000) : 0;
  const now = useTick(live);
  const activeIndex = active ? steps.findIndex((step) => step.node === active) : -1;
  const stepNo = activeIndex >= 0 ? activeIndex + 1 : Math.min(entries.length + 1, steps.length || 6);
  const nodeMs = run ? now - (run.activeNodeAt ?? run.startedAt) : 0;
  const totalMs = run ? now - run.startedAt : 0;
  return (
    <Stack as="aside" ref={panelRef} id="execution-card" className={`execution-card${live ? " is-live" : ""}`} aria-label={live ? "当前执行步骤" : "执行过程"}>
      <Card padding={0} className="execution-card-surface">
        <Button className="execution-close" label="收起执行卡片" variant="ghost" isIconOnly icon={CLOSE_ICON} onClick={close} />
        {!run ? <Stack className="execution-card-scroll" padding={4}>
          <Text size="sm" color="secondary">发送一个问题后，这里会自动聚焦正在工作的智能体。</Text>
        </Stack> : live ? <Stack ref={focusRef} className="exec-hud" gap={2} padding={3}>
          <Stack direction="horizontal" gap={2} align="center" className="exec-hud-row">
            <svg className="exec-hud-core" viewBox="0 0 24 24" width="20" height="20" aria-hidden="true">
              <circle cx="12" cy="12" r="9" className="exec-hud-core-ring" />
              <path d="M12 3a9 9 0 0 1 9 9" className="exec-hud-core-sweep" />
              <circle cx="12" cy="12" r="2.4" className="exec-hud-core-dot" />
            </svg>
            <Stack gap={0} className="exec-hud-main">
              <Text size="sm" weight="semibold" className="exec-hud-label">{active ? STEP_LABEL[active] : latest ? "交接下一步" : "准备任务"}</Text>
              <Text size="2xs" className="exec-hud-code" hasTabularNumbers>
                {`${active ? NODE_CODE[active] : "HANDOFF"} · ${String(stepNo).padStart(2, "0")}/${String(steps.length || 6).padStart(2, "0")} · R${(run.roundNo ?? 0) + 1}`}
              </Text>
            </Stack>
            <Stack gap={0} hAlign="end" className="exec-hud-clock">
              <Text size="sm" className="exec-hud-timer" hasTabularNumbers>{`${clock(nodeMs)}s`}</Text>
              <Text size="2xs" className="exec-hud-total" hasTabularNumbers>{`TOTAL ${clock(totalMs)}s`}</Text>
            </Stack>
          </Stack>
          <Stack direction="horizontal" gap={1} className="exec-hud-track" aria-label="各智能体进度">
            {steps.map((step) => <Text key={step.node} className={`exec-hud-seg is-${step.status}`} aria-label={STEP_LABEL[step.node]}> </Text>)}
          </Stack>
          <Text size="2xs" color="secondary" className="exec-hud-hint">
            {active ? RUNNING_HINT[active] : "正在交接给下一个智能体。"}
          </Text>
        </Stack> : <Stack className="execution-card-scroll" gap={4} padding={4}>
          <Stack ref={focusRef} className={`execution-result is-${run.phase}`} gap={1}>
            <Text size="sm" weight="semibold">{stateTitle(run)}</Text>
            <Text size="sm" color="secondary">{run.error ?? (run.phase === "interrupted" ? "请在对话中确认是否放行；已完成的步骤保留在下方。" : run.deliverable?.refusal_reason ?? run.deliverable?.degraded_reason ?? `已记录 ${entries.length} 次步骤执行${elapsed > 0 ? ` · 共 ${elapsed.toFixed(1)}s` : ""}`)}</Text>
          </Stack>
          {entries.length ? <Stack as="ol" className="execution-history" gap={0} aria-label="完整执行过程">
            {entries.map((entry, index) => <Stack as="li" key={entry.key} className="execution-history-row" direction="horizontal" gap={3}>
              <Text className="execution-history-index" size="2xs" hasTabularNumbers>{String(index + 1).padStart(2, "0")}</Text>
              <Stack gap={1} className="execution-history-copy">
                <Stack direction="horizontal" hAlign="between" gap={2}>
                  <Text size="sm" weight="semibold">{STEP_LABEL[entry.node]}{entry.count > 1 ? ` · 第 ${entry.count} 次` : ""}</Text>
                  {entry.durationMs > 0 ? <Text size="2xs" color="secondary" hasTabularNumbers>{(entry.durationMs / 1000).toFixed(1)}s</Text> : null}
                </Stack>
                <Text size="sm" color="secondary">{entry.summary ?? "这一步已处理完成。"}</Text>
              </Stack>
            </Stack>)}
          </Stack> : <Text size="sm" color="secondary">没有已完成的智能体步骤。</Text>}
          {steps.some((step) => step.status === "skipped") ? <Text size="2xs" color="secondary">本次无需工具计算，该步骤未执行。</Text> : null}
        </Stack>}
      </Card>
    </Stack>
  );
}
