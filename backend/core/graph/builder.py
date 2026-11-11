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
from core.graph.state import GraphState
from core.schemas.dag import TaskDAG


def build_graph(llm, retriever_port, tools, checkpointer: BaseCheckpointSaver | None = None, refusal_threshold: float = 0.45):
    g = StateGraph(GraphState)
    g.add_node("planner", make_planner(llm))
    g.add_node("retriever", make_retriever(retriever_port))
    g.add_node("executor", make_executor(tools))
    g.add_node("analyst", make_analyst(llm))
    g.add_node("critic", make_critic(llm))
    g.add_node("writer", make_writer(refusal_threshold, llm))

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
