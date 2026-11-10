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
  RunSummary,
  SseEvent,
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
  startedAt: number;
  finishedAt: number | null;
}

interface RunsContextValue {
  runs: RunState[];
  activeRunKey: string | null;
  setActiveRunKey: (key: string | null) => void;
  startRun: (question: string) => void;
  approveRun: (key: string) => Promise<void>;
  /** SQLite 持久化的历史运行（重启后仍可回放） */
  history: RunSummary[];
  reloadHistory: () => Promise<void>;
  /** 从后端快照恢复一条历史 run 到轨迹页 */
  restoreRun: (runId: string) => Promise<void>;
  transportKind: "mock" | "live" | "probing";
}

const RunsContext = createContext<RunsContextValue | null>(null);

let seq = 0;
const nextKey = () => `run-${++seq}`;

export function RunsProvider({ children }: { children: ReactNode }) {
  const [runs, setRuns] = useState<RunState[]>([]);
  const [history, setHistory] = useState<RunSummary[]>([]);
  const [activeRunKey, setActiveRunKey] = useState<string | null>(null);
  const [transportKind, setTransportKind] = useState<"mock" | "live" | "probing">(
    import.meta.env?.VITE_MOCK === "1" ? "mock" : "probing",
  );
  const transportRef = useRef<ChatTransport>(mockTransport);
  const abortRef = useRef<AbortController | null>(null);
  const sessionSeq = useRef(0);

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
    (question: string) => {
      const key = nextKey();
      const sessionId = `ui-${Date.now()}-${++sessionSeq.current}`;
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
        try {
          for await (const ev of transport.stream(question, sessionId, ctrl.signal)) {
            const now = Date.now();
            patchRun(key, (r) => reduceEvent(r, ev, now, () => now - lastAt));
            lastAt = now;
            if (ev.type === "run") {
              // live 模式：拿到 run_id 后立即拉快照拿 node_results（mock 则等 done）
              void transport.getTask(ev.run_id).then((snap) => {
                if (snap) {
                  patchRun(key, (r) => ({
                    ...r,
                    runId: r.runId ?? ev.run_id,
                    nodeResults: snap.node_results ?? r.nodeResults,
                    dag: snap.dag ?? r.dag,
                    evidencePool: snap.evidence ?? r.evidencePool,
                    roundNo: snap.round_no ?? r.roundNo,
                  }));
                }
              });
            }
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

  const restoreRun = useCallback(
    async (runId: string) => {
      const existing = runs.find((r) => r.runId === runId);
      if (existing) {
        setActiveRunKey(existing.key);
        return;
      }
      const snap = await transportRef.current.getTask(runId);
      if (!snap) return;
      const key = nextKey();
      const run: RunState = {
        key,
        runId,
        question: snap.question ?? "",
        sessionId: "",
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
        source: snap.deliverable ? "live" : "mock",
        startedAt: Date.now(),
        finishedAt: Date.now(),
      };
      setRuns((prev) => [...prev, run]);
      setActiveRunKey(key);
    },
    [runs],
  );

  const value = useMemo<RunsContextValue>(
    () => ({
      runs,
      activeRunKey,
      setActiveRunKey,
      startRun,
      approveRun,
      history,
      reloadHistory,
      restoreRun,
      transportKind,
    }),
    [runs, activeRunKey, startRun, approveRun, history, reloadHistory, restoreRun, transportKind],
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
