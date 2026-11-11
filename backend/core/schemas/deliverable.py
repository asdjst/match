from typing import Literal

from pydantic import BaseModel, Field


class Assertion(BaseModel):
    text: str
    cites: list[str] = Field(default_factory=list, description="证据编号，如 ['E1']")
    inferred: bool = Field(default=False, description="挂不上引用的断言标为推断")


class Deliverable(BaseModel):
    """最终交付物：结论 + 引用表 + 轨迹 + 置信度，结构固定可复现。"""

    question: str
    assertions: list[Assertion] = Field(default_factory=list)
    citations: list = Field(default_factory=list, description="list[Evidence]")
    trace_id: str = ""
    confidence: float = 0.0
    confidence_source: Literal["llm", "formula"] = "formula"
    confidence_reason: str | None = None
    degraded: bool = False
    degraded_reason: str | None = Field(default=None, description="降级原因，如预算耗尽")
    refused: bool = False
    refusal_reason: str | None = None
