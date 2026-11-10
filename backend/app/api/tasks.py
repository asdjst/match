from fastapi import APIRouter, HTTPException, Request
from langgraph.types import Command

router = APIRouter()


@router.get("/api/runs")
async def list_runs(request: Request, limit: int = 50):
    return {"runs": request.app.state.store.list_runs(limit)}


@router.get("/api/tasks/{run_id}")
async def get_task(run_id: str, request: Request):
    runs = request.app.state.runs
    state = runs.get(run_id)
    if state is None:
        # 进程重启后从 SQLite 回查历史 run
        state = request.app.state.store.get_run(run_id)
        if state is None:
            raise HTTPException(404, f"任务不存在：{run_id}")
        return state
    return {
        "run_id": run_id,
        "question": state.get("question"),
        "round_no": state.get("round_no", 0),
        "node_results": state.get("node_results", {}),
        "verdict": state.get("verdict"),
        "deliverable": state.get("deliverable"),
        "pending_human": state.get("pending_human", False),
        "dag": state.get("dag"),
        "evidence": state.get("evidence", {}),
    }


@router.post("/api/tasks/{run_id}/approve")
async def approve_task(run_id: str, request: Request):
    runs = request.app.state.runs
    state = runs.get(run_id)
    if state is None:
        raise HTTPException(404, f"任务不存在（放行仅支持本次进程内的任务）：{run_id}")
    if not state.get("pending_human"):
        raise HTTPException(409, "该任务不在待放行状态")
    config = {"configurable": {"thread_id": run_id}, "recursion_limit": 30}
    result = request.app.state.graph.invoke(Command(resume=True), config)
    state.update(result)
    state["pending_human"] = False
    request.app.state.store.save_run(run_id, state)
    return {
        "run_id": run_id,
        "deliverable": state.get("deliverable"),
        "node_results": state.get("node_results", {}),
    }
