"""MultiSourceRetriever：渠道扇出、配额截断、降级状态与检索报告。"""

from adapters.retrieval.multi import MultiSourceRetriever
from core.schemas.evidence import Evidence


class FakeSource:
    """假渠道：enabled 控制是否参与扇出，call 记录调用次数。"""

    def __init__(self, hits: list[Evidence] | None = None, enabled: bool = True, exc: Exception | None = None):
        self._hits = hits or []
        self.enabled = enabled
        self._exc = exc
        self.calls = 0

    def recall(self, query: str, filters: dict | None = None) -> list[Evidence]:
        self.calls += 1
        if self._exc is not None:
            raise self._exc
        return list(self._hits)


def _ev(doc_id: str, quote: str = "证据", **kwargs) -> Evidence:
    return Evidence(doc_id=doc_id, quote=quote, **kwargs)


def _report(multi) -> dict[str, dict]:
    return {item["channel"]: item for item in multi.last_report}


def test_recall_merges_and_dedups_by_doc_and_quote_prefix():
    shared = _ev("d1", "同一段证据")
    local = FakeSource([shared, _ev("d2", "本地独有")])
    web = FakeSource([shared.model_copy(), _ev("d3", "Web 独有")])
    multi = MultiSourceRetriever({"local": local, "web": web})

    hits = multi.recall("查询")

    # 合并三渠道结果，同一 (doc_id, quote) 只保留一条
    assert len(hits) == 3
    assert {h.doc_id for h in hits} == {"d1", "d2", "d3"}
    assert sum(1 for h in hits if h.doc_id == "d1") == 1
    assert _report(multi)["local"]["hits"] == 2
    assert _report(multi)["web"]["hits"] == 2


def test_dedup_uses_first_80_chars_of_quote():
    head = "x" * 80
    a = _ev("d1", head + "尾部A")
    b = _ev("d1", head + "尾部B")
    multi = MultiSourceRetriever({"local": FakeSource([a, b])})

    hits = multi.recall("查询")

    # 前 80 字相同视为重复，即使尾部不同也只留一条
    assert len(hits) == 1
    assert _report(multi)["local"]["hits"] == 2


def test_per_channel_top_k_caps_hits_and_report_count():
    web_hits = [_ev(f"w{i}", f"网页结果{i}") for i in range(1, 6)]
    local_hit = _ev("l1", "本地结果")
    multi = MultiSourceRetriever(
        {"local": FakeSource([local_hit]), "web": FakeSource(web_hits)},
        per_channel_top_k={"web": 2},
    )

    hits = multi.recall("查询")

    # web 返回 5 条，配额 2 → 只保留 2 条；local 未配置配额不截断
    assert [h.doc_id for h in hits if h.doc_id.startswith("w")] == ["w1", "w2"]
    assert any(h.doc_id == "l1" for h in hits)
    assert len(hits) == 3
    assert _report(multi)["web"]["hits"] == 2


def test_disabled_channel_marked_unconfigured_and_not_called():
    unused = FakeSource([_ev("x", "不该被调用")], enabled=False)
    local = FakeSource([_ev("l1", "本地结果")])
    multi = MultiSourceRetriever({"local": local, "cloud": unused})

    hits = multi.recall("查询")

    assert [h.doc_id for h in hits] == ["l1"]
    assert unused.calls == 0
    cloud = _report(multi)["cloud"]
    assert cloud["status"] == "未配置"
    assert cloud["hits"] == 0
    assert cloud["latency_ms"] == 0


def test_channel_failure_isolated_and_status_prefixed():
    good = FakeSource([_ev("l1", "本地结果")])
    bad = FakeSource(exc=RuntimeError("boom"))
    multi = MultiSourceRetriever({"local": good, "web": bad})

    hits = multi.recall("查询")

    # 单渠道异常不拖垮整体：好渠道结果照常返回
    assert [h.doc_id for h in hits] == ["l1"]
    report = _report(multi)
    assert report["web"]["status"].startswith("失败：")
    assert "RuntimeError" in report["web"]["status"]
    assert report["web"]["hits"] == 0
    assert report["local"]["status"] == "ok"


def test_last_report_item_shape_and_reset_each_recall():
    source = FakeSource([_ev("l1", "本地结果")])
    multi = MultiSourceRetriever({"local": source})

    multi.recall("查询")
    assert len(multi.last_report) == 1
    item = multi.last_report[0]
    assert set(item) == {"channel", "hits", "latency_ms", "status"}
    assert item["channel"] == "local"
    assert item["status"] == "ok"
    assert isinstance(item["latency_ms"], int)

    # 第二次调用时渠道变为未配置：报告整体重置，不残留上一次记录
    source.enabled = False
    multi.recall("查询")
    assert multi.last_report == [
        {"channel": "local", "hits": 0, "latency_ms": 0, "status": "未配置"}
    ]
