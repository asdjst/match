"""LiteLLMRouter：双档配置透传（extra_headers / extra_body），不碰网络。"""

from types import SimpleNamespace

import litellm

from adapters.llm.router import LiteLLMRouter
from core.schemas.prompt import PromptBundle
from infra.config import TierConfig


def _prompt() -> PromptBundle:
    return PromptBundle(role="planner", system="sys", task="task")


def test_extra_body_is_forwarded_for_thinking_toggle(monkeypatch):
    captured: dict = {}

    def fake_completion(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="ok"))])

    monkeypatch.setattr(litellm, "completion", fake_completion)
    router = LiteLLMRouter(
        fast=TierConfig(
            model="openai/deepseek-flash",
            api_key="k",
            extra_body={"thinking": {"type": "disabled"}},
        ),
        strong=TierConfig(model="openai/deepseek-chat", api_key="k"),
    )

    assert router._raw(_prompt(), "fast") == "ok"
    assert captured["extra_body"] == {"thinking": {"type": "disabled"}}
    assert captured["model"] == "openai/deepseek-flash"


def test_tier_without_extra_body_keeps_request_clean(monkeypatch):
    captured: dict = {}

    def fake_completion(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="ok"))])

    monkeypatch.setattr(litellm, "completion", fake_completion)
    router = LiteLLMRouter(
        fast=TierConfig(model="openai/deepseek-chat", api_key="k"),
        strong=TierConfig(model="openai/deepseek-chat", api_key="k"),
    )

    router._raw(_prompt(), "strong")
    assert "extra_body" not in captured
