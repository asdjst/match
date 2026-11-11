from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator


class Budget(BaseModel):
    max_steps: int = 8
    max_rounds: int = 3
    timeout_s: int = 120


class NodeSpec(BaseModel):
    node_id: str
    role: Literal["planner", "retriever", "executor", "analyst", "critic"]
    instruction: str = ""
    depends_on: list[str] = Field(default_factory=list)
    budget: Budget = Field(default_factory=Budget)
    tool: Optional[str] = None
    query: Optional[str] = None

    @field_validator("budget", mode="before")
    @classmethod
    def _coerce_budget(cls, v):
        # 真实 LLM 常把 budget 简写成数字，按步数上限收敛成对象
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            return {"max_steps": int(v)}
        return v


class TaskDAG(BaseModel):
    question: str
    nodes: list[NodeSpec] = Field(default_factory=list)

    def by_role(self, role: str) -> list[NodeSpec]:
        return [n for n in self.nodes if n.role == role]

    def order(self) -> list[NodeSpec]:
        """按 depends_on 做拓扑排序；依赖成环或引用未知节点时退回声明顺序。"""
        by_id = {n.node_id: n for n in self.nodes}
        indeg = {n.node_id: 0 for n in self.nodes}
        children: dict[str, list[str]] = {n.node_id: [] for n in self.nodes}
        for n in self.nodes:
            for dep in n.depends_on:
                if dep in by_id and dep != n.node_id:
                    indeg[n.node_id] += 1
                    children[dep].append(n.node_id)
        ready = [n.node_id for n in self.nodes if indeg[n.node_id] == 0]
        out: list[NodeSpec] = []
        while ready:
            nid = ready.pop(0)
            out.append(by_id[nid])
            for child in children[nid]:
                indeg[child] -= 1
                if indeg[child] == 0:
                    ready.append(child)
        return out if len(out) == len(self.nodes) else list(self.nodes)

    def max_rounds(self) -> int:
        return self.nodes[0].budget.max_rounds if self.nodes else 3
