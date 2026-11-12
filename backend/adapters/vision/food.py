import base64
import json
import mimetypes
from pathlib import Path

from adapters.llm.structured import extract_json
from adapters.tools.food_data import lookup
from core.schemas.food import FoodAnalysis, FoodItem
from infra.config import TierConfig

_PROMPT = (
    "识别图中所有食物，估算每样食物的可食重量与碳水化合物。"
    "克重给区间（如 150-200），碳水按食物成分表折算每 100g 含量；"
    "不确定就放宽区间，不要编造看不见的食物。"
    '只输出 JSON：{"items":[{"name":"米饭","grams_low":150,"grams_high":200,'
    '"carbs_per_100g":25.9,"confidence":0.8,"basis":"中国食物成分表"}]}；'
    '没有食物则输出 {"items":[]}。'
)


def _num(value, default: float = 0.0) -> float:
    try:
        return max(0.0, float(value))
    except (TypeError, ValueError):
        return default


class VlmFoodAnalyzer:
    """餐食照片 → 结构化食物与碳水区间；失败降级为可手动输入的提示，不抛到接口层。"""

    def __init__(self, tier: TierConfig) -> None:
        self._tier = tier

    def analyze(self, image_id: str, path: Path) -> FoodAnalysis:
        try:
            raw_items = self._extract(path)
        except Exception as exc:  # 模型/网络故障不阻塞用户，改为手动输入
            return FoodAnalysis(
                image_id=image_id,
                source="vlm",
                degraded=True,
                notes=f"自动识别失败，请手动输入食物与份量（{type(exc).__name__}）",
            )

        items: list[FoodItem] = []
        for raw in raw_items:
            item = self._to_item(raw)
            if item is not None:
                items.append(item)
        if not items:
            return FoodAnalysis(
                image_id=image_id,
                source="vlm",
                degraded=True,
                notes="未识别到食物，请手动输入食物与份量",
            )
        return FoodAnalysis(
            image_id=image_id,
            items=items,
            carbs_g_low=round(sum(i.carbs_g_low for i in items), 1),
            carbs_g_high=round(sum(i.carbs_g_high for i in items), 1),
            # 取最弱一项，避免多样食物里一项离谱就把整餐置信度抬高
            confidence=min(i.confidence for i in items),
            source="vlm",
        )

    def _to_item(self, raw: dict) -> FoodItem | None:
        if not isinstance(raw, dict) or not str(raw.get("name") or "").strip():
            return None
        name = str(raw["name"]).strip()[:40]
        grams_low = _num(raw.get("grams_low"))
        grams_high = max(grams_low, _num(raw.get("grams_high"), grams_low))
        per_100g = _num(raw.get("carbs_per_100g"))
        basis = str(raw.get("basis") or "")[:120]
        # 份量交给 VLM，碳水以本地成分表为准：避免同一样食物出现两套互相矛盾的数值
        known = lookup(name)
        if known is not None:
            per_100g = float(known["carbs_per_100g"])
            basis = f"中国食物成分表：约{per_100g:g}g 碳水/100g"
            if known["gi"] is None:
                basis += "；GI 未收录，不估算 GL"
        elif per_100g > 0:
            # 库里没有的食物只能用模型自报值，必须标明是估算，不能冒充成分表数据
            basis = f"模型估算：约{per_100g:g}g 碳水/100g（食物库未收录，请自行核对）"
        try:
            return FoodItem(
                name=name,
                grams_low=grams_low,
                grams_high=grams_high,
                carbs_g_low=round(grams_low * per_100g / 100, 1),
                carbs_g_high=round(grams_high * per_100g / 100, 1),
                confidence=min(1.0, _num(raw.get("confidence"), 0.5)),
                basis=basis,
            )
        except ValueError:
            return None

    def _extract(self, path: Path) -> list[dict]:
        from litellm import completion

        b64 = base64.b64encode(path.read_bytes()).decode()
        mime = mimetypes.guess_type(path.name)[0] or "image/jpeg"
        kwargs: dict = {
            "model": self._tier.model,
            "api_base": self._tier.api_base or None,
            "api_key": self._tier.api_key or None,
            "extra_headers": self._tier.extra_headers or None,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": _PROMPT},
                        {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
                    ],
                }
            ],
            "temperature": 0,
            # 推理模型（如 deepseek-flash）会先花数千 token 在 reasoning_content；
            # 预算给小了会 finish_reason=length 且 content 为空。
            "max_tokens": 4096,
            "num_retries": 2,
            "timeout": 90,
        }
        if self._tier.extra_body:
            # 与文本链路一致：关闭思考模式，识别一张图从 10s+ 降到 5s 左右
            kwargs["extra_body"] = self._tier.extra_body
        resp = completion(**kwargs)
        msg = resp.choices[0].message
        text = (msg.content or "").strip()
        if not text:
            # 兜底：极少数网关只回 reasoning_content
            text = (getattr(msg, "reasoning_content", None) or "").strip()
        if not text:
            finish = resp.choices[0].finish_reason
            raise ValueError(f"模型未返回内容（finish_reason={finish}）")
        data = json.loads(extract_json(text))
        items = data.get("items") if isinstance(data, dict) else None
        return items if isinstance(items, list) else []


class FakeFoodAnalyzer:
    """离线演示用固定结果：结构与真实链路一致，数值明确标为示例。"""

    def analyze(self, image_id: str, path: Path) -> FoodAnalysis:
        items = [
            FoodItem(
                name="米饭",
                grams_low=150,
                grams_high=200,
                carbs_g_low=38.9,
                carbs_g_high=51.8,
                confidence=0.6,
                basis="示例：米饭约 25.9g 碳水/100g",
            ),
            FoodItem(
                name="清炒西兰花",
                grams_low=100,
                grams_high=150,
                carbs_g_low=4.3,
                carbs_g_high=6.5,
                confidence=0.5,
                basis="示例：西兰花约 4.3g 碳水/100g",
            ),
        ]
        return FoodAnalysis(
            image_id=image_id,
            items=items,
            carbs_g_low=round(sum(i.carbs_g_low for i in items), 1),
            carbs_g_high=round(sum(i.carbs_g_high for i in items), 1),
            confidence=min(i.confidence for i in items),
            source="demo",
            notes="离线演示：食物与份量为示例值，请按实际修改",
        )
