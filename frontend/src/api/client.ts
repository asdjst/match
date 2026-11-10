/**
 * live 传输：fetch 读 SSE（POST /api/chat 是 StreamingResponse，不是 EventSource）。
 * 事件格式来自 backend/app/api/chat.py：`data: {json}\n\n`。
 */
import type { Deliverable, RunSummary, SseEvent, TaskSnapshot } from "../types";
import type { ChatTransport } from "./transport";

/** 逐块解析 SSE 字节流为事件对象 */
async function* parseSse(
  body: ReadableStream<Uint8Array>,
  signal: AbortSignal,
): AsyncGenerator<SseEvent> {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  try {
    while (!signal.aborted) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      let sep: number;
      // 事件以空行分隔（chat.py: f"data: {json}\n\n"）
      while ((sep = buffer.indexOf("\n\n")) !== -1) {
        const block = buffer.slice(0, sep);
        buffer = buffer.slice(sep + 2);
        for (const line of block.split("\n")) {
          if (!line.startsWith("data: ")) continue;
          const raw = line.slice("data: ".length).trim();
          if (!raw) continue;
          try {
            yield JSON.parse(raw) as SseEvent;
          } catch {
            // 忽略无法解析的残包，保持与 live_e2e.py 相同的容错策略
          }
        }
      }
    }
  } finally {
    reader.releaseLock();
  }
}

export async function probeBackend(timeoutMs = 2500): Promise<boolean> {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), timeoutMs);
  try {
    // 任意 run_id 都会 404，但只要收到 HTTP 响应即说明后端可达
    const resp = await fetch(`/api/tasks/__probe__`, {
      signal: ctrl.signal,
      headers: { accept: "application/json" },
    });
    return resp.status > 0;
  } catch {
    return false;
  } finally {
    clearTimeout(timer);
  }
}

export async function getTask(runId: string): Promise<TaskSnapshot | null> {
  try {
    const resp = await fetch(`/api/tasks/${encodeURIComponent(runId)}`);
    if (!resp.ok) return null;
    return (await resp.json()) as TaskSnapshot;
  } catch {
    return null;
  }
}

export async function listRuns(limit = 50): Promise<RunSummary[]> {
  try {
    const resp = await fetch(`/api/runs?limit=${limit}`);
    if (!resp.ok) return [];
    const data = (await resp.json()) as { runs?: RunSummary[] };
    return data.runs ?? [];
  } catch {
    return [];
  }
}

export const liveTransport: ChatTransport = {
  kind: "live",

  async *stream(question, sessionId, signal) {
    const resp = await fetch(`/api/chat`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ session_id: sessionId, question }),
      signal,
    });
    if (!resp.ok || !resp.body) {
      throw new Error(`后端 /api/chat 响应异常（HTTP ${resp.status}）`);
    }
    yield* parseSse(resp.body, signal);
  },

  getTask,
  listRuns,

  async approve(runId): Promise<{ deliverable: Deliverable | null }> {
    // 契约：POST /api/tasks/{run_id}/approve 放行断点。
    // 兼容三种后端实现：直接返回 JSON（含 deliverable）、返回 SSE、或返回空由前端轮询。
    const resp = await fetch(`/api/tasks/${encodeURIComponent(runId)}/approve`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ action: "approve" }),
    });
    if (!resp.ok) {
      throw new Error(`放行失败（HTTP ${resp.status}）`);
    }
    const contentType = resp.headers.get("content-type") ?? "";
    if (contentType.includes("text/event-stream") && resp.body) {
      let deliverable: Deliverable | null = null;
      for await (const ev of parseSse(resp.body, new AbortController().signal)) {
        if (ev.type === "deliverable") deliverable = ev.deliverable;
        if (ev.type === "done") break;
      }
      return { deliverable };
    }
    const text = await resp.text();
    if (text.trim()) {
      try {
        const data = JSON.parse(text) as Record<string, unknown>;
        const d = (data.deliverable ?? data) as Deliverable | undefined;
        if (d && typeof d === "object" && "question" in d) {
          return { deliverable: d as Deliverable };
        }
      } catch {
        // 非 JSON，走轮询
      }
    }
    // 兜底：轮询任务快照等图恢复后的 deliverable
    for (let i = 0; i < 10; i++) {
      await new Promise((r) => setTimeout(r, 1000));
      const snap = await getTask(runId);
      if (snap?.deliverable) return { deliverable: snap.deliverable };
    }
    return { deliverable: null };
  },
};
