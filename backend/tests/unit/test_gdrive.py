"""GDriveRetriever：用假 _http 模拟 Drive API，验证配置门禁与 Evidence 映射。"""

from adapters.retrieval.gdrive import GDriveRetriever


class FakeResponse:
    def __init__(self, payload=None, text: str = ""):
        self._payload = payload
        self.text = text

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self._payload or {}


class FakeHttp:
    def __init__(self, files: list[dict], export_text: str = "导出正文", download_text: str = "下载正文"):
        self.files = files
        self.export_text = export_text
        self.download_text = download_text
        self.calls: list[tuple[str, dict]] = []

    def get(self, url: str, params: dict | None = None, headers: dict | None = None) -> FakeResponse:
        self.calls.append((url, params or {}))
        if url == GDriveRetriever.SEARCH_URL:
            return FakeResponse(payload={"files": self.files})
        if "/export" in url:
            return FakeResponse(text=self.export_text)
        return FakeResponse(text=self.download_text)


def _retriever(key: str, http: FakeHttp | None = None, top_k: int = 3) -> GDriveRetriever:
    r = GDriveRetriever(key, top_k=top_k)
    if http is not None:
        r._http = http
    return r


def test_missing_key_disabled_and_empty():
    r = GDriveRetriever("")
    # 未配置 api_key → enabled False 且不发起任何请求
    assert r.enabled is False
    assert r.recall("米饭碳水") == []


def test_google_doc_exported_to_cloud_evidence():
    http = FakeHttp(
        [
            {
                "id": "doc-1",
                "name": "营养门诊记录",
                "mimeType": "application/vnd.google-apps.document",
            }
        ],
        export_text="  门诊记录正文  ",
    )
    r = _retriever("fake-key", http)

    hits = r.recall("米饭碳水")

    assert len(hits) == 1
    ev = hits[0]
    assert ev.channel == "cloud"
    assert ev.doc_id == "drive:doc-1"
    assert ev.quote == "门诊记录正文"
    assert ev.source.file_path.startswith("drive://")
    # Google Docs 走 export 接口，导出为纯文本
    export_calls = [c for c in http.calls if "/export" in c[0]]
    assert len(export_calls) == 1
    assert export_calls[0][1]["mimeType"] == "text/plain"


def test_search_request_carries_key_and_fulltext_query():
    http = FakeHttp([])
    r = _retriever("secret-key", http)

    r.recall("米饭碳水 每100g")

    url, params = http.calls[0]
    assert url == GDriveRetriever.SEARCH_URL
    assert params["key"] == "secret-key"
    assert "fullText contains" in params["q"]
    assert "trashed = false" in params["q"]


def test_unsupported_mime_skipped():
    http = FakeHttp(
        [
            {"id": "zip-1", "name": "压缩包", "mimeType": "application/zip"},
            {"id": "doc-2", "name": "说明", "mimeType": "application/vnd.google-apps.document"},
        ]
    )
    r = _retriever("fake-key", http)

    hits = r.recall("米饭碳水")

    # 不支持的 MIME（压缩包）→ 跳过；只有 Google Docs 生成 Evidence
    assert [h.doc_id for h in hits] == ["drive:doc-2"]
    assert not any("zip-1" in url for url, _ in http.calls)
