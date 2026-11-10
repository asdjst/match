from typing import Literal, Optional

from pydantic import BaseModel, Field

from core.schemas.deliverable import Assertion


class AgentResult(BaseModel):
    node_id: str
    status: Literal["done", "blocked", "needs_human"]
    output: Optional[dict] = None
    evidence_used: list[str] = Field(default_factory=list)
    block_reason: Optional[str] = None


class ReviewVerdict(BaseModel):
    verdict: Literal["pass", "send_back"]
    issues: list[str] = Field(default_factory=list)
    send_back_to: Optional[Literal["planner", "retriever"]] = None
    round_no: int = 0


class CriticOutput(BaseModel):
    """审校 LLM 自检通道输出：与规则通道合并成最终 ReviewVerdict。"""

    verdict: Literal["pass", "send_back"] = "pass"
    issues: list[str] = Field(default_factory=list)
    send_back_to: Optional[Literal["planner", "retriever"]] = None


class AnalystOutput(BaseModel):
    """分析节点结构化输出：每条断言必须带引用编号。"""

    assertions: list[Assertion] = Field(default_factory=list)
