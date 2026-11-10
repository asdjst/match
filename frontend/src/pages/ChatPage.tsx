/**
 * ChatPage：SSE 流式会话 + 断言引用 + 证据卡侧栏 + 断点放行。
 */
import { useCallback, useEffect, useRef, useState } from "react";
import {
  Badge,
  Banner,
  Button,
  Card,
  Collapsible,
  EmptyState,
  Spinner,
  Stack,
  StatusDot,
  TextArea,
  Text,
} from "@astryxdesign/core";
import { useRuns, type RunState } from "../store/runs";
import { useUi } from "../store/ui";
import { DeliverableView } from "../components/DeliverableView";
import { CHANNEL_META, EvidenceCard } from "../components/EvidenceCard";
import { CHANNEL_LABELS, NODE_LABELS, type Channel, type Evidence, type GraphNodeName } from "../types";

const DEMO_QUESTIONS = [
  "2024年公司营业收入是多少？",
  "2024年营业收入相比2023年增长了多少？",
  "量子力学的薛定谔方程怎么推导？",
  "2024年和2023年的毛利率相比怎么样？顺带预测2025年毛利率走势。",
];

/** 交付物引用按渠道计数（本地库 / Web / 云端网盘） */
function countChannels(citations: Evidence[]): Record<Channel, number> {
  const counts: Record<Channel, number> = { local: 0, web: 0, cloud: 0 };
  for (const ev of citations) {
    if (ev.channel && ev.channel in counts) counts[ev.channel] += 1;
  }
  return counts;
}

/** 单次运行（一条消息） */
function RunMessage({
  run,
  activeEvidenceId,
  onCiteClick,
}: {
  run: RunState;
  activeEvidenceId: string | null;
  onCiteClick: (id: string) => void;
}) {
  const { approveRun, setActiveRunKey } = useRuns();
  const { setPage } = useUi();

  const citations = run.deliverable?.citations ?? [];
  const dist = countChannels(citations);

  const viewTrace = () => {
    setActiveRunKey(run.key);
    setPage("trace");
  };

  return (
    <Card padding={4} variant="default">
      <Stack gap={3}>
        <Stack direction="horizontal" gap={2} vAlign="center" wrap="wrap">
          <StatusDot variant="accent" label="提问" />
          <Text weight="semibold" size="base">
            {run.question}
          </Text>
          {run.source === "mock" ? (
            <Text size="2xs" color="secondary">
              （mock）
            </Text>
          ) : null}
          {run.phase !== "streaming" ? (
            <Button label="查看轨迹" variant="ghost" size="sm" onClick={viewTrace} />
          ) : null}
        </Stack>

        {run.phase === "streaming" ? (
          <Stack direction="horizontal" gap={2} vAlign="center" wrap="wrap">
            <Spinner size="sm" label="执行中" />
            {run.nodeEvents.length === 0 ? (
              <Text size="sm" color="secondary">
                正在启动多智能体流水线…
              </Text>
            ) : (
              run.nodeEvents.map((e, i) => (
                <Text key={i} size="sm" color="secondary">
                  {NODE_LABELS[e.node as GraphNodeName] ?? e.node} ✓
                </Text>
              ))
            )}
          </Stack>
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
            onCiteClick={onCiteClick}
          />
        ) : null}

        {citations.length > 0 ? (
          <Collapsible
            defaultIsOpen
            trigger={
              <Stack direction="horizontal" gap={2} vAlign="center" wrap="wrap">
                <Text size="sm" weight="semibold">
                  引用来源 {citations.length}
                </Text>
                {(Object.keys(CHANNEL_LABELS) as Channel[])
                  .filter((ch) => dist[ch] > 0)
                  .map((ch) => (
                    <Badge
                      key={ch}
                      variant={CHANNEL_META[ch].badgeVariant}
                      label={`${CHANNEL_LABELS[ch]} ${dist[ch]}`}
                    />
                  ))}
              </Stack>
            }
          >
            <Stack gap={2} style={{ paddingTop: "var(--spacing-2)" }}>
              {citations.map((ev) => (
                <EvidenceCard
                  key={ev.evidence_id}
                  evidence={ev}
                  highlighted={activeEvidenceId === ev.evidence_id}
                  onClick={() => onCiteClick(ev.evidence_id)}
                />
              ))}
            </Stack>
          </Collapsible>
        ) : null}
      </Stack>
    </Card>
  );
}

export default function ChatPage() {
  const { runs, startRun, transportKind } = useRuns();
  const [input, setInput] = useState("");
  const [activeEvidenceId, setActiveEvidenceId] = useState<string | null>(null);
  const bottomRef = useRef<HTMLDivElement | null>(null);

  const handleCiteClick = useCallback((id: string) => {
    setActiveEvidenceId((cur) => (cur === id ? null : id));
  }, []);

  const send = useCallback(() => {
    const q = input.trim();
    if (!q) return;
    setActiveEvidenceId(null);
    startRun(q);
    setInput("");
  }, [input, startRun]);

  useEffect(() => {
    // 可选调用：无头/极老环境无 scrollIntoView 也不崩
    bottomRef.current?.scrollIntoView?.({ behavior: "smooth", block: "end" });
  }, [runs.length, runs[runs.length - 1]?.nodeEvents.length]);

  return (
    <div className="chat-column page-fill">
      <div className="chat-scroll">
          <Stack gap={4} padding={4} maxWidth={1040} style={{ margin: "0 auto", width: "100%" }}>
            {runs.length === 0 ? (
              <EmptyState
                title="向多智能体 RAG 提问"
                description="五角色流水线（规划 → 检索 → 计算 → 分析 → 审校 → 交付）产出带引用的结论；检索覆盖本地库、Web 与云端网盘三通道，知识库外问题会拒答。"
                actions={
                  <Stack direction="horizontal" gap={2} wrap="wrap">
                    {DEMO_QUESTIONS.map((q) => (
                      <Button key={q} label={q} variant="secondary" size="sm" onClick={() => startRun(q)} />
                    ))}
                  </Stack>
                }
              />
            ) : (
              runs.map((run) => (
                <RunMessage
                  key={run.key}
                  run={run}
                  activeEvidenceId={activeEvidenceId}
                  onCiteClick={handleCiteClick}
                />
              ))
            )}
            <div ref={bottomRef} />
          </Stack>
      </div>

      <Card padding={3} className="chat-composer">
        <Stack direction="horizontal" gap={3} vAlign="end">
          <Stack direction="vertical" gap={1} style={{ flex: 1 }}>
            <TextArea
              label="问题"
              isLabelHidden
              placeholder="输入问题，例如：2024年公司营业收入是多少？"
              value={input}
              rows={2}
              onChange={setInput}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  send();
                }
              }}
            />
            <Text size="2xs" color="secondary">
              Enter 发送 · Shift+Enter 换行
              {transportKind === "mock" ? " · 当前为 Mock 模式（后端不可达或 VITE_MOCK=1）" : ""}
            </Text>
          </Stack>
          <Button label="发送" variant="primary" isDisabled={!input.trim()} onClick={send} />
        </Stack>
      </Card>
    </div>
  );
}
