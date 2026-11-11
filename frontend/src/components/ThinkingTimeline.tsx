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

export const RUNNING_HINT: Record<GraphNodeName, string> = {
  planner: "把你的问题拆成可执行的任务，确定需要查找和计算的内容。",
  retriever: "查找与问题相关的资料，整理可追溯的来源。",
  executor: "调用工具核算数据，为建议补充计算依据。",
  analyst: "结合现有证据整理建议，并为每条建议关联来源。",
  critic: "检查建议与证据是否一致，必要时交回补充。",
  writer: "整理最终回答与引用，并评估回答的置信度。",
};

export const STEP_LABEL: Record<GraphNodeName, string> = {
  planner: "规划任务", retriever: "检索取证", executor: "工具计算",
  analyst: "分析建议", critic: "审校核验", writer: "生成回答",
};

export function isGraphNode(node: string): node is GraphNodeName {
  return GRAPH_NODES.some((name) => name === node);
}

export function executionEntries(run: RunState) {
  if (run.nodeEvents.length) {
    const counts = new Map<string, number>();
    return run.nodeEvents.filter((event) => event.status === "done" && isGraphNode(event.node)).map((event, i) => {
      const count = (counts.get(event.node) ?? 0) + 1;
      counts.set(event.node, count);
      return { ...event, node: event.node as GraphNodeName, key: `${run.key}-${i}`, count };
    });
  }
  return buildSteps(run).filter((step) => step.status === "done").map((step) => ({
    key: `${run.key}-${step.node}`, node: step.node, durationMs: 0, count: 1,
    summary: "该步骤已完成；这条旧记录未保存逐步反馈。",
  }));
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
    case "executor":
      return roles.includes(node) && Boolean(run.dag?.nodes.some((n) => n.role === node && run.nodeResults?.[n.node_id]?.status === "done"));
    case "analyst":
      return Boolean(run.nodeResults?.["analyst"]);
    case "critic":
      return Boolean(run.nodeResults?.["critic"]);
    case "writer":
      return Boolean(run.deliverable && !run.deliverable.refused && !run.deliverable.degraded);
  }
}

export function buildSteps(run: RunState): Step[] {
  const stats = new Map<string, { count: number; ms: number }>();
  for (const e of run.nodeEvents) {
    const cur = stats.get(e.node) ?? { count: 0, ms: 0 };
    stats.set(e.node, { count: cur.count + 1, ms: cur.ms + e.durationMs });
  }
  const running = run.phase === "streaming" ? run.activeNode : run.approving ? "writer" : null;
  return GRAPH_NODES.map((node) => {
    const seen = stats.get(node);
    const skipped = node === "executor" && run.dag != null && !run.dag.nodes.some((n) => n.role === "executor");
    // 人工放行不经过 SSE 节点事件，有交付物即视为 writer 已完成
    const writerDone = node === "writer" && run.approved && run.deliverable != null;
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
