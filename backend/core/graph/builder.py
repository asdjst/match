import time

from langgraph.config import get_stream_writer
from langgraph.graph import END, StateGraph
from langgraph.checkpoint.base import BaseCheckpointSaver

from core.graph.nodes.critic import make_critic
from core.graph.nodes.roles import (
    make_analyst,
    make_executor,
    make_planner,
    make_retriever,
    make_writer,
)
from core.graph.events import epoch_ms, node_summary
from core.graph.state import GraphState
from core.schemas.dag import TaskDAG


def _report_node(name, call):
    def run(state: dict) -> dict:
        writer = get_stream_writer()  # No-op during invoke/ainvoke without custom streaming.
        round_no = int(state.get("round_no", 0))
        started = time.monotonic()
        writer({"type": "node", "node": name, "status": "running", "round_no": round_no, "at": epoch_ms()})
        delta = call(state)
        elapsed_ms = int((time.monotonic() - started) * 1000)
        # An exception/interrupt never reaches this point and must not become a completion.
        writer({
            "type": "_node_completed", "node": name, "round_no": round_no,
            "elapsed_ms": elapsed_ms,
            "summary": node_summary(name, delta, {**state, **delta}, state),
        })
        return delta

    return run


def build_graph(llm, retriever_port, tools, checkpointer: BaseCheckpointSaver | None = None, refusal_threshold: float = 0.45):
    g = StateGraph(GraphState)
    g.add_node("planner", _report_node("planner", make_planner(llm)))
    g.add_node("retriever", _report_node("retriever", make_retriever(retriever_port)))
    g.add_node("executor", _report_node("executor", make_executor(tools)))
    g.add_node("analyst", _report_node("analyst", make_analyst(llm)))
    g.add_node("critic", _report_node("critic", make_critic(llm)))
    g.add_node("writer", _report_node("writer", make_writer(refusal_threshold, llm)))

    g.set_entry_point("planner")
    g.add_edge("planner", "retriever")
    g.add_conditional_edges("retriever", _after_retriever, {"executor": "executor", "analyst": "analyst"})
    g.add_edge("executor", "analyst")
    g.add_edge("analyst", "critic")
    g.add_conditional_edges(
        "critic",
        _after_critic,
        {"planner": "planner", "retriever": "retriever", "analyst": "analyst", "writer": "writer"},
    )
    g.add_edge("writer", END)
    return g.compile(checkpointer=checkpointer)


def _after_retriever(state: dict) -> str:
    dag = TaskDAG(**state["dag"])
    return "executor" if dag.by_role("executor") else "analyst"


def _after_critic(state: dict) -> str:
    verdict = state.get("verdict") or {}
    if verdict.get("verdict") == "pass":
        return "writer"
    dag = TaskDAG(**state["dag"])
    if state.get("round_no", 0) >= dag.max_rounds():
        return "writer"
    target = verdict.get("send_back_to")
    return target if target in {"planner", "retriever", "analyst"} else "retriever"
