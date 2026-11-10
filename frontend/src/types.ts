/**
 * 后端契约类型（锁死，不许改）。
 *
 * 来源：
 * - backend/app/api/chat.py        SSE 事件：payload.type + 扁平 payload
 * - backend/app/api/tasks.py       GET /api/tasks/{run_id} 快照、POST approve
 * - backend/core/schemas/deliverable.py  Deliverable / Assertion
 * - backend/core/schemas/evidence.py     Evidence
 * - backend/core/schemas/common.py       SourceRef
 * - backend/core/schemas/agent.py        AgentResult / ReviewVerdict
 */

export type Modality = "text" | "image" | "audio";

/** SourceRef（core/schemas/common.py） */
export interface SourceRef {
  file_path?: string | null;
  section?: string | null;
  page?: number | null;
  time_code?: string | null;
  modality: Modality;
}

/** Evidence（core/schemas/evidence.py） */
export type Channel = "local" | "web" | "cloud";

export interface Evidence {
  evidence_id: string;
  doc_id: string;
  quote: string;
  score: number;
  source: SourceRef;
  /** 检索渠道：本地库 / Web / 云端网盘 */
  channel?: Channel;
}

export const CHANNEL_LABELS: Record<Channel, string> = {
  local: "本地库",
  web: "Web",
  cloud: "云端网盘",
};

/** Assertion（core/schemas/deliverable.py） */
export interface Assertion {
  text: string;
  /** 证据编号，如 ["E1"] */
  cites: string[];
  /** 挂不上引用的断言标为推断 */
  inferred?: boolean;
}

/** Deliverable（core/schemas/deliverable.py） */
export interface Deliverable {
  question: string;
  assertions: Assertion[];
  citations: Evidence[];
  trace_id: string;
  confidence: number;
  /** 置信度来源：LLM 评分 / 公式兜底 */
  confidence_source?: "llm" | "formula";
  /** 大模型给出的一句话评分理由 */
  confidence_reason?: string | null;
  degraded: boolean;
  refused: boolean;
  refusal_reason: string | null;
}

/** SSE 事件（chat.py _sse 的 payload.type 分支，逐字对齐） */
export type SseEvent =
  | { type: "run"; run_id: string }
  | { type: "node"; node: string; status: string }
  | { type: "guard"; allowed: boolean; reason?: string | null }
  | { type: "deliverable"; deliverable: Deliverable }
  | { type: "error"; message: string }
  | { type: "done" };

/** AgentResult（core/schemas/agent.py，node_results 的值） */
export type AgentStatus = "done" | "blocked" | "needs_human";

/** 单次检索的三通道执行记录（retriever 节点写入 node_results） */
export interface RetrievalRecord {
  channel: string;
  hits: number;
  latency_ms: number;
  /** ok / 未配置 / 失败：Xxx / 超时 */
  status: string;
}

export interface AgentResult {
  node_id: string;
  status: AgentStatus;
  output?: Record<string, unknown> | null;
  evidence_used: string[];
  block_reason?: string | null;
  /** 该检索节点各渠道的执行记录 */
  retrievals?: RetrievalRecord[];
}

/** GET /api/runs 的历史条目（SQLite 持久化） */
export interface RunSummary {
  run_id: string;
  session_id: string;
  question: string;
  status: "running" | "done" | "interrupted";
  confidence: number | null;
  refused: 0 | 1;
  created_at: string;
}

/** GET /api/tasks/{run_id} 返回（tasks.py） */
export interface TaskSnapshot {
  run_id: string;
  question: string | null;
  round_no: number;
  node_results: Record<string, AgentResult>;
  verdict: ReviewVerdict | null;
  deliverable: Deliverable | null;
  /** planner 产出的任务图（core/schemas/dag.py TaskDAG） */
  dag: DagPlan | null;
  /** 全量证据池（state["evidence"]，含未被引用的检索结果） */
  evidence: Record<string, Evidence> | null;
  /** 是否挂在人工断点等待放行 */
  pending_human?: boolean;
}

/** TaskDAG（core/schemas/dag.py） */
export interface DagNodeSpec {
  node_id: string;
  role: "planner" | "retriever" | "executor" | "analyst" | "critic";
  instruction: string;
  depends_on: string[];
  budget: { max_steps: number; max_rounds: number; timeout_s: number };
  tool: string | null;
  query: string | null;
}

export interface DagPlan {
  question: string;
  nodes: DagNodeSpec[];
}

/** ReviewVerdict（core/schemas/agent.py） */
export interface ReviewVerdict {
  verdict: "pass" | "send_back";
  issues: string[];
  send_back_to: string | null;
  round_no: number;
}

/** 图固定六角色（core/graph/builder.py） */
export const GRAPH_NODES = [
  "planner",
  "retriever",
  "executor",
  "analyst",
  "critic",
  "writer",
] as const;

export type GraphNodeName = (typeof GRAPH_NODES)[number];

export const NODE_LABELS: Record<GraphNodeName, string> = {
  planner: "Planner 规划",
  retriever: "Retriever 检索",
  executor: "Executor 计算",
  analyst: "Analyst 分析",
  critic: "Critic 审校",
  writer: "Writer 交付",
};
