"""餐食与血糖记录 API：健康档案的读写入口，也是问答召回的数据源。"""

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from adapters.tools import food_data
from app.api.deps import current_user

router = APIRouter()

MealType = Literal["早餐", "午餐", "晚餐", "加餐"]
MealSource = Literal["photo", "chat", "manual"]


def _now_local() -> str:
    return datetime.now().strftime("%Y-%m-%dT%H:%M")


def _fill_nutrition(foods: list[dict]) -> list[dict]:
    """只写名字和克数时按食物库折算碳水/GL；用户自己填的不覆盖，库外食物留空不猜。"""
    for food in foods:
        if food.get("carbs_g") is not None:
            continue
        estimate = food_data.nutrition_for(food.get("name", ""), float(food.get("grams") or 0))
        if estimate is None:
            continue
        food["carbs_g"] = estimate["carbs_g"]
        if food.get("gl") is None:
            food["gl"] = estimate["gl"]
        food["estimated"] = True
    return foods


class FoodIn(BaseModel):
    name: str = Field(min_length=1, max_length=40)
    grams: float = Field(ge=0, le=3000)
    carbs_g: float | None = Field(default=None, ge=0, le=600)
    gl: float | None = Field(default=None, ge=0, le=600)
    # 碳水来自食物库折算而非用户自填；改回手填时前端会置 false
    estimated: bool = False


class MealIn(BaseModel):
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
async def create_meal(body: MealIn, request: Request, user: str = Depends(current_user)):
    meal = request.app.state.meals.add_meal(
        user_id=user,
        eaten_at=body.eaten_at,
        meal_type=body.meal_type,
        foods=_fill_nutrition([f.model_dump() for f in body.foods]),
        note=body.note[:500],
        source=body.source,
        image_id=body.image_id,
        insulin_note=body.insulin_note[:200],
    )
    return {"meal": meal}


@router.get("/api/meals")
async def list_meals(request: Request, limit: int = 50, user: str = Depends(current_user)):
    return {"meals": request.app.state.meals.list_meals(user, limit)}


@router.get("/api/meals/{meal_id}")
async def get_meal(meal_id: str, request: Request, user: str = Depends(current_user)):
    meal = request.app.state.meals.get_meal(meal_id, user)
    if meal is None:
        raise HTTPException(404, f"记录不存在：{meal_id}")
    return {"meal": meal}


@router.patch("/api/meals/{meal_id}")
async def update_meal(meal_id: str, body: MealPatch, request: Request, user: str = Depends(current_user)):
    patch = body.model_dump(exclude_none=True)
    if "foods" in patch:
        patch["foods"] = _fill_nutrition([f.model_dump() for f in body.foods or []])
    meal = request.app.state.meals.update_meal(meal_id, patch, user)
    if meal is None:
        raise HTTPException(404, f"记录不存在：{meal_id}")
    return {"meal": meal}


@router.delete("/api/meals/{meal_id}")
async def delete_meal(meal_id: str, request: Request, user: str = Depends(current_user)):
    if not request.app.state.meals.delete_meal(meal_id, user):
        raise HTTPException(404, f"记录不存在：{meal_id}")
    return {"deleted": True}


@router.post("/api/meals/{meal_id}/glucose")
async def add_glucose(meal_id: str, body: GlucoseIn, request: Request, user: str = Depends(current_user)):
    reading = request.app.state.meals.add_glucose(
        meal_id=meal_id,
        value_mmol=body.value_mmol,
        minutes_after=body.minutes_after,
        measured_at=body.measured_at,
        source=body.source,
        user_id=user,
    )
    if reading is None:
        raise HTTPException(404, f"记录不存在：{meal_id}")
    return {"reading": reading}


@router.delete("/api/meals/{meal_id}/glucose/{reading_id}")
async def delete_glucose(meal_id: str, reading_id: str, request: Request, user: str = Depends(current_user)):
    if not request.app.state.meals.delete_glucose(meal_id, reading_id, user):
        raise HTTPException(404, "血糖记录不存在")
    return {"deleted": True}
