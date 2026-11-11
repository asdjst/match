"""WebSearchRetriever：DDGS 结果到 Evidence 的映射，全程不碰网络。"""

import time

import pytest

from adapters.retrieval.web import WebSearchRetriever


class FakeDDGS:
    """替身：记录调用参数，按 max_results 截断返回固定结果。"""

    results: list[dict] = []
    calls: list[dict] = []

    def __init__(self, *args, **kwargs):
        pass

    def text(self, query, max_results=10, timeout=None, backend="auto"):
        FakeDDGS.calls.append(
            {"query": query, "max_results": max_results, "timeout": timeout, "backend": backend}
        )
        return list(FakeDDGS.results[:max_results])


@pytest.fixture()
def fake_ddgs(monkeypatch):
    FakeDDGS.calls = []
    FakeDDGS.results = [
        {"title": "标题一", "href": "https://example.com/a", "body": "摘要一"},
        {"title": "无链接", "href": "", "body": "应被跳过"},
        {"title": "标题三", "href": "https://example.com/c", "body": "摘要三"},
    ]
    monkeypatch.setattr("ddgs.DDGS", FakeDDGS)
    return FakeDDGS


def test_maps_ddgs_results_to_evidence(fake_ddgs):
    hits = WebSearchRetriever(top_k=3).recall("问题")

    # 空 href 结果被跳过，其余两条正常映射
    assert [h.doc_id for h in hits] == ["https://example.com/a", "https://example.com/c"]
    first = hits[0]
    assert "标题一" in first.quote
    assert "摘要一" in first.quote
    assert first.channel == "web"
    assert first.source.file_path == "https://example.com/a"
    # 排序分随结果序号递减
    assert first.score > hits[1].score
    assert fake_ddgs.calls[0]["max_results"] == 3


def test_falls_back_to_bing_when_yahoo_limited(monkeypatch):
    class FlakyDDGS(FakeDDGS):
        def text(self, query, max_results=10, timeout=None, backend="auto"):
            FakeDDGS.calls.append(
                {"query": query, "max_results": max_results, "timeout": timeout, "backend": backend}
            )
            if backend == "yahoo":
                raise RuntimeError("rate limited")
            return list(FakeDDGS.results[:max_results])

    FakeDDGS.calls = []
    FakeDDGS.results = [
        {"title": "标题一", "href": "https://example.com/a", "body": "摘要一"},
    ]
    monkeypatch.setattr("ddgs.DDGS", FlakyDDGS)

    hits = WebSearchRetriever(top_k=3).recall("问题")

    assert [h.doc_id for h in hits] == ["https://example.com/a"]
    assert [c["backend"] for c in FakeDDGS.calls] == ["yahoo", "bing"]


def test_top_k_truncates_results(fake_ddgs):
    fake_ddgs.results = [
        {"title": f"标题{i}", "href": f"https://example.com/{i}", "body": f"摘要{i}"}
        for i in range(4)
    ]
    hits = WebSearchRetriever(top_k=2).recall("问题")

    # top_k=2 时只回前两条（其余被截断），且把 max_results 传给 DDGS
    assert [h.doc_id for h in hits] == ["https://example.com/0", "https://example.com/1"]
    assert fake_ddgs.calls[0]["max_results"] == 2


class _Resp:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self._payload


def test_bocha_maps_results_and_prefers_authoritative(monkeypatch):
    calls: list[dict] = []

    def fake_post(url, headers=None, json=None, timeout=None, trust_env=None):
        calls.append({"url": url, "headers": headers, "json": json})
        return _Resp({
            "data": {"webPages": {"value": [
                {"name": "普通站点", "url": "https://example.com/a", "summary": "摘要一"},
                {"name": "国家卫健委", "url": "https://www.nhc.gov.cn/x", "summary": "摘要二"},
            ]}}
        })

    monkeypatch.setattr("adapters.retrieval.web.httpx.post", fake_post)
    hits = WebSearchRetriever(top_k=3, provider="bocha", api_key="k").recall("糖尿病 饮食")

    assert calls[0]["url"] == "https://api.bocha.cn/v1/web-search"
    assert calls[0]["headers"]["Authorization"] == "Bearer k"
    # 官方来源得分加权后排在最前
    assert [h.doc_id for h in hits] == ["https://www.nhc.gov.cn/x", "https://example.com/a"]
    assert "国家卫健委" in hits[0].quote


def test_bocha_failure_falls_back_to_ddgs(monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("quota exhausted")

    FakeDDGS.calls = []
    FakeDDGS.results = [{"title": "兜底", "href": "https://example.com/fallback", "body": "摘要"}]
    monkeypatch.setattr("adapters.retrieval.web.httpx.post", boom)
    monkeypatch.setattr("ddgs.DDGS", FakeDDGS)

    hits = WebSearchRetriever(top_k=3, provider="bocha", api_key="k").recall("问题")

    assert [h.doc_id for h in hits] == ["https://example.com/fallback"]
    assert FakeDDGS.calls


def test_tavily_maps_results(monkeypatch):
    def fake_post(url, headers=None, json=None, timeout=None, trust_env=None):
        assert url == "https://api.tavily.com/search"
        return _Resp({"results": [
            {"title": "Who", "url": "https://www.who.int/a", "content": "guideline"},
        ]})

    monkeypatch.setattr("adapters.retrieval.web.httpx.post", fake_post)
    hits = WebSearchRetriever(top_k=3, provider="tavily", api_key="k").recall("diabetes")

    assert [h.doc_id for h in hits] == ["https://www.who.int/a"]
    assert hits[0].quote == "Who：guideline"


def test_failure_cools_down_so_same_round_does_not_retry(monkeypatch):
    class DeadDDGS(FakeDDGS):
        def text(self, query, max_results=10, timeout=None, backend="auto"):
            FakeDDGS.calls.append({"query": query, "backend": backend})
            raise RuntimeError("rate limited")

    monkeypatch.setattr("ddgs.DDGS", DeadDDGS)
    retriever = WebSearchRetriever(top_k=3)

    with pytest.raises(RuntimeError, match="No results|rate limited"):
        retriever.recall("问题一")
    attempts = len(FakeDDGS.calls)

    # 冷却期内同实例直接失败，不再撞引擎
    with pytest.raises(RuntimeError, match="冷却"):
        retriever.recall("问题二")
    assert len(FakeDDGS.calls) == attempts


def test_stuck_backend_is_cut_off_at_deadline(monkeypatch):
    class SlowDDGS(FakeDDGS):
        def text(self, query, max_results=10, timeout=None, backend="auto"):
            time.sleep(0.5)
            raise RuntimeError("slow engine")

    monkeypatch.setattr("ddgs.DDGS", SlowDDGS)

    retriever = WebSearchRetriever(top_k=3, deadline_s=0.2)
    started = time.monotonic()
    with pytest.raises(TimeoutError):
        retriever.recall("问题")

    elapsed = time.monotonic() - started
    assert elapsed < 0.8
    with pytest.raises(RuntimeError, match="冷却"):
        retriever.recall("问题二")
