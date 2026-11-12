import time

from fastapi import APIRouter, Depends, HTTPException, Request
from langgraph.types import Command

from app.api.deps import current_user
from core.graph.events import NodeEventLog

router = APIRouter()


def _own_run(runs: dict, run_id: str, user: str) -> dict | None:
    """内存快照按归属过滤：别人的 run 一律当作不存在，避免用 run_id 猜读。"""
    state = runs.get(run_id)
    if state is None or state.get("user_id", "local") != user:
        return None
    return state


@router.get("/api/runs")
async def list_runs(request: Request, limit: int = 50, user: str = Depends(current_user)):
    return {"runs": request.app.state.store.list_runs(limit, user_id=user)}


@router.get("/api/tasks/{run_id}")
async def get_task(run_id: str, request: Request, user: str = Depends(current_user)):
    runs = request.app.state.runs
    state = _own_run(runs, run_id, user)
    if state is None:
        # 进程重启后从 SQLite 回查历史 run
        state = request.app.state.store.get_run(run_id, with_session=True, user_id=user)
        if state is None:
            raise HTTPException(404, f"任务不存在：{run_id}")
        return state
    return {
        "run_id": run_id,
        "session_id": state.get("session_id"),
        "created_at": state.get("created_at"),
        "question": state.get("question"),
        "round_no": state.get("round_no", 0),
        "node_results": state.get("node_results", {}),
        "verdict": state.get("verdict"),
        "deliverable": state.get("deliverable"),
        "pending_human": state.get("pending_human", False),
        "dag": state.get("dag"),
        "evidence": state.get("evidence", {}),
        "image_id": state.get("image_id"),
        "food_items": state.get("food_items", []),
        "node_events": state.get("node_events", []),
        "timings": state.get("timings", []),
        "duration_ms": state.get("duration_ms"),
        "error": state.get("error"),
    }


@router.post("/api/tasks/{run_id}/approve")
async def approve_task(run_id: str, request: Request, user: str = Depends(current_user)):
    runs = request.app.state.runs
    state = _own_run(runs, run_id, user)
    # 进程重启后内存里没有 run：靠 SQLite 断点 + 落库快照恢复放行
    snap = state if state is not None else request.app.state.store.get_run(run_id, with_session=True, user_id=user)
    if snap is None:
        raise HTTPException(404, f"任务不存在：{run_id}")
    if not snap.get("pending_human"):
        raise HTTPException(409, "该任务不在待放行状态")
    config = {"configurable": {"thread_id": run_id}, "recursion_limit": 30}
    events = NodeEventLog(snap)
    # 快照落库时不含 user_id 列，恢复后仍要带上归属，否则内存缓存会认不出所有者
    merged = {**snap, "pending_human": False, "user_id": user}

    def persist():
        record = events.snapshot(merged)
        runs[run_id] = record
        request.app.state.store.save_run(run_id, record, user_id=user)
        return record

    try:
        # HTTP remains non-streaming; consume real resumed node updates rather than diffing a final state.
        # 放行后重新起算预算：断点可能跨进程存活很久，旧 started_at 会立刻触发超时
        async for mode, chunk in request.app.state.graph.astream(
            Command(resume=True, update={"started_at": time.monotonic(), "steps": 0, "budget_stop": None}),
            config,
            stream_mode=["custom", "updates"],
        ):
            if mode == "custom":
                events.custom(chunk)
                continue
            if "__interrupt__" in chunk:
                intr = chunk["__interrupt__"][0]
                payload = intr.value if isinstance(intr.value, dict) else {"reason": str(intr.value)}
                merged.update(pending_human=True, human_gate=payload)
                break
            for node, delta in chunk.items():
                merged.update(delta)
                events.done(node)
                runs[run_id] = events.snapshot(merged)
    except Exception as exc:
        merged["error"] = f"恢复执行失败（{type(exc).__name__}）"
        persist()
        raise HTTPException(409, f"断点已失效，无法恢复（{type(exc).__name__}）") from exc
    merged = persist()
    return {
        "run_id": run_id,
        "deliverable": merged.get("deliverable"),
        "node_results": merged.get("node_results", {}),
    }
