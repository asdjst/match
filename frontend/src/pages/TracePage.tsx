/**
 * TracePage：React Flow 六角色 DAG + 节点/证据联动。
 * 节点显示 status 与耗时，边按执行顺序流动；点击节点或证据 chip 高亮证据原文。
 * 详情栏按角色展示该阶段产出：规划→任务图、检索→检索词与取证、计算→工具入参出参、
 * 分析→断言、审校→结论与问题、交付→置信度与最终断言。
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Badge,
  Button,
  Card,
  EmptyState,
  Heading,
  MetadataList,
  MetadataListItem,
  Selector,
  Stack,
  Table,
  Text,
  pixel,
  proportional,
  type TableColumn,
} from "@astryxdesign/core";
import { FlowDag, resultsForGraphNode, ROLE_LABELS } from "../components/FlowDag";
import { EvidenceCard } from "../components/EvidenceCard";
import {
  CHANNEL_LABELS,
  NODE_LABELS,
  type Assertion,
  type Channel,
  type Evidence,
  type GraphNodeName,
} from "../types";
import { useRuns, type RunState } from "../store/runs";
import { useUi } from "../store/ui";

const DEMO_TRACES = [
  "2024年公司营业收入是多少？",
  "2024年和2023年的毛利率相比怎么样？顺带预测2025年毛利率走势。",
];

const CHANNEL_BADGE: Record<Channel, { variant: "neutral" | "info" | "success"; label: string }> = {
  local: { variant: "neutral", label: CHANNEL_LABELS.local },
  web: { variant: "info", label: CHANNEL_LABELS.web },
  cloud: { variant: "success", label: CHANNEL_LABELS.cloud },
};

const PHASE_META = {
  streaming: { variant: "info", label: "执行中" },
  done: { variant: "success", label: "已完成" },
  interrupted: { variant: "warning", label: "等待放行" },
  error: { variant: "error", label: "执行出错" },
} as const;

interface RetrievalRow {
  key: string;
  node_id: string;
  query: string;
  channel: string;
  hits: number;
  latency_ms: number;
  status: string;
  sample: string;
  [k: string]: unknown;
}

function statusMeta(status: string): { variant: "success" | "neutral" | "warning"; label: string } {
  if (status === "ok") return { variant: "success", label: "正常" };
  if (status === "未配置") return { variant: "neutral", label: "未配置" };
  if (status === "超时") return { variant: "warning", label: "超时" };
  return { variant: "warning", label: "失败" };
}

function channelCounts(pool: Record<string, Evidence> | null | undefined): Record<Channel, number> {
  const counts: Record<Channel, number> = { local: 0, web: 0, cloud: 0 };
  for (const ev of Object.values(pool ?? {})) {
    if (ev.channel && ev.channel in counts) counts[ev.channel] += 1;
  }
  return counts;
}

/** 逐检索节点 × 通道展开检索记录，并挂上该通道的一条代表证据 */
function buildRetrievalRows(run: RunState): RetrievalRow[] {
  const specs: Array<{ node_id: string; query: string | null }> =
    run.dag?.nodes.filter((n) => n.role === "retriever") ?? [];
  const results = resultsForGraphNode("retriever", run.nodeResults, run.dag);
  const targets =
    specs.length > 0
      ? specs
      : results.map((r, i) => ({ node_id: r.node_id || `r${i + 1}`, query: run.question }));
  const pool = run.evidencePool ?? {};
  return targets.flatMap((spec, i) => {
    const res = results[i];
    return (res?.retrievals ?? []).map((rec) => {
      const evId = (res?.evidence_used ?? []).find((id) => pool[id]?.channel === rec.channel);
      const ev = evId ? pool[evId] : undefined;
      return {
        key: `${spec.node_id}-${rec.channel}`,
        node_id: spec.node_id,
        query: spec.query || run.question,
        channel: rec.channel,
        hits: rec.hits,
        latency_ms: rec.latency_ms,
        status: rec.status,
        sample: ev ? `${ev.evidence_id} · ${ev.source.file_path ?? ev.doc_id}` : "—",
      };
    });
  });
}

const RETRIEVAL_COLUMNS: TableColumn<RetrievalRow>[] = [
  {
    key: "node_id",
    header: "节点",
    width: pixel(64),
    renderCell: (r) => <Badge variant="neutral" label={String(r.node_id)} />,
  },
  {
    key: "query",
    header: "检索词",
    width: proportional(2, { minWidth: 140 }),
    renderCell: (r) => (
      <Text size="sm" maxLines={1}>
        {String(r.query)}
      </Text>
    ),
  },
  {
    key: "channel",
    header: "通道",
    width: pixel(96),
    renderCell: (r) => {
      const meta = CHANNEL_BADGE[r.channel as Channel];
      return <Badge variant={meta?.variant ?? "neutral"} label={meta?.label ?? String(r.channel)} />;
    },
  },
  {
    key: "hits",
    header: "命中",
    width: pixel(56),
    align: "end",
    renderCell: (r) => (
      <Text size="sm" hasTabularNumbers>
        {String(r.hits)}
      </Text>
    ),
  },
  {
    key: "latency_ms",
    header: "耗时",
    width: pixel(76),
    align: "end",
    renderCell: (r) => (
      <Text size="sm" color="secondary" hasTabularNumbers>
        {`${r.latency_ms}ms`}
      </Text>
    ),
  },
  {
    key: "status",
    header: "状态",
    width: pixel(84),
    renderCell: (r) => {
      const meta = statusMeta(String(r.status));
      return <Badge variant={meta.variant} label={meta.label} />;
    },
  },
  {
    key: "sample",
    header: "代表证据",
    width: proportional(2, { minWidth: 160 }),
    renderCell: (r) => (
      <Text size="2xs" color="secondary" maxLines={1}>
        {String(r.sample)}
      </Text>
    ),
  },
];

function RunOverview({ run }: { run: RunState }) {
  const counts = channelCounts(run.evidencePool);
  const totalEvidence = counts.local + counts.web + counts.cloud;
  const d = run.deliverable;
  const totalMs = (run.finishedAt ?? Date.now()) - run.startedAt;
  const hasSideEvents = run.nodeEvents.length > 0;
  const phase = PHASE_META[run.phase];

  return (
    <Card padding={4}>
      <Stack gap={3}>
        <Stack direction="horizontal" gap={2} vAlign="center" wrap="wrap">
          <Badge variant={phase.variant} label={phase.label} />
          {run.source === "mock" ? <Badge variant="neutral" label="Mock" /> : null}
          <Text size="2xs" color="secondary">
            {run.runId ?? "run_id 未就绪"}
          </Text>
        </Stack>
        <Heading level={3}>{run.question}</Heading>
        <MetadataList orientation="horizontal">
          <MetadataListItem label="总耗时">
            {hasSideEvents ? `${(totalMs / 1000).toFixed(1)}s` : "—"}
          </MetadataListItem>
          <MetadataListItem label="审校轮次">
            {run.roundNo != null ? `第 ${run.roundNo} 轮` : "—"}
          </MetadataListItem>
          <MetadataListItem label="证据池">{totalEvidence} 条</MetadataListItem>
          <MetadataListItem label="交付引用">{d?.citations.length ?? 0} 条</MetadataListItem>
          <MetadataListItem label="置信度">
            {d
              ? `${Math.round(d.confidence * 100)}%${d.confidence_source === "llm" ? " · 模型评分" : d.confidence_source === "formula" ? " · 公式兜底" : ""}`
              : "—"}
          </MetadataListItem>
        </MetadataList>
      </Stack>
    </Card>
  );
}

function RetrievalPanel({ run }: { run: RunState }) {
  const rows = buildRetrievalRows(run);
  const counts = channelCounts(run.evidencePool);
  const totalEvidence = counts.local + counts.web + counts.cloud;

  return (
    <Card padding={4}>
      <Stack gap={3}>
        <Stack direction="horizontal" gap={3} vAlign="start" hAlign="between" wrap="wrap">
          <Stack gap={1}>
            <Text weight="semibold">三通道检索</Text>
            <Text size="2xs" color="secondary">
              本地 R2R · Web（DuckDuckGo）· 云端网盘（Google Drive）并行取证，逐节点记录命中、耗时与状态
            </Text>
          </Stack>
          <Stack direction="horizontal" gap={2} vAlign="center" wrap="wrap">
            {(Object.keys(CHANNEL_BADGE) as Channel[]).map((ch) => (
              <Badge
                key={ch}
                variant={CHANNEL_BADGE[ch].variant}
                label={`${CHANNEL_BADGE[ch].label} ${counts[ch]}`}
              />
            ))}
          </Stack>
        </Stack>

        {rows.length > 0 ? (
          <Table
            data={rows}
            columns={RETRIEVAL_COLUMNS}
            density="compact"
            dividers="rows"
            hasHover
            textOverflow="truncate"
          />
        ) : (
          <Text size="sm" color="secondary">
            本问还没有检索记录。
          </Text>
        )}

        <Text size="2xs" color="secondary">
          证据池合计 {totalEvidence} 条 · 交付物引用 {run.deliverable?.citations.length ?? 0} 条
        </Text>
      </Stack>
    </Card>
  );
}

/** 某节点用到的证据编号：node_results.evidence_used（r1/x1 前缀聚合），缺省回退交付物引用 */
function evidenceForNode(run: RunState, node: string | null): Set<string> {
  if (!node) return new Set();
  const used = resultsForGraphNode(node as GraphNodeName, run.nodeResults, run.dag).flatMap(
    (r) => r.evidence_used ?? [],
  );
  if (used.length > 0) return new Set(used);
  if (node === "writer" || node === "analyst") {
    return new Set(run.deliverable?.citations.map((c) => c.evidence_id) ?? []);
  }
  return new Set();
}

function AssertionsSection({ title, assertions }: { title: string; assertions: Assertion[] }) {
  return (
    <Stack gap={1}>
      <Text size="sm" weight="semibold" color="secondary">
        {title}
      </Text>
      {assertions.map((a, i) => (
        <Text key={i} size="sm" color="secondary">
          {i + 1}. {a.text}
          {a.cites.length ? ` [${a.cites.join("][")}]` : ""}
          {a.inferred ? "（推断）" : ""}
        </Text>
      ))}
    </Stack>
  );
}

/** 按角色渲染该阶段的产出（"规划的情况是什么"就在这里回答） */
function StageSection({ run, node }: { run: RunState; node: GraphNodeName }) {
  const dagNodes = run.dag?.nodes ?? [];
  const hasDag = dagNodes.length > 0;

  switch (node) {
    case "planner": {
      if (!hasDag) {
        return (
          <Text size="sm" color="secondary">
            任务图未就绪（快照未返回 dag）。
          </Text>
        );
      }
      return (
        <Stack gap={2}>
          <Text size="sm" weight="semibold" color="secondary">
            本问规划出的任务图（{dagNodes.length} 个节点）
          </Text>
          {dagNodes.map((spec) => (
            <Card key={spec.node_id} padding={3}>
              <Stack gap={1}>
                <Stack direction="horizontal" gap={2} vAlign="center" wrap="wrap">
                  <Badge variant="neutral" label={`[${spec.node_id}]`} />
                  <Text size="sm" weight="medium">
                    {ROLE_LABELS[spec.role]}
                  </Text>
                  {spec.tool ? (
                    <Text size="2xs" color="secondary">
                      工具：{spec.tool}
                    </Text>
                  ) : null}
                  {spec.depends_on.length > 0 ? (
                    <Text size="2xs" color="secondary">
                      依赖：{spec.depends_on.join("、")}
                    </Text>
                  ) : null}
                </Stack>
                {spec.instruction ? (
                  <Text size="sm" color="secondary">
                    指令：{spec.instruction}
                  </Text>
                ) : null}
                {spec.query ? (
                  <Text size="sm" color="secondary">
                    检索词：{spec.query}
                  </Text>
                ) : null}
              </Stack>
            </Card>
          ))}
        </Stack>
      );
    }
    case "retriever": {
      const specs = dagNodes.filter((n) => n.role === "retriever");
      const results = resultsForGraphNode("retriever", run.nodeResults, run.dag);
      const totalIds = new Set(results.flatMap((r) => r.evidence_used ?? []));
      return (
        <Stack gap={2}>
          <Text size="sm" weight="semibold" color="secondary">
            检索执行情况（渠道明细见上方「三通道检索」表）
          </Text>
          {specs.map((spec, i) => (
            <Stack key={spec.node_id} gap={1}>
              <Text size="sm" color="secondary">
                检索词：{spec.query || run.question}
              </Text>
              <Text size="sm" color="secondary">
                取证：{results[i]?.evidence_used?.length ?? 0} 条进入证据池
              </Text>
            </Stack>
          ))}
          {!hasDag && results.length > 0 ? (
            <Text size="sm" color="secondary">
              取证：{totalIds.size} 条进入证据池
            </Text>
          ) : null}
          {hasDag && specs.length === 0 ? (
            <Text size="sm" color="secondary">
              任务图中未规划检索节点。
            </Text>
          ) : null}
        </Stack>
      );
    }
    case "executor": {
      const specs = dagNodes.filter((n) => n.role === "executor");
      const results = resultsForGraphNode("executor", run.nodeResults, run.dag);
      if (specs.length === 0 && results.length === 0) {
        return (
          <Text size="sm" color="secondary">
            本问未规划计算节点，跳过工具调用。
          </Text>
        );
      }
      return (
        <Stack gap={2}>
          <Text size="sm" weight="semibold" color="secondary">
            工具调用情况
          </Text>
          {specs.map((spec, i) => {
            const r = results[i];
            const out = r?.output as
              | { args?: { a?: number; b?: number }; result?: number; unit?: string }
              | null
              | undefined;
            return (
              <Stack key={spec.node_id} gap={1}>
                <Text size="sm" color="secondary">
                  工具：{spec.tool ?? "—"}
                </Text>
                {out?.args ? (
                  <Text size="sm" color="secondary" hasTabularNumbers>
                    入参：a={out.args.a}，b={out.args.b}
                  </Text>
                ) : null}
                {out?.result != null ? (
                  <Text size="sm" color="secondary" hasTabularNumbers>
                    结果：{out.result}
                    {out.unit ?? ""}
                  </Text>
                ) : null}
                {r?.block_reason ? (
                  <Text size="sm" color="secondary">
                    阻塞：{r.block_reason}
                  </Text>
                ) : null}
              </Stack>
            );
          })}
          {!hasDag && results.length > 0
            ? results.map((r) => (
                <Stack key={r.node_id} gap={1}>
                  <Text size="sm" color="secondary">
                    节点 {r.node_id}
                    {r.block_reason ? `：阻塞（${r.block_reason}）` : "：工具执行完成"}
                  </Text>
                </Stack>
              ))
            : null}
        </Stack>
      );
    }
    case "analyst": {
      const assertions = run.deliverable?.assertions ?? [];
      if (assertions.length === 0) {
        return (
          <Text size="sm" color="secondary">
            未产出断言（证据不足或与问题无关）。
          </Text>
        );
      }
      return <AssertionsSection title="分析产出的断言" assertions={assertions} />;
    }
    case "critic": {
      const v = run.verdict;
      if (!v) {
        return (
          <Text size="sm" color="secondary">
            审校结论未就绪。
          </Text>
        );
      }
      return (
        <Stack gap={1}>
          <Text size="sm" weight="semibold" color="secondary">
            审校产出
          </Text>
          <Text size="sm" color="secondary">
            结论：{v.verdict === "pass" ? "通过" : `打回 → ${v.send_back_to ?? "上游"}`}
          </Text>
          {v.issues.map((iss, i) => (
            <Text key={i} size="sm" color="secondary">
              · {iss}
            </Text>
          ))}
        </Stack>
      );
    }
    case "writer": {
      const d = run.deliverable;
      if (!d) {
        return (
          <Text size="sm" color="secondary">
            等待人工放行后输出兜底结论。
          </Text>
        );
      }
      return (
        <Stack gap={1}>
          <Text size="sm" weight="semibold" color="secondary">
            交付产出
          </Text>
          <Text size="sm" color="secondary">
            {d.refused ? "已拒答" : d.degraded ? "兜底结论（降级）" : "正常交付"} · 置信度{" "}
            {d.confidence.toFixed(2)}
            {d.confidence_source === "llm" ? "（大模型评分）" : d.confidence_source === "formula" ? "（公式兜底）" : ""}
          </Text>
          {d.confidence_reason ? (
            <Text size="sm" color="secondary">
              评分理由：{d.confidence_reason}
            </Text>
          ) : null}
          {d.refusal_reason ? (
            <Text size="sm" color="secondary">
              说明：{d.refusal_reason}
            </Text>
          ) : null}
          {d.assertions.length > 0 ? (
            <AssertionsSection title="最终断言" assertions={d.assertions} />
          ) : null}
        </Stack>
      );
    }
  }
}

function NodeDetail({
  run,
  node,
  activeEvidenceId,
  onEvidenceClick,
}: {
  run: RunState;
  node: string;
  activeEvidenceId: string | null;
  onEvidenceClick: (id: string) => void;
}) {
  const name = node as GraphNodeName;
  const events = run.nodeEvents.filter((e) => e.node === name);
  const result = run.nodeResults?.[name];
  const results = resultsForGraphNode(name, run.nodeResults, run.dag);
  // 历史回放快照没有端侧事件：按 node_results / dag / deliverable 推导是否执行过
  const executed =
    events.length > 0 ||
    results.length > 0 ||
    (name === "planner" && Boolean(run.dag)) ||
    (name === "writer" && Boolean(run.deliverable));
  const runCount = events.length > 0 ? events.length : results.length || (executed ? 1 : 0);
  const totalMs = events.reduce((a, b) => a + b.durationMs, 0);
  const usedIds = evidenceForNode(run, node);
  const evById = useMemo(() => {
    const map: Record<string, Evidence> = {};
    for (const [k, v] of Object.entries(run.evidencePool ?? {})) map[k] = v;
    for (const c of run.deliverable?.citations ?? []) map[c.evidence_id] = c;
    return map;
  }, [run.evidencePool, run.deliverable]);
  const stageCards = [...usedIds].map((id) => evById[id]).filter(Boolean);

  return (
    <Stack gap={3}>
        <Stack direction="horizontal" gap={2} vAlign="center" wrap="wrap">
          <Heading level={4}>{NODE_LABELS[name] ?? node}</Heading>
          {executed ? (
            <Badge variant="success" label="完成" />
          ) : run.phase === "interrupted" && node === "writer" ? (
            <Badge variant="error" label="等待放行" />
          ) : (
            <Badge variant="neutral" label="未执行" />
          )}
          {result?.status === "blocked" ? <Badge variant="warning" label="阻塞" /> : null}
        </Stack>

        <MetadataList orientation="horizontal">
          <MetadataListItem label="执行次数">{runCount}</MetadataListItem>
          <MetadataListItem label="端侧累计耗时">
            {events.length > 0 ? `${(totalMs / 1000).toFixed(1)}s` : "—"}
          </MetadataListItem>
          <MetadataListItem label="审校轮次">
            {run.roundNo != null ? `第 ${run.roundNo} 轮` : "—"}
          </MetadataListItem>
        </MetadataList>

        {result?.block_reason ? (
          <Text size="sm" color="secondary">
            阻塞原因：{result.block_reason}
          </Text>
        ) : null}

        <StageSection run={run} node={name} />

        <Stack gap={2}>
          <Text size="sm" weight="semibold" color="secondary">
            该节点使用的证据（点击高亮原文）
          </Text>
          {stageCards.length > 0 ? (
            stageCards.map((ev) => (
              <EvidenceCard
                key={ev.evidence_id}
                evidence={ev}
                highlighted={activeEvidenceId === ev.evidence_id}
                onClick={() => onEvidenceClick(ev.evidence_id)}
              />
            ))
          ) : (
            <Text size="sm" color="secondary">
              该节点未挂证据。
            </Text>
          )}
        </Stack>
    </Stack>
  );
}

export default function TracePage() {
  const {
    runs,
    activeRunKey,
    setActiveRunKey,
    startRun,
    transportKind,
    history,
    reloadHistory,
    restoreRun,
  } = useRuns();
  const { setPage } = useUi();
  const [selectedNode, setSelectedNode] = useState<string | null>(null);
  const [activeEvidenceId, setActiveEvidenceId] = useState<string | null>(null);

  // 新 run 完成/阶段变化时刷新持久化历史（SQLite）
  const phaseSig = useMemo(() => runs.map((r) => `${r.runId}:${r.phase}`).join(","), [runs]);
  useEffect(() => {
    if (transportKind === "live") void reloadHistory();
  }, [phaseSig, transportKind, reloadHistory]);

  const loadedRunIds = useMemo(
    () => new Set(runs.map((r) => r.runId).filter((id): id is string => Boolean(id))),
    [runs],
  );
  const historyItems = useMemo(
    () => history.filter((h) => !loadedRunIds.has(h.run_id)),
    [history, loadedRunIds],
  );

  const run = useMemo<RunState | null>(() => {
    if (runs.length === 0) return null;
    return runs.find((r) => r.key === activeRunKey) ?? runs[runs.length - 1];
  }, [runs, activeRunKey]);

  const handleEvidenceClick = useCallback((id: string) => {
    setActiveEvidenceId((cur) => (cur === id ? null : id));
  }, []);

  const handleSelectNode = useCallback((node: string | null) => {
    setSelectedNode(node);
    setActiveEvidenceId(null);
  }, []);

  const truncate = (s: string, n: number) => (s.length > n ? `${s.slice(0, n)}…` : s);

  const runOptions = useMemo(
    () => [
      ...runs.map((r) => ({
        value: r.key,
        label: `${truncate(r.question, 26)}${r.phase === "streaming" ? " · 执行中" : ""}`,
      })),
      ...historyItems.map((h) => ({
        value: `h:${h.run_id}`,
        label: `↺ ${truncate(h.question, 22)} · ${h.created_at.slice(5, 16).replace("T", " ")}`,
      })),
    ],
    [runs, historyItems],
  );

  const handlePickRun = useCallback(
    (value: string) => {
      if (value.startsWith("h:")) {
        void restoreRun(value.slice(2));
        return;
      }
      setActiveRunKey(value);
      setSelectedNode(null);
      setActiveEvidenceId(null);
    },
    [restoreRun, setActiveRunKey],
  );

  if (!run) {
    return (
      <div className="page-fill page-center">
        <EmptyState
          title="暂无轨迹"
          description="先在会话页提问生成运行轨迹，或直接加载一条演示轨迹。"
          actions={
            <Stack direction="horizontal" gap={2} wrap="wrap">
              <Button label="去会话页提问" variant="primary" onClick={() => setPage("chat")} />
              {transportKind === "mock"
                ? DEMO_TRACES.map((q) => (
                    <Button
                      key={q}
                      label={`演示：${q.slice(0, 12)}…`}
                      variant="secondary"
                      size="sm"
                      onClick={() => startRun(q)}
                    />
                  ))
                : history.slice(0, 6).map((h) => (
                    <Button
                      key={h.run_id}
                      label={`回放：${h.question.slice(0, 12)}${h.question.length > 12 ? "…" : ""}`}
                      variant="secondary"
                      size="sm"
                      onClick={() => void restoreRun(h.run_id)}
                    />
                  ))}
            </Stack>
          }
        />
      </div>
    );
  }

  return (
    <div className="page-fill trace-page">
      <div className="trace-toolbar">
        <Stack direction="horizontal" gap={3} vAlign="center" wrap="wrap" padding={3}>
          <Selector
            label="运行记录"
            isLabelHidden
            size="sm"
            variant="secondary"
            options={runOptions}
            value={run.key}
            onChange={handlePickRun}
          />
          <Text size="2xs" color="secondary">
            本次会话 {runs.length} 条 · 已落库 {history.length} 条
          </Text>
        </Stack>
      </div>

      <div className="trace-scroll">
        <Stack gap={4} padding={4} maxWidth={1360} style={{ margin: "0 auto", width: "100%" }}>
          <RunOverview run={run} />
          <FlowDag
            run={run}
            selectedNode={selectedNode}
            onSelectNode={handleSelectNode}
            detail={
              selectedNode ? (
                <NodeDetail
                  run={run}
                  node={selectedNode}
                  activeEvidenceId={activeEvidenceId}
                  onEvidenceClick={handleEvidenceClick}
                />
              ) : undefined
            }
          />
          <RetrievalPanel run={run} />

          {run.deliverable ? (
            <Card padding={4}>
              <Stack gap={3}>
                <Stack direction="horizontal" gap={2} vAlign="center" wrap="wrap">
                  <Heading level={4}>交付物引用</Heading>
                  <Text size="2xs" color="secondary">
                    共 {run.deliverable.citations.length} 条 · 点击卡片高亮原文
                  </Text>
                </Stack>
                <Stack gap={2}>
                  {run.deliverable.citations.map((ev) => (
                    <EvidenceCard
                      key={ev.evidence_id}
                      evidence={ev}
                      highlighted={
                        activeEvidenceId === ev.evidence_id ||
                        (selectedNode != null &&
                          evidenceForNode(run, selectedNode).has(ev.evidence_id))
                      }
                      onClick={() => handleEvidenceClick(ev.evidence_id)}
                    />
                  ))}
                </Stack>
              </Stack>
            </Card>
          ) : null}
        </Stack>
      </div>
    </div>
  );
}
