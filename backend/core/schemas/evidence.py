from typing import Literal

from pydantic import BaseModel, Field

from core.schemas.common import SourceRef

Channel = Literal["local", "web", "cloud"]


class Evidence(BaseModel):
    """检索证据：由 R2R 检索载荷（或工具计算结果）映射而来。"""

    evidence_id: str = Field(default="", description="进 Prompt 的编号 [n]，检索节点统一分配")
    doc_id: str
    quote: str
    score: float = 0.0
    source: SourceRef = Field(default_factory=SourceRef)
    channel: Channel = "local"
