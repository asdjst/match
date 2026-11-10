import json
import uuid
from typing import AsyncIterator

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from langgraph.errors import GraphRecursionError
from pydantic import BaseModel, Field

from core.graph.state import GraphState
from core.schemas.deliverable import Deliverable

router = APIRouter()


class ChatRequest(BaseModel):
    session_id: str = "default"
    question: str = Field(min_length=1)


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


@router.post("/api/chat")
async def chat(req: ChatRequest, request: Request) -> StreamingResponse:
    state = request.app.state

    async def gen() -> AsyncIterator[str]:
        run_id = str(uuid.uuid4())
        yield _sse({"type": "run", "run_id": run_id})

        trace_id = state.tracer.start("chat", {"run_id": run_id, "session_id": req.session_id, "question": req.question})

        def persist(record: dict) -> None:
            try:
                state.store.save_run(run_id, record, req.session_id, req.question)
            except Exception as exc:  # 落库失败不影响在线交付
                state.tracer.event(trace_id, "store_error", {"error": str(exc)[:200]})

        verdict = state.guard.inspect_input(req.question)
        if not verdict.allowed:
            deliverable = Deliverable(
                question=req.question,
                trace_id=run_id,
                refused=True,
                refusal_reason=verdict.reason or "输入被安全策略拦截",
            )
            state.runs[run_id] = {"question": req.question, "round_no": 0, "node_results": {}, "deliverable": deliverable.model_dump()}
            persist(state.runs[run_id])
            state.tracer.event(trace_id, "guard", {"allowed": False, "reason": verdict.reason})
            yield _sse({"type": "guard", "allowed": False, "reason": verdict.reason})
            yield _sse({"type": "deliverable", "deliverable": deliverable.model_dump()})
            state.tracer.end(trace_id, {"refused": True, "blocked_by": "guard"})
            yield _sse({"type": "done"})
            return

        question = state.guard.sanitize(req.question)
        init: GraphState = {
            "session_id": req.session_id,
            "question": question,
            "trace_id": run_id,
            "round_no": 0,
            "evidence": {},
            "node_results": {},
        }
        merged: dict = dict(init)
        config = {"configurable": {"thread_id": run_id}, "recursion_limit": 30}
        interrupted = False
        try:
            async for chunk in state.graph.astream(init, config, stream_mode="updates"):
                if "__interrupt__" in chunk:
                    intr = chunk["__interrupt__"][0]
                    payload = intr.value if isinstance(intr.value, dict) else {"reason": str(intr.value)}
                    interrupted = True
                    merged |= {"pending_human": True, "human_gate": payload}
                    yield _sse({"type": "needs_human", "run_id": run_id, **payload})
                    break
                for node, delta in chunk.items():
                    merged.update(delta)
                    state.tracer.event(trace_id, f"node:{node}", {"status": "done"})
                    yield _sse({"type": "node", "node": node, "status": "done"})
        except GraphRecursionError:
            yield _sse({"type": "error", "message": "超过图循环上限"})
            state.tracer.event(trace_id, "error", {"message": "超过图循环上限"})
        except Exception as e:
            # 模型/检索等组件故障 → 缓存证据模板兜底（W4.4 降级）
            from core.services.degrade import fallback_deliverable

            merged["deliverable"] = fallback_deliverable(
                req.question, merged.get("evidence") or {}, run_id, f"系统组件故障（{type(e).__name__}）"
            ).model_dump()
            state.tracer.event(trace_id, "degraded", {"error": str(e)[:200]})
        if interrupted:
            state.runs[run_id] = merged
            persist(merged)
            state.memory.append(req.session_id, {"question": req.question, "run_id": run_id})
            state.tracer.event(trace_id, "needs_human", merged.get("human_gate"))
            state.tracer.end(trace_id, {"pending_human": True})
            yield _sse({"type": "done", "pending_human": True})
            return
        if merged.get("deliverable"):
            yield _sse({"type": "deliverable", "deliverable": merged["deliverable"]})
        state.runs[run_id] = merged
        persist(merged)
        state.memory.append(req.session_id, {"question": req.question, "run_id": run_id})
        d = merged.get("deliverable") or {}
        state.tracer.end(trace_id, {"refused": d.get("refused", False), "confidence": d.get("confidence")})
        yield _sse({"type": "done"})

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
