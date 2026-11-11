from typing import Literal

from pydantic import BaseModel, Field, model_validator


class FoodItem(BaseModel):
    """单条食物估算：克重与碳水都给区间，便于用户按实际份量修正。"""

    name: str = Field(min_length=1, max_length=40)
    grams_low: float = Field(ge=0)
    grams_high: float = Field(ge=0)
    carbs_g_low: float = Field(ge=0)
    carbs_g_high: float = Field(ge=0)
    confidence: float = Field(ge=0, le=1)
    basis: str = Field(default="", max_length=120, description="碳水估算依据，如食物成分表条目")

    @model_validator(mode="after")
    def _ordered_range(self) -> "FoodItem":
        if self.grams_high < self.grams_low or self.carbs_g_high < self.carbs_g_low:
            raise ValueError("区间上界不能小于下界")
        return self


class FoodAnalysis(BaseModel):
    """拍照识别的结构化结果；图片本身只留在服务端，state 里只传 image_id。"""

    image_id: str
    items: list[FoodItem] = Field(default_factory=list)
    carbs_g_low: float = Field(default=0.0, ge=0)
    carbs_g_high: float = Field(default=0.0, ge=0)
    confidence: float = Field(default=0.0, ge=0, le=1)
    source: Literal["vlm", "demo"] = "demo"
    degraded: bool = False
    notes: str = ""
