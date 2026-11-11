/**
 * TracePage：React Flow 六角色 DAG + 节点/证据联动。
 * 节点显示 status 与耗时，边按执行顺序流动；点击节点或证据 chip 高亮证据原文。
 * 详情栏按角色展示该阶段产出：规划→任务图、检索→检索词与取证、计算→工具入参出参、
 * 分析→断言、审校→结论与问题、交付→置信度与最终断言。
 */
import { useCallback, useMemo, useState } from "react";
import {
  Badge,
  Banner,
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
  type AgentResult,
  type Assertion,
  type Channel,
  type Evidence,
  type GraphNodeName,
} from "../types";
import { useRuns, type RunState } from "../store/runs";
import { useUi } from "../store/ui";

const DEMO_TRACES = [
  "一碗米饭大概多少碳水？",
  "米饭和馒头的升糖负荷哪个更高？",
];

const CHANNEL_BADGE: Record<Channel, { variant: "neutral" | "info" | "success" | "warning"; label: string }> = {
  local: { variant: "neutral", label: CHANNEL_LABELS.local },
  web: { variant: "info", label: CHANNEL_LABELS.web },
  cloud: { variant: "success", label: CHANNEL_LABELS.cloud },
  image: { variant: "info", label: CHANNEL_LABELS.image },
  tool: { variant: "success", label: CHANNEL_LABELS.tool },
  memory: { variant: "warning", label: CHANNEL_LABELS.memory },
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
  const counts: Record<Channel, number> = {
    local: 0,
    web: 0,
    cloud: 0,
    image: 0,
    tool: 0,
    memory: 0,
  };
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

/** MCP 工具调用流水：node_results[*].output.calls（后端真实入参/出参） */
interface McpCall {
  tool: string;
  args?: Record<string, unknown>;
  ok?: boolean;
  result?: unknown;
  unit?: string | null;
  gi?: number | null;
  source?: string | null;
  error?: string | null;
  evidence_id?: string | null;
}

function mcpCalls(result?: AgentResult): McpCall[] {
  const raw = result?.output?.calls;
  return Array.isArray(raw) ? (raw as McpCall[]) : [];
}

function formatArgs(args?: Record<string, unknown>): string {
  if (!args) return "—";
  return Object.entries(args)
    .map(([k, v]) => `${k}=${String(v)}`)
    .join("，");
}

function formatCallResult(call: McpCall): string {
  if (call.ok === false) return call.error ?? "调用失败";
  if (typeof call.result === "number") return `${call.result}${call.unit ? ` ${call.unit}` : ""}`;
  if (call.result && typeof call.result === "object") {
    const r = call.result as { carbs_per_100g?: number; gi?: number };
    return `碳水 ${r.carbs_per_100g}g/100g · GI ${r.gi}`;
  }
  return "—";
}

function RunOverview({ run }: { run: RunState }) {
  const counts = channelCounts(run.evidencePool);
  const totalEvidence = Object.values(counts).reduce((sum, n) => sum + n, 0);
  const d = run.deliverable;
  const assertions = d?.assertions ?? [];
  const citedAssertions = assertions.filter((a) => a.cites.length > 0).length;
  const totalMs = (run.finishedAt ?? Date.now()) - run.startedAt;
  const hasSideEvents = run.nodeEvents.length > 0;
  const phase = PHASE_META[run.phase];
  const verdict = run.verdict;

  return (
    <Card padding={4}>
      <Stack gap={3}>
        <Stack direction="horizontal" gap={2} vAlign="center" wrap="wrap">
          <Badge variant={phase.variant} label={phase.label} />
          {run.source === "mock" ? <Badge variant="neutral" label="Mock" /> : null}
          {verdict ? (
            <Badge
              variant={verdict.verdict === "pass" ? "success" : "warning"}
              label={
                verdict.verdict === "pass"
                  ? `审校通过 · 第 ${verdict.round_no} 轮`
                  : `审校打回 → ${verdict.send_back_to ?? "上游"} · 第 ${verdict.round_no} 轮`
              }
            />
          ) : null}
          {run.guard ? (
            <Badge
              variant={run.guard.allowed ? "neutral" : "error"}
              label={run.guard.allowed ? "安全红线未触发" : "输入已拦截"}
            />
          ) : null}
          <Text size="2xs" color="secondary">
            {run.runId ?? "run_id 未就绪"}
          </Text>
        </Stack>
        <Heading level={3}>{run.question}</Heading>
        <div className="stat-strip">
          {hasSideEvents ? (
            <div className="stat">
              <span>总耗时</span>
              <b>
                {(totalMs / 1000).toFixed(1)}
                <small> 秒</small>
              </b>
            </div>
          ) : null}
          <div className="stat">
            <span>证据池</span>
            <b>
              {totalEvidence}
              <small> 条</small>
            </b>
          </div>
          <div className="stat">
            <span>断言</span>
            <b>
              {assertions.length > 0 ? assertions.length : "—"}
              {assertions.length > 0 ? <small> 条 · 带引用 {citedAssertions}</small> : null}
            </b>
          </div>
          <div className="stat">
            <span>交付引用</span>
            <b>
              {d?.citations.length ?? 0}
              <small> 条</small>
            </b>
          </div>
          <div className="stat">
            <span>置信度</span>
            <b>
              {d ? `${Math.round(d.confidence * 100)}` : "—"}
              {d ? <small>%</small> : null}
            </b>
            {d?.confidence_source ? (
              <small className="stat-unit">
                {d.confidence_source === "llm" ? "模型评分" : "公式兜底"}
              </small>
            ) : null}
          </div>
        </div>
        <Stack direction="horizontal" gap={2} vAlign="center" wrap="wrap">
          <Text size="2xs" color="secondary">
            证据分渠道
          </Text>
          {(Object.keys(CHANNEL_BADGE) as Channel[]).map((ch) => (
            <Badge
              key={ch}
              variant={CHANNEL_BADGE[ch].variant}
              label={`${CHANNEL_BADGE[ch].label} ${counts[ch]}`}
            />
          ))}
        </Stack>
      </Stack>
    </Card>
  );
}

function RetrievalPanel({ run }: { run: RunState }) {
  const rows = buildRetrievalRows(run);
  const counts = channelCounts(run.evidencePool);
  const totalEvidence = Object.values(counts).reduce((sum, n) => sum + n, 0);

  return (
    <Card padding={4}>
      <Stack gap={3}>
        <Stack direction="horizontal" gap={3} vAlign="start" hAlign="between" wrap="wrap">
          <Stack gap={1}>
            <Text weight="semibold">多通道取证</Text>
            <Text size="2xs" color="secondary">
              本地 R2R · Web（DuckDuckGo）· 云端网盘（Google Drive）三路并行检索；拍照识别与 MCP 工具结果一并入池
            </Text>
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
            {totalEvidence > 0
              ? "本问未走本地/Web/云盘检索，证据来自拍照识别或 MCP 工具。"
              : "本问还没有检索记录。"}
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
      const calls = results.flatMap((r) => mcpCalls(r));
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
          {calls.length > 0 ? (
            <Card padding={3}>
              <Stack gap={2}>
                <Text size="sm" weight="semibold" color="secondary">
                  MCP 调用流水（{calls.length} 次）
                </Text>
                {calls.map((c, i) => (
                  <div className="audit-call" key={`${c.tool}-${i}`}>
                    <div className="audit-head">
                      <span className="audit-tool">{c.tool}</span>
                      <span className={`audit-ok${c.ok === false ? " is-fail" : ""}`}>
                        {c.ok === false ? "调用失败" : "调用成功"}
                      </span>
                    </div>
                    <div className="audit-tiles">
                      <div className="audit-tile">
                        <span>输入参数</span>
                        <strong className="mono">{formatArgs(c.args)}</strong>
                      </div>
                      <div className="audit-tile">
                        <span>返回结果</span>
                        <strong className="mono">{formatCallResult(c)}</strong>
                      </div>
                      <div className="audit-tile">
                        <span>证据引用</span>
                        <strong>{c.evidence_id ?? "—"}</strong>
                        {c.source ? <small>{c.source}</small> : null}
                      </div>
                    </div>
                  </div>
                ))}
              </Stack>
            </Card>
          ) : null}
          {/* 有真实调用流水时不再重复列工具名；无流水（如增长率计算）保留规划侧信息 */}
          {calls.length === 0
            ? specs.map((spec, i) => {
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
              })
            : null}
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
      const assertions = run.deliverable?.assertions ?? [];
      const pool = run.evidencePool ?? {};
      const cited = assertions.filter((a) => a.cites.length > 0).length;
      const missing = [
        ...new Set(assertions.flatMap((a) => a.cites).filter((c) => !(c in pool))),
      ];
      return (
        <Stack gap={2}>
          <Text size="sm" weight="semibold" color="secondary">
            审校产出
          </Text>
          <Text size="sm" color="secondary">
            结论：{v.verdict === "pass" ? "通过" : `打回 → ${v.send_back_to ?? "上游"}`}
          </Text>
          <Stack gap={1}>
            <Stack direction="horizontal" gap={2} vAlign="center" wrap="wrap">
              <Badge
                variant={missing.length === 0 ? "success" : "error"}
                label={missing.length === 0 ? "引用编号全部存在" : `${missing.length} 个引用不在证据池`}
              />
              <Text size="2xs" color="secondary">
                {missing.length > 0 ? missing.join("、") : ""}
              </Text>
            </Stack>
            <Stack direction="horizontal" gap={2} vAlign="center" wrap="wrap">
              <Badge
                variant={
                  assertions.length === 0
                    ? "neutral"
                    : cited === assertions.length
                      ? "success"
                      : "warning"
                }
                label={
                  assertions.length === 0
                    ? "无可核断言"
                    : `断言带引用 ${cited}/${assertions.length}`
                }
              />
            </Stack>
            {run.guard ? (
              <Badge
                variant={run.guard.allowed ? "success" : "error"}
                label={
                  run.guard.allowed ? "安全红线检查通过" : `安全红线拦截：${run.guard.reason ?? "见会话页"}`
                }
              />
            ) : (
              <Badge variant="neutral" label="安全红线本问未触发" />
            )}
          </Stack>
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
          {d.degraded_reason ? (
            <Text size="sm" color="secondary">
              降级原因：{d.degraded_reason}
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
    approveRun,
  } = useRuns();
  const { setPage } = useUi();
  const [selectedNode, setSelectedNode] = useState<string | null>(null);
  const [activeEvidenceId, setActiveEvidenceId] = useState<string | null>(null);

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
    () =>
      runs.map((r) => ({
        value: r.key,
        label: `${truncate(r.question, 26)}${r.phase === "streaming" ? " · 执行中" : ""}`,
      })),
    [runs],
  );

  const handlePickRun = useCallback(
    (value: string) => {
      setActiveRunKey(value);
      setSelectedNode(null);
      setActiveEvidenceId(null);
    },
    [setActiveRunKey],
  );

  if (!run) {
    return (
      <div className="page-fill trace-page">
        <div className="trace-toolbar">
          <Stack direction="horizontal" gap={3} vAlign="center" wrap="wrap" padding={3}>
            <Text size="2xs" color="secondary">
              从左侧会话历史打开一段对话，再点消息里的「查看轨迹」；工具入参、证据来源和审校结论都会保留。
            </Text>
          </Stack>
        </div>
        <div className="trace-scroll page-center">
          <EmptyState
            title="暂无轨迹"
            description="先在控糖工作台跑一次评估，或从左侧会话历史打开一段旧对话。"
            actions={
              <Stack direction="horizontal" gap={2} wrap="wrap">
                <Button label="去工作台提问" variant="primary" onClick={() => setPage("chat")} />
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
                  : null}
              </Stack>
            }
          />
        </div>
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
            当前已加载 {runs.length} 条运行
          </Text>
        </Stack>
      </div>

      <div className="trace-scroll">
        <Stack gap={4} padding={4} maxWidth={1360} style={{ margin: "0 auto", width: "100%" }}>
          <RunOverview run={run} />
          {run.phase === "interrupted" ? (
            <Banner
              status="warning"
              title="流程在人工断点暂停"
              description="审校连续打回且轮数用尽，图挂在 Writer 前。放行后输出兜底结论并标注降级。"
              endContent={
                <Button
                  label="放行并交付"
                  variant="primary"
                  size="sm"
                  isLoading={run.approving}
                  isDisabled={run.approving}
                  onClick={() => void approveRun(run.key)}
                />
              }
            />
          ) : null}
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
