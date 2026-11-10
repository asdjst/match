from pydantic import BaseModel, Field


class GuardVerdict(BaseModel):
    allowed: bool
    reason: str | None = None
    sanitized: str = ""
    patterns_hit: list[str] = Field(default_factory=list)
