from typing import Literal

from pydantic import BaseModel, Field


class ProfileIn(BaseModel):
    """用户自填的代谢档案：只用于个性化建议的上下文，不是诊断依据，也不进证据池。"""

    height_cm: float | None = Field(default=None, ge=80, le=250)
    weight_kg: float | None = Field(default=None, ge=20, le=300)
    age: int | None = Field(default=None, ge=10, le=120)
    activity: Literal["久坐", "轻度活动", "规律运动"] | None = None
    goal: Literal["控制餐后血糖", "减重", "维持体重"] | None = None

    def normalized(self) -> dict:
        data = self.model_dump(exclude_none=True)
        height = data.get("height_cm")
        weight = data.get("weight_kg")
        if height and weight:
            data["bmi"] = round(weight / (height / 100) ** 2, 1)
        return data
