/**
 * TracePage DAG：React Flow 画六角色流水线，每个节点内直接给出该阶段产出摘要。
 * 节点/徽标全部用 Astryx Card/Badge/Text 渲染；点击节点 → 下方展开该阶段完整详情。
 */
import { useCallback, useMemo, type MouseEvent as ReactMouseEvent, type ReactNode } from "react";
import {
  Background,
  BackgroundVariant,
  Controls,
  Handle,
  Position,
  ReactFlow,
  type Edge,
  type Node,
  type NodeProps,
  type NodeTypes,
} from "@xyflow/react";
import { Badge, Button, Card, Stack, Text } from "@astryxdesign/core";
import {
  CHANNEL_LABELS,
  GRAPH_NODES,
  NODE_LABELS,
  type AgentResult,
  type Channel,
  type DagNodeSpec,
  type DagPlan,
  type GraphNodeName,
} from "../types";
import type { NodeEventLog, RunState } from "../store/runs";

export const ROLE_LABELS: Record<DagNodeSpec["role"], string> = {
  planner: "规划",
  retriever: "检索",
  executor: "计算",
  analyst: "分析",
  critic: "审校",
};

type DagNodeData = {
  label: string;
  desc: string;
  status: "pending" | "done" | "blocked" | "needs_human" | "waiting";
  times: number[];
  totalMs: number;
  blockReason: string | null;
  summary: string[];
  selected: boolean;
  anyHighlight: boolean;
};

type DagNode = Node<DagNodeData, "agent">;

const NODE_WIDTH = 196;
/** 节点横向间距：卡片宽度 + 连边留白 */
const NODE_STEP = 236;

const LAYOUT: Record<GraphNodeName, { x: number; y: number }> = {
  planner: { x: 0, y: 0 },
  retriever: { x: NODE_STEP, y: 0 },
  executor: { x: NODE_STEP * 2, y: 0 },
  analyst: { x: NODE_STEP * 3, y: 0 },
  critic: { x: NODE_STEP * 4, y: 0 },
  writer: { x: NODE_STEP * 5, y: 0 },
};

const SHORT_LABELS: Record<GraphNodeName, string> = {
  planner: "规划",
  retriever: "检索",
  executor: "计算",
  analyst: "分析",
  critic: "审校",
  writer: "交付",
};

const STATUS_LABELS: Record<DagNodeData["status"], string> = {
  pending: "未执行",
  done: "完成",
  blocked: "阻塞",
  needs_human: "待人工",
  waiting: "等待放行",
};

function statusBadgeVariant(status: DagNodeData["status"]): "success" | "neutral" | "warning" | "error" {
  if (status === "done") return "success";
  if (status === "pending") return "neutral";
  if (status === "blocked") return "warning";
  return "error";
}

function statusBorderColor(status: DagNodeData["status"]): string {
  if (status === "done") return "var(--color-border-success)";
  if (status === "blocked") return "var(--color-border-warning)";
  if (status === "pending") return "var(--color-border)";
  return "var(--color-border-error)";
}

function AgentNode({ data }: NodeProps<DagNode>) {
  return (
    <Card
      padding={3}
      elevation={data.selected ? "high" : "low"}
      minHeight={116}
      style={{
        width: NODE_WIDTH,
        boxSizing: "border-box",
        borderStyle: "solid",
        borderWidth: data.selected ? 2 : 1,
        borderColor: data.selected ? "var(--color-text-accent)" : statusBorderColor(data.status),
        cursor: "pointer",
        opacity: data.anyHighlight && !data.selected ? 0.4 : 1,
        transition: "border-color 120ms ease, opacity 120ms ease",
      }}
    >
      <Handle id="l" type="target" position={Position.Left} />
      <Stack gap={2}>
        <Stack direction="horizontal" gap={2} vAlign="center" hAlign="between">
          <Text size="sm" weight="semibold">
            {data.label}
          </Text>
          <Badge variant={statusBadgeVariant(data.status)} label={STATUS_LABELS[data.status]} />
        </Stack>

        {data.totalMs > 0 || data.times.length > 1 ? (
          <Stack direction="horizontal" gap={2} vAlign="center" wrap="wrap">
            {data.totalMs > 0 ? (
              <Text size="2xs" color="secondary" hasTabularNumbers>
                {(data.totalMs / 1000).toFixed(1)}s
              </Text>
            ) : null}
            {data.times.length > 1 ? (
              <Text size="2xs" color="secondary">
                ×{data.times.length}
              </Text>
            ) : null}
          </Stack>
        ) : null}

        {data.blockReason ? (
          <Text size="2xs" color="secondary" maxLines={2}>
            {data.blockReason}
          </Text>
        ) : data.summary.length > 0 ? (
          <Stack gap={0.5}>
            {data.summary.slice(0, 2).map((line, i) => (
              <Text key={i} size="2xs" color="secondary" maxLines={1}>
                {line}
              </Text>
            ))}
          </Stack>
        ) : (
          <Text size="2xs" color="secondary">
            —
          </Text>
        )}
      </Stack>
      <Handle id="r" type="source" position={Position.Right} />
    </Card>
  );
}

const nodeTypes: NodeTypes = { agent: AgentNode };

const BASE_EDGES: Array<{ id: string; source: GraphNodeName; target: GraphNodeName }> = [
  { id: "e-planner-retriever", source: "planner", target: "retriever" },
  { id: "e-retriever-executor", source: "retriever", target: "executor" },
  { id: "e-executor-analyst", source: "executor", target: "analyst" },
  { id: "e-retriever-analyst", source: "retriever", target: "analyst" },
  { id: "e-analyst-critic", source: "analyst", target: "critic" },
  { id: "e-critic-writer", source: "critic", target: "writer" },
  // 审校打回回路
  { id: "e-critic-retriever", source: "critic", target: "retriever" },
];

/**
 * 把 GET /api/tasks 快照的 node_results 映射到六个图角色。
 * 键名以 planner 任务图的 spec id 为权威（LLM 可能命名 e1/calc1 等任意 id）；
 * 快照未带 dag 时回退到后端键名约定：retriever=r*、executor=x*、analyst/critic 用图名。
 */
export function resultsForGraphNode(
  name: GraphNodeName,
  nodeResults: Record<string, AgentResult> | null,
  dag?: DagPlan | null,
): AgentResult[] {
  if (!nodeResults) return [];
  if (name === "analyst" || name === "critic" || name === "writer") {
    return nodeResults[name] ? [nodeResults[name]] : [];
  }
  if (dag) {
    const ids = dag.nodes.filter((n) => n.role === name).map((n) => n.node_id);
    if (ids.length > 0) {
      return ids.map((id) => nodeResults[id]).filter(Boolean);
    }
  }
  const prefix = name === "retriever" ? "r" : name === "executor" ? "x" : name === "planner" ? "p" : "";
  if (!prefix) return [];
  return Object.entries(nodeResults)
    .filter(([k, v]) => k !== name && v.node_id !== name && new RegExp(`^${prefix}\\d`).test(k))
    .map(([, v]) => v);
}

/** 节点摘要：该阶段最关键的一两行产出 */
function stageLines(name: GraphNodeName, run: RunState): string[] {
  const dagNodes = run.dag?.nodes ?? [];
  const results = resultsForGraphNode(name, run.nodeResults, run.dag);
  switch (name) {
    case "planner":
      return dagNodes.length > 0 ? [`任务图 ${dagNodes.length} 个节点`] : [];
    case "retriever": {
      if (results.length === 0) return [];
      // 打回重跑时同一检索会执行多次：这里只展示最后一轮各通道命中，避免重复累加
      const latest = results[results.length - 1];
      const hits: Record<Channel, number> = { local: 0, web: 0, cloud: 0 };
      for (const rec of latest.retrievals ?? []) {
        const ch = rec.channel as Channel;
        if (ch in hits) hits[ch] += rec.hits;
      }
      const used = new Set(results.flatMap((r) => r.evidence_used ?? [])).size;
      return [
        `取证 ${used} 条`,
        `本轮 ${CHANNEL_LABELS.local} ${hits.local} · ${CHANNEL_LABELS.web} ${hits.web} · ${CHANNEL_LABELS.cloud} ${hits.cloud}`,
      ];
    }
    case "executor": {
      const specs = dagNodes.filter((n) => n.role === "executor");
      if (specs.length === 0) return ["工具 0 次"];
      const ok = results.filter((r) => r.status === "done").length;
      const blocked = results.filter((r) => r.status === "blocked").length;
      return [blocked > 0 ? `工具 ${ok} 次 · 阻塞 ${blocked}` : `工具 ${ok} 次`];
    }
    case "analyst": {
      const n = run.deliverable?.assertions.length;
      return n != null ? [`断言 ${n} 条`] : [];
    }
    case "critic": {
      const v = run.verdict;
      if (!v) return [];
      return [v.verdict === "pass" ? "审校通过" : `打回 → ${v.send_back_to ?? "上游"}`];
    }
    case "writer": {
      const d = run.deliverable;
      if (!d) return [];
      if (d.refused) return ["已拒答"];
      return [`置信度 ${(d.confidence * 100).toFixed(0)}% · 引用 ${d.citations.length} 条`];
    }
  }
}

function computeNodeStatus(
  name: GraphNodeName,
  run: RunState,
): { status: DagNodeData["status"]; times: number[]; blockReason: string | null } {
  const events: NodeEventLog[] = run.nodeEvents.filter((e) => e.node === name);
  const results = resultsForGraphNode(name, run.nodeResults, run.dag);
  const blocked = results.find((r) => r.status === "blocked");
  const needsHuman = results.find((r) => r.status === "needs_human");
  const blockReason = blocked?.block_reason ?? needsHuman?.block_reason ?? null;
  if (events.length === 0) {
    // 历史回放（快照恢复的 run 没有端侧事件）：按快照结果推导状态
    if (results.length > 0) {
      const status = blocked ? "blocked" : needsHuman ? "needs_human" : "done";
      return { status, times: [], blockReason };
    }
    // planner/writer 的产物在 dag/deliverable 里，node_results 没有它们的键
    if (name === "planner" && run.dag) return { status: "done", times: [], blockReason };
    if (name === "writer" && run.deliverable) return { status: "done", times: [], blockReason };
    // writer 在断点场景从未收到 done 事件 → 等待放行
    if (run.phase === "interrupted" && name === "writer") {
      return { status: "waiting", times: [], blockReason: "审校打回已达上限，需人工放行后输出兜底结论" };
    }
    return { status: "pending", times: [], blockReason };
  }
  let status: DagNodeData["status"] = "done";
  if (blocked) status = "blocked";
  else if (needsHuman) status = "needs_human";
  else if (run.phase === "interrupted" && name === "writer") status = "waiting";
  return { status, times: events.map((e) => e.durationMs), blockReason };
}

/** 判断边是否被实际走过（按事件顺序；历史回放时按快照结果推导） */
function computeTraversed(run: RunState): Set<string> {
  const order: string[] = run.nodeEvents.map((e) => e.node);
  const count: Record<string, number> = {};
  for (const n of order) count[n] = (count[n] ?? 0) + 1;
  if (order.length === 0) {
    for (const name of GRAPH_NODES) {
      if (resultsForGraphNode(name, run.nodeResults, run.dag).length > 0) count[name] = 1;
    }
    // 历史快照里 analyst/critic/writer 的图名结果不一定存在，用交付物兜底
    if (run.deliverable) {
      count["analyst"] = count["analyst"] || 1;
      count["critic"] = count["critic"] || 1;
      count["writer"] = count["writer"] || 1;
    }
  }
  const traversed = new Set<string>();
  if (count["planner"] && count["retriever"]) traversed.add("e-planner-retriever");
  if (count["retriever"] && count["executor"]) traversed.add("e-retriever-executor");
  if (count["executor"] && count["analyst"]) traversed.add("e-executor-analyst");
  if (count["retriever"] && count["analyst"] && !count["executor"]) {
    traversed.add("e-retriever-analyst");
  }
  if (count["analyst"] && count["critic"]) traversed.add("e-analyst-critic");
  if (count["critic"] && (count["writer"] || run.phase === "interrupted")) {
    traversed.add("e-critic-writer");
  }
  // 打回回路：retriever 执行多次即说明 critic→retriever 发生过
  if ((count["retriever"] ?? 0) > 1) traversed.add("e-critic-retriever");
  return traversed;
}

export interface FlowDagProps {
  run: RunState;
  selectedNode: string | null;
  onSelectNode: (node: string | null) => void;
  /** 选中节点的完整产出：浮在画布（网格）上，而非画布下方 */
  detail?: ReactNode;
}

export function FlowDag({ run, selectedNode, onSelectNode, detail }: FlowDagProps) {
  const traversed = useMemo(() => computeTraversed(run), [run]);

  const nodes = useMemo<DagNode[]>(
    () =>
      GRAPH_NODES.map((name) => {
        const { status, times, blockReason } = computeNodeStatus(name, run);
        const pos = LAYOUT[name];
        const selected = selectedNode === name;
        return {
          id: name,
          type: "agent" as const,
          position: { x: pos.x, y: pos.y },
          data: {
            label: NODE_LABELS[name],
            desc: name,
            status,
            times,
            totalMs: times.reduce((a, b) => a + b, 0),
            blockReason,
            summary: stageLines(name, run),
            selected,
            anyHighlight: selectedNode !== null,
          },
        };
      }),
    [run, selectedNode],
  );

  const edges = useMemo<Edge[]>(
    () =>
      BASE_EDGES.map((e) => {
        const isTraversed = traversed.has(e.id);
        const isLoop = e.id === "e-critic-retriever";
        return {
          id: e.id,
          source: e.source,
          target: e.target,
          sourceHandle: "r",
          targetHandle: "l",
          type: "smoothstep" as const,
          animated: isTraversed,
          style: {
            stroke: isTraversed ? "var(--color-text-success)" : "var(--color-border-emphasized)",
            strokeWidth: isTraversed ? 2 : 1.5,
            opacity: isTraversed ? 1 : 0.55,
          },
          label: isLoop ? "打回" : undefined,
          labelStyle: { fontSize: 11, fill: "var(--color-text-secondary)" },
          labelBgStyle: { fill: "var(--color-background-card)" },
        };
      }),
    [traversed],
  );

  const handleNodeClick = useCallback(
    (_: ReactMouseEvent, node: DagNode) => {
      onSelectNode(node.id === selectedNode ? null : node.id);
    },
    [onSelectNode, selectedNode],
  );

  return (
    <div className={detail ? "dag-canvas has-detail" : "dag-canvas"}>
      <ReactFlow<DagNode>
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        onNodeClick={handleNodeClick}
        onPaneClick={() => onSelectNode(null)}
        fitView
        fitViewOptions={{ padding: 0.12 }}
        proOptions={{ hideAttribution: true }}
        nodesDraggable={false}
        nodesConnectable={false}
        elementsSelectable
        minZoom={0.35}
        maxZoom={1.4}
      >
        <Background variant={BackgroundVariant.Dots} gap={22} size={1} />
        <Controls showInteractive={false} />
      </ReactFlow>

      {detail ? (
        <div className="dag-detail">
          <div className="dag-detail-bar">
            <Stack direction="horizontal" gap={1} vAlign="center" wrap="wrap" style={{ minWidth: 0 }}>
              {GRAPH_NODES.map((n) => (
                <Button
                  key={n}
                  label={SHORT_LABELS[n]}
                  size="sm"
                  variant={n === selectedNode ? "primary" : "ghost"}
                  onClick={() => onSelectNode(n)}
                />
              ))}
            </Stack>
            <Button label="关闭" variant="ghost" size="sm" onClick={() => onSelectNode(null)} />
          </div>
          <div className="dag-detail-body">{detail}</div>
        </div>
      ) : (
        <div className="dag-hint">
          <Text size="2xs" color="secondary">
            点击任一节点，该阶段产出会展示在画布上
          </Text>
        </div>
      )}
    </div>
  );
}
