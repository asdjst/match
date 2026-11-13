"""流式成文：delta 逐块回调、完整文本仍过确定性校验、不过则整体回退。"""

from adapters.llm.fake import FakeLLM
from core.schemas.agent import ComposedAnswer
from core.schemas.deliverable import Assertion
from core.services.compose import compose_stream

ASSERTIONS = [Assertion(text="米饭每100g碳水约26g", cites=["E1"])]


def test_fake_llm_stream_emits_chunks_and_validates():
    chunks: list[str] = []
    res = compose_stream(FakeLLM(), "一碗米饭多少碳水？", ASSERTIONS, emit=chunks.append)
    assert res.source == "llm" and res.text
    assert chunks, "应有流式 delta 回调"
    assert "".join(chunks) == res.text
    assert "[E1]" in res.text


class BadCiteLLM:
    """流式输出引入了未审校的引用编号 → 校验不过，整体回退。"""

    def stream(self, prompt, tier="fast"):
        yield "米饭每100g碳水约26g"
        yield "[E99]"


def test_stream_with_unaudited_citation_falls_back():
    chunks: list[str] = []
    res = compose_stream(BadCiteLLM(), "q", ASSERTIONS, emit=chunks.append)
    assert res.text is None
    assert chunks, "回退前 delta 已经推出去了（由调用方发 answer_abort 丢弃）"
    assert "未审校的引用" in (res.reason or "")


class NoStreamLLM:
    """没有 stream 方法的实现 → 退回普通 complete，行为与原来一致。"""

    def complete(self, prompt, tier="fast", schema=None):
        assert schema is ComposedAnswer
        return ComposedAnswer(text="米饭每100g碳水约26g[E1]")


def test_llm_without_stream_falls_back_to_complete():
    res = compose_stream(NoStreamLLM(), "q", ASSERTIONS, emit=lambda d: None)
    assert res.text == "米饭每100g碳水约26g[E1]"
    assert res.source == "llm"


class BrokenLLM:
    def stream(self, prompt, tier="fast"):
        raise RuntimeError("gateway down")
        yield


def test_stream_exception_falls_back():
    res = compose_stream(BrokenLLM(), "q", ASSERTIONS)
    assert res.text is None
    assert "调用失败" in (res.reason or "")
