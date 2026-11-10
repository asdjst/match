"""WebSearchRetriever：DDGS 结果到 Evidence 的映射，全程不碰网络。"""

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


def test_falls_back_to_auto_when_yahoo_limited(monkeypatch):
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
    assert [c["backend"] for c in FakeDDGS.calls] == ["yahoo", "auto"]


def test_top_k_truncates_results(fake_ddgs):
    fake_ddgs.results = [
        {"title": f"标题{i}", "href": f"https://example.com/{i}", "body": f"摘要{i}"}
        for i in range(4)
    ]
    hits = WebSearchRetriever(top_k=2).recall("问题")

    # top_k=2 时只回前两条（其余被截断），且把 max_results 传给 DDGS
    assert [h.doc_id for h in hits] == ["https://example.com/0", "https://example.com/1"]
    assert fake_ddgs.calls[0]["max_results"] == 2
