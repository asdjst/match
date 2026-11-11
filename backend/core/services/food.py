from pydantic import ValidationError

from core.schemas.common import SourceRef
from core.schemas.evidence import Evidence
from core.schemas.food import FoodItem


def build_food_evidence(
    image_id: str | None, raw_items: list[dict]
) -> tuple[list[dict], dict[str, dict]]:
    """把拍照/手动修正的餐食结果变成可引用证据；非法项直接丢掉，不阻塞问答。"""
    items: list[FoodItem] = []
    for raw in raw_items:
        try:
            items.append(FoodItem.model_validate(raw))
        except (ValidationError, TypeError):
            continue
    if not items:
        return [], {}

    source = SourceRef(
        file_path=f"photo://{image_id}" if image_id else "手动录入",
        modality="image" if image_id else "text",
    )
    pool: dict[str, dict] = {}
    for index, item in enumerate(items, start=1):
        quote = (
            f"拍照识别：{item.name} {_fmt(item.grams_low)}-{_fmt(item.grams_high)}g，"
            f"碳水 {_fmt(item.carbs_g_low)}-{_fmt(item.carbs_g_high)}g"
        )
        if item.basis:
            quote += f"（依据：{item.basis}）"
        pool[f"E{index}"] = Evidence(
            evidence_id=f"E{index}",
            doc_id="photo",
            quote=quote,
            score=item.confidence,
            source=source,
            channel="image",
        ).model_dump()

    low = round(sum(i.carbs_g_low for i in items), 1)
    high = round(sum(i.carbs_g_high for i in items), 1)
    total_id = f"E{len(items) + 1}"
    pool[total_id] = Evidence(
        evidence_id=total_id,
        doc_id="photo",
        quote=f"拍照识别整餐合计：{len(items)} 样食物，碳水 {_fmt(low)}-{_fmt(high)}g",
        score=min(i.confidence for i in items),
        source=source,
        channel="image",
    ).model_dump()
    return [i.model_dump() for i in items], pool


def _fmt(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else f"{value:.1f}"
