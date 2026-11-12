/**
 * live 传输：fetch 读 SSE（POST /api/chat 是 StreamingResponse，不是 EventSource）。
 * 事件格式来自 backend/app/api/chat.py：`data: {json}\n\n`。
 */
import type {
  Deliverable,
  FoodAnalysis,
  GlucoseReading,
  MealDraft,
  MealRecord,
  RunSummary,
  SseEvent,
  TaskSnapshot,
} from "../types";
import type { ChatTransport } from "./transport";

const TOKEN_KEY = "glucoguard.token";

export interface Account {
  user_id: string;
  username: string;
  created_at: string;
}

export interface Session {
  token: string;
  expires_at: string;
  user: Account;
}

/** 登录令牌只存本机浏览器；没有令牌时后端按单机演示身份 local 记账。 */
export function readToken(): string {
  if (typeof localStorage === "undefined") return "";
  try {
    return localStorage.getItem(TOKEN_KEY)?.trim() ?? "";
  } catch {
    return "";
  }
}

export function saveToken(token: string): void {
  const value = token.trim();
  if (value) localStorage.setItem(TOKEN_KEY, value);
  else localStorage.removeItem(TOKEN_KEY);
}

/** 任何个人接口回 401 都说明会话没了：由 AuthProvider 清令牌、回到未登录态。 */
let unauthorizedHandler: (() => void) | null = null;

export function onUnauthorized(fn: () => void): () => void {
  unauthorizedHandler = fn;
  return () => {
    if (unauthorizedHandler === fn) unauthorizedHandler = null;
  };
}

/** 身份由后端从令牌解析，请求体里不再带 user_id。 */
function authHeaders(extra?: Record<string, string>): Record<string, string> {
  const token = readToken();
  return { ...extra, ...(token ? { authorization: `Bearer ${token}` } : {}) };
}

async function detailOf(resp: Response, action: string): Promise<string> {
  try {
    const body = (await resp.json()) as { detail?: unknown };
    if (typeof body.detail === "string" && body.detail) return body.detail;
  } catch {
    // 非 JSON 错误体，保留状态码文案
  }
  return `${action}（HTTP ${resp.status}）`;
}

/** 401 要说清是登录过期，不能和「后端挂了」混为一谈。 */
async function failure(resp: Response, action: string): Promise<Error> {
  if (resp.status === 401) {
    unauthorizedHandler?.();
    return new Error("登录已过期，请重新登录后继续");
  }
  return new Error(await detailOf(resp, action));
}

async function credentials(path: string, username: string, password: string, action: string): Promise<Session> {
  const resp = await fetch(path, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ username, password }),
  });
  // 登录失败的 401 是「密码不对」，不是会话过期，不能触发全局登出
  if (!resp.ok) throw new Error(await detailOf(resp, action));
  return (await resp.json()) as Session;
}

export function registerAccount(username: string, password: string): Promise<Session> {
  return credentials("/api/auth/register", username, password, "注册失败");
}

export function loginAccount(username: string, password: string): Promise<Session> {
  return credentials("/api/auth/login", username, password, "登录失败");
}

export async function logoutAccount(): Promise<void> {
  await fetch("/api/auth/logout", { method: "POST", headers: authHeaders() }).catch(() => undefined);
}

/** /api/auth/me 不会 401：expired=true 表示本地还留着失效令牌。 */
export async function currentAccount(): Promise<{ user: Account | null; expired: boolean }> {
  const resp = await fetch("/api/auth/me", { headers: authHeaders({ accept: "application/json" }) });
  if (!resp.ok) throw new Error(await detailOf(resp, "读取登录状态失败"));
  const data = (await resp.json()) as { user: Account | null; expired?: boolean };
  return { user: data.user ?? null, expired: Boolean(data.expired) };
}

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

/** 读取「代谢档案」页保存的本地资料，转成后端 ProfileIn；没有填写就返回 undefined。 */
function readProfile() {
  if (typeof localStorage === "undefined") return undefined;
  try {
    const raw = localStorage.getItem("glucoguard.profile");
    if (!raw) return undefined;
    const p = JSON.parse(raw) as Record<string, unknown>;
    const num = (v: unknown) => {
      const n = Number(v);
      return Number.isFinite(n) && n > 0 ? n : undefined;
    };
    const profile = {
      height_cm: num(p.height),
      weight_kg: num(p.weight),
      age: num(p.age),
      activity: typeof p.activity === "string" ? p.activity : undefined,
      goal: typeof p.goal === "string" ? p.goal : undefined,
    };
    return Object.values(profile).some((v) => v !== undefined) ? profile : undefined;
  } catch {
    return undefined;
  }
}

export type BackendProbe = "live" | "unauthorized" | "offline";

export async function probeBackend(timeoutMs = 2500): Promise<BackendProbe> {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), timeoutMs);
  try {
    const resp = await fetch(`/api/runs?limit=1`, {
      signal: ctrl.signal,
      headers: authHeaders({ accept: "application/json" }),
    });
    // 后端在应答但拒绝身份：属于「登录过期」，不是「后端不可达」
    if (resp.status === 401) return "unauthorized";
    // 必须确认是后端在应答：dev 代理在后端挂掉时也会回 500，只看 status>0 会误判为可达
    if (!resp.ok) return "offline";
    const data = (await resp.json()) as { runs?: unknown };
    return Array.isArray(data.runs) ? "live" : "offline";
  } catch {
    return "offline";
  } finally {
    clearTimeout(timer);
  }
}

export async function getTask(runId: string): Promise<TaskSnapshot | null> {
  try {
    const resp = await fetch(`/api/tasks/${encodeURIComponent(runId)}`, { headers: authHeaders() });
    if (!resp.ok) return null;
    return (await resp.json()) as TaskSnapshot;
  } catch {
    return null;
  }
}

export async function listRuns(limit = 50): Promise<RunSummary[]> {
  try {
    const resp = await fetch(`/api/runs?limit=${limit}`, { headers: authHeaders() });
    if (!resp.ok) return [];
    const data = (await resp.json()) as { runs?: RunSummary[] };
    return data.runs ?? [];
  } catch {
    return [];
  }
}

export async function analyzeFood(file: File): Promise<FoodAnalysis> {
  const form = new FormData();
  form.append("file", file);
  const resp = await fetch(`/api/food/analyze`, { method: "POST", headers: authHeaders(), body: form });
  if (!resp.ok) throw await failure(resp, "识别失败");
  return (await resp.json()) as FoodAnalysis;
}

/** 读失败必须抛出：返回空数组会被上层当成“没有记录”，把后端故障说成空档案。 */
export async function listMeals(limit = 50): Promise<MealRecord[]> {
  const resp = await fetch(`/api/meals?limit=${limit}`, { headers: authHeaders() });
  if (!resp.ok) throw await failure(resp, "读取餐食记录失败");
  const data = (await resp.json()) as { meals?: MealRecord[] };
  return data.meals ?? [];
}

export async function createMeal(draft: MealDraft): Promise<MealRecord> {
  const resp = await fetch(`/api/meals`, {
    method: "POST",
    headers: authHeaders({ "content-type": "application/json" }),
    body: JSON.stringify(draft),
  });
  if (!resp.ok) throw await failure(resp, "记录失败");
  const data = (await resp.json()) as { meal: MealRecord };
  return data.meal;
}

export async function updateMeal(
  mealId: string,
  patch: Partial<Pick<MealDraft, "eaten_at" | "meal_type" | "foods" | "note" | "insulin_note">>,
): Promise<MealRecord> {
  const resp = await fetch(`/api/meals/${encodeURIComponent(mealId)}`, {
    method: "PATCH",
    headers: authHeaders({ "content-type": "application/json" }),
    body: JSON.stringify(patch),
  });
  if (!resp.ok) throw await failure(resp, "更新失败");
  return ((await resp.json()) as { meal: MealRecord }).meal;
}

export async function deleteMeal(mealId: string): Promise<void> {
  const resp = await fetch(`/api/meals/${encodeURIComponent(mealId)}`, {
    method: "DELETE",
    headers: authHeaders(),
  });
  if (!resp.ok) throw await failure(resp, "删除失败");
}

export async function addGlucose(
  mealId: string,
  valueMmol: number,
  minutesAfter = 120,
  measuredAt?: string,
): Promise<GlucoseReading> {
  const resp = await fetch(`/api/meals/${encodeURIComponent(mealId)}/glucose`, {
    method: "POST",
    headers: authHeaders({ "content-type": "application/json" }),
    body: JSON.stringify({
      value_mmol: valueMmol,
      minutes_after: minutesAfter,
      measured_at: measuredAt ?? null,
    }),
  });
  if (!resp.ok) throw await failure(resp, "血糖记录失败");
  return ((await resp.json()) as { reading: GlucoseReading }).reading;
}

export async function deleteGlucose(mealId: string, readingId: string): Promise<void> {
  const resp = await fetch(
    `/api/meals/${encodeURIComponent(mealId)}/glucose/${encodeURIComponent(readingId)}`,
    { method: "DELETE", headers: authHeaders() },
  );
  if (!resp.ok) throw await failure(resp, "删除血糖失败");
}

export const liveTransport: ChatTransport = {
  async *stream(question, sessionId, signal, food) {
    const resp = await fetch(`/api/chat`, {
      method: "POST",
      headers: authHeaders({ "content-type": "application/json" }),
      body: JSON.stringify({
        session_id: sessionId,
        question,
        ...(food ? { image_id: food.image_id, food_items: food.food_items } : {}),
        profile: readProfile(),
      }),
      signal,
    });
    if (!resp.ok) throw await failure(resp, "提问失败");
    if (!resp.body) throw new Error("后端 /api/chat 未返回流式响应");
    yield* parseSse(resp.body, signal);
  },

  getTask,
  listRuns,

  async approve(runId): Promise<{ deliverable: Deliverable | null }> {
    // 契约：POST /api/tasks/{run_id}/approve 放行断点。
    // 兼容三种后端实现：直接返回 JSON（含 deliverable）、返回 SSE、或返回空由前端轮询。
    const resp = await fetch(`/api/tasks/${encodeURIComponent(runId)}/approve`, {
      method: "POST",
      headers: authHeaders({ "content-type": "application/json" }),
      body: JSON.stringify({ action: "approve" }),
    });
    if (!resp.ok) throw await failure(resp, "放行失败");
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