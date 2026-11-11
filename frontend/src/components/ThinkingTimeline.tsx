/**
 * 执行步骤推导：把 SSE 节点事件与任务快照揉成六角色状态，
 * 供会话内联轨迹（RunTrace）逐步点亮。
 */
import type { RunState } from "../store/runs";
import { GRAPH_NODES, type Channel, type GraphNodeName } from "../types";

type StepStatus = "done" | "running" | "pending" | "skipped" | "waiting";

export interface Step {
  node: GraphNodeName;
  status: StepStatus;
  count: number;
  durationMs: number;
  detail: string | null;
}

const RUNNING_HINT: Record<GraphNodeName, string> = {
  planner: "正在把问题拆成任务图",
  retriever: "正在检索本地库与 Web",
  executor: "正在调用工具计算",
  analyst: "正在把证据写成带引用的断言",
  critic: "正在核验断言是否有证据支撑",
  writer: "正在评分并生成交付物",
};

function nextNode(run: RunState, last: GraphNodeName | undefined): GraphNodeName | null {
  if (run.phase !== "streaming") return null;
  if (!last) return "planner";
  switch (last) {
    case "planner":
      return "retriever";
    case "retriever": {
      const executorDone = run.nodeEvents.some((e) => e.node === "executor");
      const hasExecutor = run.dag?.nodes.some((n) => n.role === "executor");
      return hasExecutor && !executorDone ? "executor" : "analyst";
    }
    case "executor":
      return "analyst";
    case "analyst":
      return "critic";
    case "critic": {
      const out = (run.nodeResults?.["critic"]?.output ?? run.verdict) as
        | { verdict?: string }
        | null
        | undefined;
      return out?.verdict === "send_back" ? "retriever" : "writer";
    }
    default:
      return null;
  }
}

function formatValue(value: unknown): string {
  if (typeof value !== "number") return String(value);
  return Number.isInteger(value) ? String(value) : value.toFixed(2).replace(/0+$/, "").replace(/\.$/, "");
}

function detailFor(node: GraphNodeName, run: RunState): string | null {
  switch (node) {
    case "planner":
      return run.dag ? `拆成 ${run.dag.nodes.length} 个任务节点` : null;
    case "retriever": {
      const pool = Object.values(run.evidencePool ?? {});
      if (!pool.length) return null;
      const by: Record<Channel, number> = {
        local: 0,
        web: 0,
        cloud: 0,
        image: 0,
        tool: 0,
        memory: 0,
      };
      for (const ev of pool) by[ev.channel ?? "local"] += 1;
      const extra = [by.image ? `拍照 ${by.image}` : "", by.memory ? `个人记录 ${by.memory}` : "", by.web ? `Web ${by.web}` : "", by.cloud ? `云盘 ${by.cloud}` : "", by.tool ? `工具 ${by.tool}` : ""]
        .filter(Boolean)
        .join(" · ");
      return `${pool.length} 条证据（本地 ${by.local}${extra ? ` · ${extra}` : ""}）`;
    }
    case "executor": {
      if (!run.dag) return null;
      const ids = run.dag.nodes.filter((n) => n.role === "executor").map((n) => n.node_id);
      if (!ids.length) return "无计算任务";
      const res = ids.map((id) => run.nodeResults?.[id]).find(Boolean);
      if (!res) return null;
      if (res.status === "blocked") return res.block_reason ?? "计算被跳过";
      const out = res.output as { result?: unknown; unit?: string } | null | undefined;
      if (out?.result === undefined) return null;
      return `工具结果 ${formatValue(out.result)}${out.unit ?? ""}`;
    }
    case "analyst": {
      const n = run.nodeResults?.["analyst"]?.evidence_used?.length ?? 0;
      return n ? `引用 ${n} 条证据` : null;
    }
    case "critic": {
      const out = run.nodeResults?.["critic"]?.output as
        | { verdict?: string; issues?: string[] }
        | null
        | undefined;
      if (!out?.verdict) return null;
      return out.verdict === "pass" ? "每条断言都有证据支撑" : `打回：${out.issues?.[0] ?? "证据支撑不足"}`;
    }
    case "writer": {
      const d = run.deliverable;
      if (!d) return null;
      const source = d.confidence_source === "llm" ? "模型评分" : "公式兜底";
      return `${Math.round(d.confidence * 100)}% 置信度 · ${source}`;
    }
  }
}

/** 回放的历史 run 没有 SSE 节点事件，用快照里的 dag / node_results 反推各角色已完成 */
function snapshotDone(run: RunState, node: GraphNodeName): boolean {
  if (run.nodeEvents.length > 0 || run.phase === "streaming") return false;
  const roles = run.dag?.nodes.map((n) => n.role) ?? [];
  switch (node) {
    case "planner":
      return Boolean(run.dag);
    case "retriever":
      return roles.includes("retriever");
    case "executor":
      return roles.includes("executor");
    case "analyst":
      return Boolean(run.nodeResults?.["analyst"]);
    case "critic":
      return Boolean(run.nodeResults?.["critic"]);
    case "writer":
      return Boolean(run.deliverable);
  }
}

export function buildSteps(run: RunState): Step[] {
  const stats = new Map<string, { count: number; ms: number }>();
  for (const e of run.nodeEvents) {
    const cur = stats.get(e.node) ?? { count: 0, ms: 0 };
    stats.set(e.node, { count: cur.count + 1, ms: cur.ms + e.durationMs });
  }
  const last = run.nodeEvents[run.nodeEvents.length - 1]?.node as GraphNodeName | undefined;
  const running = nextNode(run, last);
  return GRAPH_NODES.map((node) => {
    const seen = stats.get(node);
    const skipped = node === "executor" && run.dag != null && !run.dag.nodes.some((n) => n.role === "executor");
    // 人工放行不经过 SSE 节点事件，有交付物即视为 writer 已完成
    const writerDone = node === "writer" && run.deliverable != null;
    let status: StepStatus = seen || writerDone || snapshotDone(run, node) ? "done" : "pending";
    if (skipped) status = "skipped";
    if (running === node) status = "running";
    // 打回用尽时图停在 writer 之前，等人工放行
    if (node === "writer" && run.phase === "interrupted" && !run.deliverable) status = "waiting";
    const detail =
      status === "running"
        ? RUNNING_HINT[node]
        : status === "skipped"
          ? "无计算任务"
          : status === "waiting"
            ? "等待人工放行"
            : status === "done"
              ? detailFor(node, run)
              : null;
    return {
      node,
      status,
      count: seen?.count ?? 0,
      durationMs: seen?.ms ?? 0,
      detail,
    };
  });
}
