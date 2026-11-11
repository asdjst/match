from pydantic import BaseModel

from adapters.llm.structured import complete_structured, extract_json
from core.schemas.prompt import PromptBundle, TextOut
from infra.config import TierConfig

_TIER_TEMPERATURE = {"planner": 0.2, "critic": 0.0, "retriever": 0.3, "executor": 0.0, "analyst": 0.6, "writer": 0.6}
# 快档只做规划/审校/评分这类短 JSON，给 2k 足够；强档分析要留推理预算
_MAX_TOKENS = {"fast": 2048, "strong": 8192}


class LiteLLMRouter:
    """真实现：LiteLLM 双档路由 + 四层 Prompt 拼装 + Schema 校验重试。
    每档独立 model/api_base/api_key/extra_headers，走 openai/ 前缀的兼容网关。"""

    def __init__(self, fast: TierConfig, strong: TierConfig) -> None:
        self._tiers = {"fast": fast, "strong": strong}

    def complete(self, prompt: PromptBundle, tier: str, schema: type[BaseModel] | None = None) -> BaseModel:
        if schema is None:
            return TextOut(text=self._raw(prompt, tier))

        def call(p: PromptBundle) -> BaseModel:
            return schema.model_validate_json(extract_json(self._raw(p, tier)))

        return complete_structured(call, prompt)

    def _raw(self, prompt: PromptBundle, tier: str) -> str:
        from litellm import completion

        cfg = self._tiers.get(tier) or self._tiers["fast"]
        user = "\n\n".join(x for x in [prompt.task, prompt.evidence_block, prompt.format_hint] if x)
        kwargs: dict = {
            "model": cfg.model,
            "messages": [{"role": "system", "content": prompt.system}, {"role": "user", "content": user}],
            "temperature": _TIER_TEMPERATURE.get(prompt.role, 0.3),
            # 强档是推理型模型（deepseek-v4.1-flash），max_tokens 太小会把预算全耗在推理上返回空
            "max_tokens": _MAX_TOKENS.get(tier, 4096),
            # 网关瞬时抖动（连接错误/429/5xx）由 litellm 原生退避重试兜底
            "num_retries": 3,
            "timeout": 90,
        }
        if cfg.api_base:
            kwargs["api_base"] = cfg.api_base
        if cfg.api_key:
            kwargs["api_key"] = cfg.api_key
        if cfg.extra_headers:
            kwargs["extra_headers"] = cfg.extra_headers
        if cfg.extra_body:
            # litellm 会把 extra_body 合并进发给兼容端点的 JSON，用于关思考模式等开关
            kwargs["extra_body"] = cfg.extra_body
        resp = completion(**kwargs)
        return resp.choices[0].message.content or ""
