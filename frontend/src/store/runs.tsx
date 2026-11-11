/**
 * 会话/运行状态：ChatPage 与 TracePage 共享。
 * 每次提问生成一条 RunState，SSE 事件增量写入；断点 pending 时可放行。
 */
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import type {
  AgentResult,
  DagPlan,
  Deliverable,
  Evidence,
  FoodContext,
  RunSummary,
  SseEvent,
  TaskSnapshot,
} from "../types";
import { liveTransport, listRuns, probeBackend } from "../api/client";
import { mockTransport } from "../api/mock";
import type { ChatTransport } from "../api/transport";

export type RunPhase = "streaming" | "done" | "interrupted" | "error";

export interface NodeEventLog {
  node: string;
  status: string;
  /** 距上一事件（或提问发起）的毫秒数，端侧计时 */
  durationMs: number;
  at: number;
}

export interface RunState {
  key: string;
  runId: string | null;
  question: string;
  sessionId: string;
  phase: RunPhase;
  guard: { allowed: boolean; reason?: string | null } | null;
  error: string | null;
  deliverable: Deliverable | null;
  nodeEvents: NodeEventLog[];
  /** GET /api/tasks 快照里的 node_results（live 在 done 后补拉；mock 直接内置） */
  nodeResults: Record<string, AgentResult> | null;
  /** planner 任务图与全量证据池（快照补拉，供轨迹页展示各阶段产出） */
  dag: DagPlan | null;
  evidencePool: Record<string, Evidence> | null;
  verdict: { verdict: string; issues: string[]; send_back_to: string | null; round_no: number } | null;
  roundNo: number | null;
  approved: boolean;
  approving: boolean;
  source: "mock" | "live";
  /** 本条提问附带的餐食识别结果（发送后仍保留，供消息里回看） */
  food?: FoodContext;
  startedAt: number;
  finishedAt: number | null;
}

/** 一次会话：同一 session_id 下的多轮问答，左侧历史按它归组 */
export interface Conversation {
  id: string;
  /** 第一句话作为标题 */
  title: string;
  count: number;
  updatedAt: number;
  /** 该会话里已落库的 run id（时间正序），用于点开时回放 */
  runIds: string[];
}

interface RunsContextValue {
  runs: RunState[];
  activeRunKey: string | null;
  setActiveRunKey: (key: string | null) => void;
  /** 当前会话 id：同一会话内的追问共享它，后端据此回填多轮上下文 */
  activeSessionId: string;
  conversations: Conversation[];
  /** 开一段新对话（不删除旧会话，旧会话仍在历史里） */
  newConversation: () => void;
  /** 打开左侧历史里的会话：切到该 session 并补齐未加载的 run */
  openConversation: (conversation: Conversation) => Promise<void>;
  startRun: (question: string, food?: FoodContext) => void;
  approveRun: (key: string) => Promise<void>;
  /** SQLite 持久化的历史运行（重启后仍可回放） */
  history: RunSummary[];
  reloadHistory: () => Promise<void>;
  transportKind: "mock" | "live" | "probing";
}

const RunsContext = createContext<RunsContextValue | null>(null);

let seq = 0;
const nextKey = () => `run-${++seq}`;

let sessionSeq = 0;
const newSessionId = () => `ui-${Date.now()}-${++sessionSeq}`;

export function RunsProvider({ children }: { children: ReactNode }) {
  const [runs, setRuns] = useState<RunState[]>([]);
  const [history, setHistory] = useState<RunSummary[]>([]);
  const [activeRunKey, setActiveRunKey] = useState<string | null>(null);
  const [transportKind, setTransportKind] = useState<"mock" | "live" | "probing">(
    import.meta.env?.VITE_MOCK === "1" ? "mock" : "probing",
  );
  const transportRef = useRef<ChatTransport>(mockTransport);
  const abortRef = useRef<AbortController | null>(null);
  // 会话 id 既要给 React 渲染（侧栏高亮），也要给 startRun 的同步闭包读
  const initialSession = useMemo(() => newSessionId(), []);
  const [activeSessionId, setActiveSessionId] = useState(initialSession);
  const activeSessionRef = useRef(initialSession);

  // finalize 的异步补拉需要一个绕过闭包的出口：注册模块级 patcher
  useEffect(() => {
    const unregister = registerGlobalPatcher((key, patch) => {
      setRuns((prev) => prev.map((r) => (r.key === key ? { ...r, ...patch } : r)));
    });
    return unregister;
  }, []);

  // 启动时探测后端；VITE_MOCK=1 直接 mock
  useEffect(() => {
    if (import.meta.env?.VITE_MOCK === "1") return;
    let cancelled = false;
    probeBackend().then((ok) => {
      if (cancelled) return;
      if (ok) {
        transportRef.current = liveTransport;
        setTransportKind("live");
        void listRuns().then((items) => {
          if (!cancelled) setHistory(items);
        });
      } else {
        transportRef.current = mockTransport;
        setTransportKind("mock");
      }
    });
    return () => {
      cancelled = true;
    };
  }, []);

  const patchRun = useCallback((key: string, patch: (r: RunState) => RunState) => {
    setRuns((prev) => prev.map((r) => (r.key === key ? patch(r) : r)));
  }, []);

  const startRun = useCallback(
    (question: string, food?: FoodContext) => {
      const key = nextKey();
      // 同一会话复用 session_id，后端才能取到最近几轮问答做指代消解
      const sessionId = activeSessionRef.current;
      const run: RunState = {
        key,
        runId: null,
        question,
        sessionId,
        phase: "streaming",
        guard: null,
        error: null,
        deliverable: null,
        nodeEvents: [],
        nodeResults: null,
        dag: null,
        evidencePool: null,
        verdict: null,
        roundNo: null,
        approved: false,
        approving: false,
        source: transportRef.current.kind,
        food,
        startedAt: Date.now(),
        finishedAt: null,
      };
      setRuns((prev) => [...prev, run]);
      setActiveRunKey(key);

      const ctrl = new AbortController();
      abortRef.current = ctrl;
      const transport = transportRef.current;

      void (async () => {
        let lastAt = Date.now();
        let runId: string | null = null;
        let snapshotSeq = 0;
        let appliedSeq = 0;
        const syncSnapshot = (id: string) => {
          const seq = ++snapshotSeq;
          void transport.getTask(id).then((snap) => {
            // 快照按节点事件并发补拉，慢的旧响应不能覆盖新状态
            if (!snap || seq < appliedSeq) return;
            appliedSeq = seq;
            patchRun(key, (r) => ({
              ...r,
              nodeResults: snap.node_results ?? r.nodeResults,
              dag: snap.dag ?? r.dag,
              evidencePool: snap.evidence ?? r.evidencePool,
              verdict: snap.verdict ?? r.verdict,
              roundNo: snap.round_no ?? r.roundNo,
            }));
          });
        };
        try {
          for await (const ev of transport.stream(question, sessionId, ctrl.signal, food)) {
            const now = Date.now();
            patchRun(key, (r) => reduceEvent(r, ev, now, () => now - lastAt));
            lastAt = now;
            if (ev.type === "run") runId = ev.run_id;
            // 每个角色跑完补拉一次快照：思考过程要显示这一步产出了什么
            if (ev.type === "node" && runId) syncSnapshot(runId);
          }
          patchRun(key, (r) => finalize(r, transport));
        } catch (err) {
          if (ctrl.signal.aborted) {
            patchRun(key, (r) => ({ ...r, phase: "error", error: "已手动停止" , finishedAt: Date.now() }));
          } else {
            const message = err instanceof Error ? err.message : String(err);
            patchRun(key, (r) => ({
              ...r,
              phase: "error",
              error: message,
              finishedAt: Date.now(),
            }));
          }
        }
      })();
    },
    [patchRun],
  );

  const approveRun = useCallback(
    async (key: string) => {
      const run = runs.find((r) => r.key === key);
      if (!run?.runId) return;
      patchRun(key, (r) => ({ ...r, approving: true }));
      try {
        const { deliverable } = await transportRef.current.approve(run.runId);
        let final = deliverable;
        if (!final) {
          const snap = await transportRef.current.getTask(run.runId);
          final = snap?.deliverable ?? null;
        }
        patchRun(key, (r) => ({
          ...r,
          approved: true,
          approving: false,
          deliverable: final ?? r.deliverable,
          phase: final ? "done" : r.phase,
          finishedAt: final ? Date.now() : r.finishedAt,
        }));
      } catch (err) {
        const message = err instanceof Error ? err.message : String(err);
        patchRun(key, (r) => ({ ...r, approving: false, error: message }));
      }
    },
    [patchRun, runs],
  );

  const reloadHistory = useCallback(async () => {
    if (transportRef.current.kind !== "live") return;
    setHistory(await listRuns());
  }, []);

  // 一轮跑完就刷新历史，左侧会话栏不用等切页
  const phaseSig = useMemo(() => runs.map((r) => `${r.runId}:${r.phase}`).join(","), [runs]);
  useEffect(() => {
    if (transportKind === "live") void reloadHistory();
  }, [phaseSig, transportKind, reloadHistory]);

  /** 后端快照 → 可回放的 RunState */
  const adoptSnapshot = useCallback((runId: string, snap: TaskSnapshot, sessionId: string): RunState => {
    const items = snap.food_items ?? [];
    const created = Date.parse(snap.created_at ?? "");
    const startedAt = Number.isNaN(created) ? Date.now() : created;
    return {
      key: nextKey(),
      runId,
      question: snap.question ?? "",
      sessionId: sessionId || snap.session_id || "",
      phase: snap.pending_human ? "interrupted" : "done",
      guard: null,
      error: null,
      deliverable: snap.deliverable,
      nodeEvents: [],
      nodeResults: snap.node_results,
      dag: snap.dag,
      evidencePool: snap.evidence,
      verdict: snap.verdict,
      roundNo: snap.round_no,
      approved: false,
      approving: false,
      source: "live",
      food:
        items.length > 0
          ? {
              image_id: snap.image_id ?? "",
              food_items: items,
              photo_url: snap.image_id ? `/api/food/images/${snap.image_id}` : null,
            }
          : undefined,
      startedAt,
      finishedAt: startedAt,
    };
  }, []);

  const newConversation = useCallback(() => {
    const sid = newSessionId();
    activeSessionRef.current = sid;
    setActiveSessionId(sid);
    setActiveRunKey(null);
  }, []);

  const openConversation = useCallback(
    async (conversation: Conversation) => {
      activeSessionRef.current = conversation.id;
      setActiveSessionId(conversation.id);
      const loaded = new Set(runs.map((r) => r.runId).filter((id): id is string => Boolean(id)));
      const added: RunState[] = [];
      for (const runId of conversation.runIds) {
        if (loaded.has(runId)) continue;
        const snap = await transportRef.current.getTask(runId);
        if (snap) added.push(adoptSnapshot(runId, snap, conversation.id));
      }
      if (added.length) setRuns((prev) => [...prev, ...added]);
      const lastAdded = added[added.length - 1];
      if (lastAdded) {
        setActiveRunKey(lastAdded.key);
      } else {
        const lastRunId = conversation.runIds[conversation.runIds.length - 1];
        const existing = runs.find((r) => r.runId === lastRunId);
        if (existing) setActiveRunKey(existing.key);
      }
    },
    [runs, adoptSnapshot],
  );

  // 会话列表：内存中的 run 与 SQLite 历史合并，按 session_id 归组、按 run_id 去重
  const conversations = useMemo<Conversation[]>(() => {
    type Entry = { question: string; at: number; runId: string | null };
    const groups = new Map<string, Entry[]>();
    const seen = new Set<string>();
    const push = (id: string, entry: Entry) => {
      const list = groups.get(id) ?? [];
      list.push(entry);
      groups.set(id, list);
    };
    for (const run of runs) {
      push(run.sessionId || `run:${run.runId ?? run.key}`, {
        question: run.question,
        at: run.startedAt,
        runId: run.runId,
      });
      if (run.runId) seen.add(run.runId);
    }
    for (const item of history) {
      if (seen.has(item.run_id)) continue;
      const at = Date.parse(item.created_at);
      push(item.session_id || `run:${item.run_id}`, {
        question: item.question,
        at: Number.isNaN(at) ? 0 : at,
        runId: item.run_id,
      });
    }
    return [...groups.entries()]
      .map(([id, entries]) => {
        const ordered = [...entries].sort((a, b) => a.at - b.at);
        const runIds = [...new Set(ordered.map((e) => e.runId).filter((v): v is string => Boolean(v)))];
        return {
          id,
          title: ordered[0].question,
          count: ordered.length,
          updatedAt: ordered[ordered.length - 1].at,
          runIds,
        };
      })
      .sort((a, b) => b.updatedAt - a.updatedAt);
  }, [runs, history]);

  const value = useMemo<RunsContextValue>(
    () => ({
      runs,
      activeRunKey,
      setActiveRunKey,
      activeSessionId,
      conversations,
      newConversation,
      openConversation,
      startRun,
      approveRun,
      history,
      reloadHistory,
      transportKind,
    }),
    [
      runs,
      activeRunKey,
      activeSessionId,
      conversations,
      newConversation,
      openConversation,
      startRun,
      approveRun,
      history,
      reloadHistory,
      transportKind,
    ],
  );

  return <RunsContext.Provider value={value}>{children}</RunsContext.Provider>;
}

export function useRuns(): RunsContextValue {
  const ctx = useContext(RunsContext);
  if (!ctx) throw new Error("useRuns 必须在 RunsProvider 内使用");
  return ctx;
}

/** SSE 事件 → RunState 归约 */
function reduceEvent(r: RunState, ev: SseEvent, now: number, deltaMs: () => number): RunState {
  switch (ev.type) {
    case "run":
      return { ...r, runId: ev.run_id };
    case "guard":
      return { ...r, guard: { allowed: ev.allowed, reason: ev.reason } };
    case "node":
      return {
        ...r,
        nodeEvents: [
          ...r.nodeEvents,
          { node: ev.node, status: ev.status, durationMs: deltaMs(), at: now },
        ],
      };
    case "deliverable":
      return { ...r, deliverable: ev.deliverable };
    case "error":
      return { ...r, error: ev.message };
    case "done":
      return r;
    default:
      return r;
  }
}

/** 流结束：有 deliverable → done；无 deliverable → writer 人工断点 pending */
function finalize(r: RunState, transport: ChatTransport): RunState {
  const finishedAt = Date.now();
  if (r.deliverable) {
    // live：结束后补拉快照，拿 node_results / verdict / round_no 丰富轨迹页
    if (transport.kind === "live" && r.runId) {
      void transport.getTask(r.runId).then((snap) => {
        if (!snap) return;
        setRunsGlobal(r.key, {
          nodeResults: snap.node_results ?? null,
          dag: snap.dag ?? null,
          evidencePool: snap.evidence ?? null,
          verdict: snap.verdict ?? null,
          roundNo: snap.round_no ?? null,
        });
      });
    }
    return { ...r, phase: "done", finishedAt };
  }
  return { ...r, phase: "interrupted", finishedAt };
}

// finalize 里异步补拉的出口：直接复用 provider 的 setState 不方便，
// 用模块级句柄桥接（RunsProvider 挂载时注册）。
let globalPatcher: ((key: string, patch: Partial<RunState>) => void) | null = null;
function setRunsGlobal(key: string, patch: Partial<RunState>) {
  globalPatcher?.(key, patch);
}

export function registerGlobalPatcher(
  fn: (key: string, patch: Partial<RunState>) => void,
): () => void {
  globalPatcher = fn;
  return () => {
    if (globalPatcher === fn) globalPatcher = null;
  };
}
