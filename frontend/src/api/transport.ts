/**
 * 传输层接口：事件/响应结构逐字对齐 backend 契约，不许改。
 * 只有 live 一种实现——后端不可达时必须显式报错，不允许用内置数据冒充回答。
 */
import type { Deliverable, FoodContext, RunSummary, SseEvent, TaskSnapshot } from "../types";

export interface ChatTransport {
  /** POST /api/chat 的 SSE 流 */
  stream(
    question: string,
    sessionId: string,
    signal: AbortSignal,
    food?: FoodContext,
  ): AsyncGenerator<SseEvent>;
  /** GET /api/tasks/{run_id} */
  getTask(runId: string): Promise<TaskSnapshot | null>;
  /** GET /api/runs：持久化的历史运行列表 */
  listRuns(limit?: number): Promise<RunSummary[]>;
  /** POST /api/tasks/{run_id}/approve：放行断点，返回兜底 Deliverable（或随后轮询 getTask） */
  approve(runId: string): Promise<{ deliverable: Deliverable | null }>;
}
