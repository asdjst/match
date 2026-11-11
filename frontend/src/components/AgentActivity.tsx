import { useEffect, useLayoutEffect, useRef, useState, type RefObject } from "react";
import { Button, Card, Stack, Text } from "@astryxdesign/core";
import type { RunState } from "../store/runs";
import { buildSteps, executionEntries, isGraphNode, STEP_LABEL } from "./ThinkingTimeline";

export const EXECUTION_ICON = (
  <svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <rect x="3" y="3" width="6" height="6" rx="2" />
    <rect x="15" y="15" width="6" height="6" rx="2" />
    <path d="M6 9v6a3 3 0 0 0 3 3h6M15 5h5m-2.5-2.5v5" />
  </svg>
);
const CLOSE_ICON = <svg viewBox="0 0 20 20" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden="true"><path d="m5 8 5 5 5-5" /></svg>;

function useTick(active: boolean) {
  const [, setTick] = useState(0);
  useEffect(() => {
    if (!active) return;
    const timer = window.setInterval(() => setTick((n) => n + 1), 1000);
    return () => window.clearInterval(timer);
  }, [active]);
}

function stateTitle(run: RunState): string {
  if (run.approving) return "正在恢复执行";
  if (run.phase === "streaming") return "正在执行中";
  if (run.phase === "interrupted") return "等待人工放行";
  if (run.phase === "error") return "执行出错";
  if (run.deliverable?.refused) return "已停止 · 安全限制";
  if (run.deliverable?.degraded) return "已完成 · 降级回答";
  return "执行已完成";
}

export function RunStatus({ run, onOpen, open }: { run: RunState; onOpen: () => void; open: boolean }) {
  useTick(run.phase === "streaming");
  const elapsed = Math.max(0, ((run.finishedAt ?? Date.now()) - run.startedAt) / 1000);
  const node = run.activeNode && isGraphNode(run.activeNode) ? run.activeNode : null;
  return (
    <Button className={`run-status-bar is-${run.phase}`} label={stateTitle(run)} variant="ghost" width="100%" aria-controls="execution-card" aria-expanded={open} onClick={onOpen}>
      <Stack direction="horizontal" gap={2} vAlign="center" width="100%">
        <Text className={`execution-dot is-${run.phase}`} aria-hidden="true">●</Text>
        <Text size="sm" weight="semibold">{stateTitle(run)}</Text>
        <Text size="2xs" color="secondary" hasTabularNumbers>{run.phase === "streaming" ? `${Math.floor(elapsed)}s` : elapsed > 0 ? `${elapsed.toFixed(1)}s` : "历史记录"}</Text>
        {node && run.phase === "streaming" ? <Text className="execution-current-name" size="2xs" color="secondary" maxLines={1}>{STEP_LABEL[node]}</Text> : null}
        <Text className="execution-bar-action" size="2xs" color="secondary">{open ? "收起" : "展开"}</Text>
      </Stack>
    </Button>
  );
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
  return (
    <Stack as="aside" ref={panelRef} id="execution-card" className={`execution-card${live ? " is-live" : ""}`} aria-label={live ? "当前执行步骤" : "执行过程"}>
      <Card padding={0} className="execution-card-surface">
        <Button className="execution-close" label="收起执行卡片" variant="ghost" isIconOnly icon={CLOSE_ICON} onClick={close} />
        {!run ? <Stack className="execution-card-scroll" padding={4}>
          <Text size="sm" color="secondary">发送一个问题后，这里会自动聚焦正在工作的智能体。</Text>
        </Stack> : live ? <Stack className="execution-active" gap={2} hAlign="center" padding={4}>
          <Stack direction="horizontal" gap={1} className="execution-segments" aria-label="各智能体进度">
            {steps.map((step) => <Text key={step.node} className={`execution-segment is-${step.status}`} aria-label={STEP_LABEL[step.node]}> </Text>)}
          </Stack>
          <svg className="execution-flow-arrow" viewBox="0 0 32 56" width="32" height="56" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            <path className="execution-flow-dashes" d="M16 4v36" strokeDasharray="7 7" />
            <path className="execution-flow-head" d="m8 33 8 9 8-9" />
            <circle className="execution-flow-spark" cx="16" cy="6" r="2.8" fill="currentColor" stroke="none" />
          </svg>
          <Stack ref={focusRef} className="execution-focus" hAlign="center" vAlign="center" padding={3}>
            <Text as="h3" size="lg" weight="semibold" className="execution-focus-label">{active ? STEP_LABEL[active] : latest ? "交接下一步" : "准备任务"}</Text>
          </Stack>
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
