import json
import logging
import re
import time
import uuid
from datetime import datetime, timezone
from typing import AsyncIterator

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from langgraph.errors import GraphRecursionError
from pydantic import BaseModel, Field

from core.graph.events import NodeEventLog
from core.graph.state import GraphState
from core.schemas.deliverable import Deliverable
from core.schemas.profile import ProfileIn
from core.services.food import build_food_evidence
from core.services.meals import memory_evidences
from core.services.memory import answer_snippet

router = APIRouter()
log = logging.getLogger(__name__)

# “这个/这餐”没有带新照片时，沿用本会话上一张餐盘的食物名做记录核对
_BACKREF = re.compile(r"这个|这餐|这顿|这份|刚才|刚刚|上一|上个")


class ChatRequest(BaseModel):
    session_id: str = "default"
    user_id: str = Field(default="local", max_length=64)
    question: str = Field(min_length=1)
    image_id: str | None = Field(default=None, max_length=64)
    food_items: list[dict] = Field(default_factory=list, max_length=20)
    profile: ProfileIn | None = None


def _next_evidence_id(pool: dict) -> str:
    ids = [int(m) for eid in pool for m in re.findall(r"E(\d+)", eid)]
    return f"E{max(ids, default=0) + 1}"


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


@router.post("/api/chat")
async def chat(req: ChatRequest, request: Request) -> StreamingResponse:
    state = request.app.state

    async def gen() -> AsyncIterator[str]:
        run_id = str(uuid.uuid4())
        created_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        events = NodeEventLog()
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
            state.runs[run_id] = events.snapshot({
                "session_id": req.session_id,
                "question": req.question,
                "round_no": 0,
                "node_results": {},
                "deliverable": deliverable.model_dump(),
                "created_at": created_at,
            })
            persist(state.runs[run_id])
            state.tracer.event(trace_id, "guard", {"allowed": False, "reason": verdict.reason})
            yield _sse({"type": "guard", "allowed": False, "reason": verdict.reason})
            yield _sse({"type": "deliverable", "deliverable": deliverable.model_dump()})
            state.tracer.end(trace_id, {"refused": True, "blocked_by": "guard"})
            yield _sse({"type": "done"})
            return

        question = state.guard.sanitize(req.question)
        # 拍照结果先校验再进证据池：非法项丢弃，避免脏 payload 影响后续引用
        food_items, food_pool = build_food_evidence(req.image_id, req.food_items)
        pool = dict(food_pool)
        # 个人餐食记录作为独立证据通道：命中食物名或“上次”类提问时附带，失败不阻塞问答
        try:
            target_foods = [str(item.get("name") or "") for item in food_items]
            if not target_foods and _BACKREF.search(question):
                target_foods = state.store.recent_food_names(req.session_id)
            for ev in memory_evidences(
                state.meals, req.user_id, question, target_foods=target_foods
            ):
                eid = _next_evidence_id(pool)
                pool[eid] = ev.model_copy(update={"evidence_id": eid}).model_dump()
        except Exception as exc:
            state.tracer.event(trace_id, "memory_error", {"error": str(exc)[:200]})
        profile = req.profile.normalized() if req.profile else None
        # 多轮上下文：优先进程内记忆，重启后由 SQLite 里的历史 run 回填
        history = state.memory.history(req.session_id, last=3)
        if not history:
            try:
                history = state.store.history(req.session_id, last=3)
            except Exception as exc:  # 历史读失败只影响指代消解，不阻塞问答
                state.tracer.event(trace_id, "memory_error", {"error": str(exc)[:200]})
        init: GraphState = {
            "session_id": req.session_id,
            "question": question,
            "trace_id": run_id,
            "round_no": 0,
            "evidence": pool,
            "node_results": {},
            "history": history,
            "steps": 0,
            "started_at": time.monotonic(),
            "image_id": req.image_id,
            "food_items": food_items,
            "profile": profile,
        }

        def remember(record: dict) -> None:
            deliverable = record.get("deliverable") or {}
            state.memory.append(req.session_id, {
                "question": record.get("question") or req.question,
                "answer": answer_snippet(deliverable),
                "confidence": deliverable.get("confidence"),
                "run_id": run_id,
            })
        merged: dict = {**init, "created_at": created_at}
        config = {"configurable": {"thread_id": run_id}, "recursion_limit": 30}
        interrupted = False
        try:
            async for mode, chunk in state.graph.astream(init, config, stream_mode=["custom", "updates"]):
                if mode == "custom":
                    event = events.custom(chunk)
                    if event is not None:
                        state.runs[run_id] = events.snapshot(merged)
                        yield _sse(event)
                    continue
                if "__interrupt__" in chunk:
                    intr = chunk["__interrupt__"][0]
                    payload = intr.value if isinstance(intr.value, dict) else {"reason": str(intr.value)}
                    interrupted = True
                    merged |= {"pending_human": True, "human_gate": payload}
                    yield _sse({"type": "needs_human", "run_id": run_id, **payload})
                    break
                for node, delta in chunk.items():
                    merged.update(delta)
                    event = events.done(node)
                    # Only actual updates enter completion history; interrupted/failed nodes do not.
                    state.runs[run_id] = events.snapshot(merged)
                    state.tracer.event(trace_id, f"node:{node}", {"status": "done"})
                    yield _sse(event)
        except GraphRecursionError:
            merged["error"] = "超过图循环上限"
            state.runs[run_id] = events.snapshot(merged)
            yield _sse({"type": "error", "message": merged["error"]})
            state.tracer.event(trace_id, "error", {"message": "超过图循环上限"})
        except Exception as e:
            # 模型/检索等组件故障 → 缓存证据模板兜底（W4.4 降级）
            log.exception("run %s 降级兜底", run_id)
            from core.services.degrade import fallback_deliverable

            merged["error"] = f"系统组件故障（{type(e).__name__}）"
            merged["deliverable"] = fallback_deliverable(
                req.question, merged.get("evidence") or {}, run_id, merged["error"]
            ).model_dump()
            state.tracer.event(trace_id, "degraded", {"error": str(e)[:200]})
        merged = events.snapshot(merged)
        if interrupted:
            state.runs[run_id] = merged
            persist(merged)
            remember(merged)
            state.tracer.event(trace_id, "needs_human", merged.get("human_gate"))
            state.tracer.end(trace_id, {"pending_human": True})
            yield _sse({"type": "done", "pending_human": True})
            return
        if merged.get("deliverable"):
            yield _sse({"type": "deliverable", "deliverable": merged["deliverable"]})
        state.runs[run_id] = merged
        persist(merged)
        remember(merged)
        d = merged.get("deliverable") or {}
        state.tracer.end(trace_id, {"refused": d.get("refused", False), "confidence": d.get("confidence")})
        yield _sse({"type": "done"})

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
