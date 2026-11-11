"""餐食与血糖记录 API：健康档案的读写入口，也是问答召回的数据源。"""

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

router = APIRouter()

MealType = Literal["早餐", "午餐", "晚餐", "加餐"]
MealSource = Literal["photo", "chat", "manual"]


def _now_local() -> str:
    return datetime.now().strftime("%Y-%m-%dT%H:%M")


class FoodIn(BaseModel):
    name: str = Field(min_length=1, max_length=40)
    grams: float = Field(ge=0, le=3000)
    carbs_g: float | None = Field(default=None, ge=0, le=600)
    gl: float | None = Field(default=None, ge=0, le=600)


class MealIn(BaseModel):
    user_id: str = Field(default="local", max_length=64)
    eaten_at: str = Field(default_factory=_now_local, max_length=32)
    meal_type: MealType = "午餐"
    foods: list[FoodIn] = Field(min_length=1, max_length=10)
    note: str = ""
    source: MealSource = "manual"
    image_id: str | None = Field(default=None, max_length=64)
    # 用户自记用药，仅本人可查看；不进入问答上下文
    insulin_note: str = ""


class MealPatch(BaseModel):
    eaten_at: str | None = Field(default=None, max_length=32)
    meal_type: MealType | None = None
    foods: list[FoodIn] | None = Field(default=None, max_length=10)
    note: str | None = None
    insulin_note: str | None = None


class GlucoseIn(BaseModel):
    value_mmol: float = Field(ge=1, le=40)
    minutes_after: int = Field(default=120, ge=0, le=600)
    measured_at: str | None = Field(default=None, max_length=32)
    source: Literal["manual", "cgm"] = "manual"


@router.post("/api/meals")
async def create_meal(body: MealIn, request: Request):
    meal = request.app.state.meals.add_meal(
        user_id=body.user_id,
        eaten_at=body.eaten_at,
        meal_type=body.meal_type,
        foods=[f.model_dump() for f in body.foods],
        note=body.note[:500],
        source=body.source,
        image_id=body.image_id,
        insulin_note=body.insulin_note[:200],
    )
    return {"meal": meal}


@router.get("/api/meals")
async def list_meals(request: Request, user_id: str = "local", limit: int = 50):
    return {"meals": request.app.state.meals.list_meals(user_id, limit)}


@router.get("/api/meals/{meal_id}")
async def get_meal(meal_id: str, request: Request):
    meal = request.app.state.meals.get_meal(meal_id)
    if meal is None:
        raise HTTPException(404, f"记录不存在：{meal_id}")
    return {"meal": meal}


@router.patch("/api/meals/{meal_id}")
async def update_meal(meal_id: str, body: MealPatch, request: Request):
    patch = body.model_dump(exclude_none=True)
    if "foods" in patch:
        patch["foods"] = [f.model_dump() for f in body.foods or []]
    meal = request.app.state.meals.update_meal(meal_id, patch)
    if meal is None:
        raise HTTPException(404, f"记录不存在：{meal_id}")
    return {"meal": meal}


@router.delete("/api/meals/{meal_id}")
async def delete_meal(meal_id: str, request: Request):
    if not request.app.state.meals.delete_meal(meal_id):
        raise HTTPException(404, f"记录不存在：{meal_id}")
    return {"deleted": True}


@router.post("/api/meals/{meal_id}/glucose")
async def add_glucose(meal_id: str, body: GlucoseIn, request: Request):
    reading = request.app.state.meals.add_glucose(
        meal_id=meal_id,
        value_mmol=body.value_mmol,
        minutes_after=body.minutes_after,
        measured_at=body.measured_at,
        source=body.source,
    )
    if reading is None:
        raise HTTPException(404, f"记录不存在：{meal_id}")
    return {"reading": reading}


@router.delete("/api/meals/{meal_id}/glucose/{reading_id}")
async def delete_glucose(meal_id: str, reading_id: str, request: Request):
    if not request.app.state.meals.delete_glucose(meal_id, reading_id):
        raise HTTPException(404, "血糖记录不存在")
    return {"deleted": True}
