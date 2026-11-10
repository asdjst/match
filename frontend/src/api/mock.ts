/**
 * Mock 传输：无后端演示模式（VITE_MOCK=1 或探测后端不可达时启用）。
 * 语料与事件形状逐字对齐 backend：demo_corpus.py / chat.py SSE / writer 断点逻辑，
 * 保证录屏与真实链路观感一致。
 */
import type {
  AgentResult,
  DagNodeSpec,
  Deliverable,
  Evidence,
  SourceRef,
  TaskSnapshot,
} from "../types";
import type { ChatTransport } from "./transport";

const P = (s: Partial<SourceRef> & { modality?: SourceRef["modality"] }): SourceRef => ({
  file_path: null,
  section: null,
  page: null,
  time_code: null,
  modality: "text",
  ...s,
});

/** 与 backend/adapters/retrieval/demo_corpus.py 同源的演示语料 */
const CORPUS: Evidence[] = [
  {
    evidence_id: "E1",
    doc_id: "annual_report",
    quote: "2024年公司实现营业收入120亿元。",
    score: 3.0,
    source: P({ file_path: "A公司2024年报.pdf", section: "87" }),
  },
  {
    evidence_id: "E2",
    doc_id: "annual_report",
    quote: "2023年公司实现营业收入100亿元。",
    score: 3.0,
    source: P({ file_path: "A公司2024年报.pdf", section: "88" }),
  },
  {
    evidence_id: "E3",
    doc_id: "annual_report",
    quote: "2024年公司毛利率为38%，2023年为35%。",
    score: 3.0,
    source: P({ file_path: "A公司2024年报.pdf", section: "90" }),
  },
  {
    evidence_id: "E4",
    doc_id: "annual_report",
    quote: "营收与毛利率概览：2024年营业收入120亿元，毛利率38%；2023年营业收入100亿元，毛利率35%。",
    score: 2.0,
    source: P({ file_path: "A公司2024年报.pdf", section: "92" }),
  },
  {
    evidence_id: "E5",
    doc_id: "report_screenshot",
    quote: "报表截图表格：营业收入 | 120亿 | 100亿；毛利率 | 38% | 35%",
    score: 2.0,
    source: P({ file_path: "报表截图.png", page: 2, modality: "image" }),
  },
  {
    evidence_id: "E6",
    doc_id: "earnings_call",
    quote: "本年度收入增长主要来自核心产品销量提升与新市场放量。",
    score: 2.0,
    source: P({ file_path: "业绩说明会.m4a", time_code: "03:12", modality: "audio" }),
  },
  {
    evidence_id: "E7",
    doc_id: "earnings_call",
    quote: "毛利率改善主要得益于供应链成本优化与产品结构升级。",
    score: 2.0,
    source: P({ file_path: "业绩说明会.m4a", time_code: "07:45", modality: "audio" }),
  },
];

const byId = (id: string): Evidence => {
  const hit = CORPUS.find((e) => e.evidence_id === id);
  if (!hit) throw new Error(`mock 语料缺少 ${id}`);
  return hit;
};

const renumber = (list: Evidence[]): Evidence[] =>
  list.map((e, i) => ({ ...e, evidence_id: `E${i + 1}` }));

interface MockScenario {
  /** 每个节点事件之间的间隔（模拟真实耗时） */
  steps: Array<{ node: string; ms: number }>;
  guard?: { allowed: false; reason: string };
  deliverable: Deliverable | null;
  /** 各节点的 AgentResult（对齐 GET /api/tasks 快照） */
  nodeResults: Record<string, AgentResult>;
  /** planner 任务图（注入场景被 guard 拦截，为 null） */
  dag: TaskSnapshot["dag"];
  roundNo: number;
  verdict: { verdict: "pass" | "send_back"; issues: string[]; send_back_to: string | null; round_no: number } | null;
}

interface MockRunState {
  runId: string;
  question: string;
  scenario: MockScenario;
  deliveredEvents: number; // 已播发的 step 游标
  approved: boolean;
  finished: boolean;
}

const RUNS = new Map<string, MockRunState>();
let runSeq = 0;

const NODE_RES = (
  node_id: string,
  evidence_used: string[],
  extra?: Partial<AgentResult>,
): AgentResult => ({
  node_id,
  status: "done",
  output: null,
  evidence_used,
  block_reason: null,
  ...extra,
});

/** planner 任务图（对齐 core/schemas/dag.py：mock 只含 retriever/executor 节点） */
const dagNodes = (specs: Array<Partial<DagNodeSpec> & Pick<DagNodeSpec, "node_id" | "role">>): DagNodeSpec[] =>
  specs.map((s) => ({
    instruction: "",
    depends_on: [],
    budget: { max_steps: 8, max_rounds: 3, timeout_s: 120 },
    tool: null,
    query: null,
    ...s,
  }));

// ————————————————— 各演示场景（预置会话） —————————————————

function factScenario(question: string): MockScenario {
  const citations = renumber([byId("E1"), byId("E5"), byId("E6")]);
  const [c1, c2, c3] = citations;
  return {
    steps: [
      { node: "planner", ms: 650 },
      { node: "retriever", ms: 900 },
      { node: "analyst", ms: 1050 },
      { node: "critic", ms: 550 },
      { node: "writer", ms: 500 },
    ],
    deliverable: {
      question,
      assertions: [
        { text: "2024年公司实现营业收入120亿元。", cites: [c1.evidence_id] },
        { text: "报表截图表格同样记录营业收入为120亿元、毛利率38%。", cites: [c2.evidence_id] },
        { text: "管理层表示收入增长主要来自核心产品销量提升与新市场放量。", cites: [c3.evidence_id] },
      ],
      citations,
      trace_id: "",
      confidence: 0.84,
      confidence_source: "llm",
      degraded: false,
      refused: false,
      refusal_reason: null,
    },
    nodeResults: {
      planner: NODE_RES("planner", []),
      retriever: NODE_RES("retriever", citations.map((c) => c.evidence_id), {
        retrievals: [
          { channel: "local", hits: 6, latency_ms: 840, status: "ok" },
          { channel: "web", hits: 2, latency_ms: 1600, status: "ok" },
          { channel: "cloud", hits: 0, latency_ms: 0, status: "未配置" },
        ],
      }),
      analyst: NODE_RES("analyst", [c1.evidence_id, c2.evidence_id, c3.evidence_id]),
      critic: NODE_RES("critic", []),
      writer: NODE_RES("writer", citations.map((c) => c.evidence_id)),
    },
    dag: {
      question,
      nodes: dagNodes([
        {
          node_id: "r1",
          role: "retriever",
          instruction: "检索公司营业收入相关证据",
          query: question,
        },
      ]),
    },
    roundNo: 0,
    verdict: { verdict: "pass", issues: [], send_back_to: null, round_no: 0 },
  };
}

function calcScenario(question: string): MockScenario {
  const citations = renumber([byId("E1"), byId("E2"), byId("E5"), byId("E4")]);
  // executor 的工具证据（对齐 roles.py executor：tool://growth_rate，score 3.0）
  const toolEv: Evidence = {
    evidence_id: `E${citations.length + 1}`,
    doc_id: "tool",
    quote: "工具计算：120.0 对比 100.0 → 20.0%",
    score: 3.0,
    source: P({ file_path: "tool://growth_rate" }),
  };
  const all = [...citations, toolEv];
  const c1 = citations[0];
  const c2 = citations[1];
  return {
    steps: [
      { node: "planner", ms: 700 },
      { node: "retriever", ms: 850 },
      { node: "executor", ms: 600 },
      { node: "analyst", ms: 950 },
      { node: "critic", ms: 500 },
      { node: "writer", ms: 450 },
    ],
    deliverable: {
      question,
      assertions: [
        { text: "2024年营业收入为120亿元，2023年为100亿元。", cites: [c1.evidence_id, c2.evidence_id] },
        { text: "2024年营业收入相比2023年增长20.0%。", cites: [toolEv.evidence_id] },
      ],
      citations: all,
      trace_id: "",
      confidence: 0.79,
      confidence_source: "llm",
      degraded: false,
      refused: false,
      refusal_reason: null,
    },
    nodeResults: {
      planner: NODE_RES("planner", []),
      retriever: NODE_RES("retriever", [c1.evidence_id, c2.evidence_id]),
      executor: NODE_RES("executor", [toolEv.evidence_id], {
        output: { args: { a: 120.0, b: 100.0 }, result: 20.0, unit: "%" },
      }),
      analyst: NODE_RES("analyst", all.map((c) => c.evidence_id)),
      critic: NODE_RES("critic", []),
      writer: NODE_RES("writer", all.map((c) => c.evidence_id)),
    },
    dag: {
      question,
      nodes: dagNodes([
        {
          node_id: "r1",
          role: "retriever",
          instruction: "检索近两年营业收入数据",
          query: question,
        },
        {
          node_id: "x1",
          role: "executor",
          instruction: "计算营收同比增长率",
          tool: "growth_rate",
          depends_on: ["r1"],
        },
      ]),
    },
    roundNo: 0,
    verdict: { verdict: "pass", issues: [], send_back_to: null, round_no: 0 },
  };
}

function refusalScenario(question: string): MockScenario {
  return {
    steps: [
      { node: "planner", ms: 600 },
      { node: "retriever", ms: 800 },
      { node: "analyst", ms: 900 },
      { node: "critic", ms: 550 },
      { node: "writer", ms: 420 },
    ],
    deliverable: {
      question,
      assertions: [],
      citations: [],
      trace_id: "",
      confidence: 0.0,
      degraded: false,
      refused: true,
      refusal_reason: "置信度 0.00 低于阈值 0.45",
    },
    nodeResults: {
      planner: NODE_RES("planner", []),
      retriever: NODE_RES("retriever", []),
      analyst: NODE_RES("analyst", []),
      critic: NODE_RES("critic", []),
      writer: NODE_RES("writer", []),
    },
    dag: {
      question,
      nodes: dagNodes([
        { node_id: "r1", role: "retriever", instruction: "检索与问题相关的财报证据", query: question },
      ]),
    },
    roundNo: 0,
    verdict: { verdict: "pass", issues: [], send_back_to: null, round_no: 0 },
  };
}

/** 人工断点：审校连续打回至上限，图在 writer 前暂停，等 POST approve 放行 */
function breakpointScenario(_question: string): MockScenario {
  const citations = renumber([byId("E3"), byId("E7")]);
  const [c1, c2] = citations;
  return {
    steps: [
      { node: "planner", ms: 650 },
      { node: "retriever", ms: 850 },
      { node: "analyst", ms: 900 },
      { node: "critic", ms: 600 },
      { node: "retriever", ms: 800 },
      { node: "analyst", ms: 850 },
      { node: "critic", ms: 600 },
      { node: "retriever", ms: 800 },
      { node: "analyst", ms: 850 },
      { node: "critic", ms: 600 },
      // writer interrupt()：流在此收尾，无 deliverable → 前端显示“等待放行”
    ],
    deliverable: null,
    nodeResults: {
      planner: NODE_RES("planner", []),
      retriever: NODE_RES("retriever", citations.map((c) => c.evidence_id)),
      analyst: NODE_RES("analyst", [c1.evidence_id, c2.evidence_id]),
      critic: NODE_RES("critic", []),
      writer: NODE_RES("writer", [], { status: "needs_human", block_reason: "审校打回已达上限，需人工放行后输出兜底结论" }),
    },
    dag: {
      question: _question,
      nodes: dagNodes([
        {
          node_id: "r1",
          role: "retriever",
          instruction: "检索毛利率历史数据与改善原因",
          query: _question,
        },
      ]),
    },
    roundNo: 3,
    verdict: {
      verdict: "send_back",
      issues: ["2025年毛利率预测缺少证据支撑", "断言缺引用：2025年毛利率预测"],
      send_back_to: "retriever",
      round_no: 3,
    },
  };
}

/** 放行后的兜底交付物（对齐 writer：degraded + refused + 兜底断言） */
function breakpointApprovedDeliverable(question: string): Deliverable {
  const citations = renumber([byId("E3"), byId("E7")]);
  const [c1, c2] = citations;
  return {
    question,
    assertions: [
      { text: "2024年公司毛利率为38%，2023年为35%，同比提升3个百分点。", cites: [c1.evidence_id] },
      { text: "毛利率改善主要得益于供应链成本优化与产品结构升级。", cites: [c2.evidence_id] },
      { text: "按近两年改善趋势外推，2025年毛利率有望升至40%左右。（推断，无直接证据）", cites: [], inferred: true },
    ],
    citations,
    trace_id: "",
    confidence: 0.58,
    degraded: true,
    refused: true,
    refusal_reason: "已达最大打回轮数（3），人工已放行，输出兜底结论",
  };
}

const injectionScenario = (question: string): MockScenario => ({
  steps: [],
  guard: { allowed: false, reason: "检测到提示注入（指令覆盖、数据外泄）" },
  deliverable: {
    question,
    assertions: [],
    citations: [],
    trace_id: "",
    confidence: 0.0,
    degraded: false,
    refused: true,
    refusal_reason: "检测到提示注入（指令覆盖、数据外泄）",
  },
  nodeResults: {},
  dag: null,
  roundNo: 0,
  verdict: null,
});

// ————————————————— 场景匹配（含关键词兜底检索） —————————————————

const PRESETS: Array<{ match: string[]; build: (q: string) => MockScenario }> = [
  {
    match: ["忽略", "系统提示", "打印你的", "无视", "越狱", "developer mode"],
    build: injectionScenario,
  },
  { match: ["毛利率", "预测", "2025"], build: breakpointScenario },
  { match: ["增长", "增长了多少", "相比", "对比", "提升"], build: calcScenario },
  { match: ["量子", "薛定谔", "方程", "相对论", "python", "股票推荐"], build: refusalScenario },
  { match: [], build: factScenario },
];

function pickScenario(question: string): MockScenario {
  for (const p of PRESETS) {
    if (p.match.some((m) => question.includes(m))) return p.build(question);
  }
  return factScenario(question);
}

// ————————————————— Mock 传输实现 —————————————————

const sleep = (ms: number) => new Promise<void>((r) => setTimeout(r, ms));

function snapshotOf(state: MockRunState): TaskSnapshot {
  return {
    run_id: state.runId,
    question: state.question,
    round_no: state.scenario.roundNo,
    node_results: state.scenario.nodeResults,
    verdict: state.scenario.verdict,
    deliverable: state.approved && state.scenario.deliverable === null
      ? breakpointApprovedDeliverable(state.question)
      : state.scenario.deliverable,
    dag: state.scenario.dag,
    evidence: null,
  };
}

export const mockTransport: ChatTransport = {
  kind: "mock",

  async *stream(question, _sessionId, signal) {
    const runId = `mock-${String(++runSeq).padStart(3, "0")}`;
    const scenario = pickScenario(question);
    const state: MockRunState = {
      runId,
      question,
      scenario,
      deliveredEvents: 0,
      approved: false,
      finished: false,
    };
    RUNS.set(runId, state);

    yield { type: "run", run_id: runId };
    if (signal.aborted) return;

    if (scenario.guard) {
      yield { type: "guard", allowed: false, reason: scenario.guard.reason };
    }
    for (const step of scenario.steps) {
      await sleep(step.ms);
      if (signal.aborted) return;
      yield { type: "node", node: step.node, status: "done" };
    }
    if (scenario.deliverable) {
      await sleep(350);
      if (signal.aborted) return;
      yield { type: "deliverable", deliverable: scenario.deliverable };
    }
    state.finished = true;
    yield { type: "done" };
  },

  async getTask(runId) {
    const state = RUNS.get(runId);
    return state ? snapshotOf(state) : null;
  },

  async listRuns() {
    return []; // mock 模式没有持久化历史
  },

  async approve(runId) {
    const state = RUNS.get(runId);
    if (!state) throw new Error(`mock 任务不存在：${runId}`);
    await sleep(900); // 模拟图恢复 + writer 兜底输出
    state.approved = true;
    state.finished = true;
    const deliverable =
      state.scenario.deliverable ?? breakpointApprovedDeliverable(state.question);
    state.scenario = { ...state.scenario, deliverable };
    return { deliverable };
  },
};
