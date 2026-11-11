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

/** 证据渠道：本地库 / Web / 云端网盘 / 餐食拍照识别 / MCP 工具 / 个人记录 */
export type Channel = "local" | "web" | "cloud" | "image" | "tool" | "memory";

export interface Evidence {
  evidence_id: string;
  doc_id: string;
  quote: string;
  score: number;
  source: SourceRef;
  /** 证据渠道：本地库 / Web / 云端网盘 / 拍照 / MCP 工具 */
  channel?: Channel;
}

export const CHANNEL_LABELS: Record<Channel, string> = {
  local: "本地库",
  web: "Web",
  cloud: "云端网盘",
  image: "拍照",
  tool: "工具",
  memory: "个人记录",
};

/** FoodItem（core/schemas/food.py） */
export interface FoodItem {
  name: string;
  grams_low: number;
  grams_high: number;
  carbs_g_low: number;
  carbs_g_high: number;
  confidence: number;
  basis?: string;
}

/** FoodAnalysis（core/schemas/food.py） */
export interface FoodAnalysis {
  image_id: string;
  items: FoodItem[];
  carbs_g_low: number;
  carbs_g_high: number;
  confidence: number;
  source: "vlm" | "demo";
  degraded: boolean;
  notes: string;
}

/** POST /api/chat 的可选餐食上下文 */
export interface FoodContext {
  image_id: string;
  food_items: FoodItem[];
  /** 本地预览图（object URL），仅当前会话内有效 */
  photo_url?: string | null;
}

/** 餐食记录（backend/app/api/meals.py） */
export type MealType = "早餐" | "午餐" | "晚餐" | "加餐";
export type MealSource = "photo" | "chat" | "manual";

export interface MealFood {
  name: string;
  grams: number;
  carbs_g?: number | null;
  gl?: number | null;
}

export interface GlucoseReading {
  reading_id: string;
  meal_id: string;
  measured_at: string;
  minutes_after: number;
  value_mmol: number;
  source: "manual" | "cgm";
}

export interface MealRecord {
  meal_id: string;
  user_id: string;
  eaten_at: string;
  meal_type: MealType;
  foods: MealFood[];
  carbs_g: number | null;
  gl: number | null;
  note: string;
  source: MealSource;
  image_id: string | null;
  insulin_note: string;
  created_at: string;
  updated_at: string;
  readings: GlucoseReading[];
}

export interface MealDraft {
  eaten_at: string;
  meal_type: MealType;
  foods: MealFood[];
  note: string;
  source: MealSource;
  image_id?: string | null;
  insulin_note: string;
}

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
  /** 降级原因，如预算耗尽 */
  degraded_reason?: string | null;
  refused: boolean;
  refusal_reason: string | null;
}

/** SSE 事件（chat.py _sse 的 payload.type 分支，逐字对齐） */
export type SseEvent =
  | { type: "run"; run_id: string }
  | { type: "node"; node: string; status: string; elapsed_ms?: number }
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
  /** 运行所属会话，用于把同一会话的多轮问答归到一组 */
  session_id?: string | null;
  /** 运行创建时间（UTC ISO），回放时保留原始时间 */
  created_at?: string | null;
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
  /** 拍照运行的图片 id 与识别清单，回放时重建餐盘摘要 */
  image_id?: string | null;
  food_items?: FoodItem[];
  /** 用户自填代谢档案（含 BMI），仅作个性化上下文 */
  profile?: Record<string, unknown> | null;
  /** 各图节点耗时与整轮总耗时（毫秒） */
  timings?: { node: string; ms: number }[];
  duration_ms?: number | null;
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
