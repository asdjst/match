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

    def max_rounds(self) -> int:
        return self.nodes[0].budget.max_rounds if self.nodes else 3
