import json
import time
from urllib.parse import quote
from uuid import uuid4

import httpx

from core.schemas.common import SourceRef
from core.schemas.evidence import Evidence


class R2RClient:
    """唯一的 R2R 适配器：混合召回(向量+全文 RRF)+精排+top-k 全在 R2R 服务端。
    端点/字段按 compose 里 pin 的 sciphiai/r2r:3.6.6 校准；禁止其他文件 import r2r。
    """

    def __init__(
        self,
        base_url: str,
        collection_id: str,
        api_key: str | None = None,
        top_k: int = 8,
        timeout_s: float = 30.0,
    ) -> None:
        self._base = base_url.rstrip("/")
        self._collection = collection_id
        self._top_k = top_k
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self._http = httpx.Client(base_url=self._base, headers=headers, timeout=timeout_s, trust_env=False)

    @property
    def collection(self) -> str:
        return self._collection

    @property
    def base_url(self) -> str:
        return self._base

    def health(self) -> dict:
        resp = self._http.get("/v3/health")
        resp.raise_for_status()
        return resp.json().get("results") or {}

    def list_collections(self, limit: int = 100) -> list[dict]:
        resp = self._http.get("/v3/collections", params={"limit": limit, "offset": 0})
        resp.raise_for_status()
        return resp.json().get("results") or []

    def list_documents(self, limit: int = 1000, offset: int = 0) -> tuple[list[dict], int]:
        resp = self._http.get("/v3/documents", params={"limit": limit, "offset": offset})
        resp.raise_for_status()
        body = resp.json()
        return body.get("results") or [], int(body.get("total_entries") or 0)

    def list_chunks(self, limit: int = 1000, offset: int = 0) -> tuple[list[dict], int]:
        resp = self._http.get("/v3/chunks", params={"limit": limit, "offset": offset})
        resp.raise_for_status()
        body = resp.json()
        out = []
        for item in body.get("results") or []:
            metadata = item.get("metadata", {}) or {}
            out.append({
                "id": str(item.get("id") or ""),
                "document_id": str(item.get("document_id") or ""),
                "text": item.get("text", ""),
                "metadata": metadata,
            })
        return out, int(body.get("total_entries") or 0)

    def search_chunks(self, query: str, limit: int = 8) -> list[dict]:
        """维护页的召回预览：与线上同集合过滤，返回向量分数便于看排序。"""
        payload = {
            "query": query,
            "search_settings": {
                "use_semantic_search": True,
                "limit": max(1, limit),
                "filters": self._filters(None),
            },
        }
        resp = self._http.post("/v3/chunks/search", json=payload)
        resp.raise_for_status()
        out = []
        for item in resp.json().get("results") or []:
            metadata = item.get("metadata", {}) or {}
            out.append({
                "id": str(item.get("id") or ""),
                "doc_id": str(item.get("document_id") or ""),
                "score": float(item.get("score") or 0.0),
                "text": item.get("text", ""),
                "file_path": metadata.get("file_path"),
                "section": metadata.get("section"),
                "modality": metadata.get("modality", "text"),
            })
        return out

    def recall(self, query: str, filters: dict | None = None) -> list[Evidence]:
        payload = {
            "query": query,
            "search_settings": {
                "use_hybrid_search": True,
                "limit": 50,
                "filters": self._filters(filters),
            },
        }
        resp = self._http.post("/v3/retrieval/search", json=payload)
        resp.raise_for_status()
        return self._map(resp.json())

    def ingest_text(self, raw_text: str, metadata: dict | None = None, timeout_s: float = 180.0) -> str:
        """单段文本入库（fast 模式、不走编排器），轮询到 ingestion_status 结束。"""
        doc_id = str(uuid4())
        data = {
            "id": doc_id,
            "raw_text": raw_text,
            "metadata": json.dumps(metadata or {}, ensure_ascii=False),
            "ingestion_mode": "fast",
            "run_with_orchestration": "false",
        }
        resp = self._http.post("/v3/documents", data=data)
        resp.raise_for_status()
        self._wait_ingested(doc_id, timeout_s)
        return doc_id

    def ingest(self, doc, content: str | bytes) -> str:
        """Ingestor 端口适配：IngestDoc 的 SourceRef 平铺进 metadata 后走文本入库。"""
        metadata = {"collection": doc.collection_id, "modality": doc.modality}
        metadata.update(doc.source.model_dump(exclude_none=True))
        metadata.pop("modality", None)
        text = content.decode("utf-8") if isinstance(content, bytes) else content
        return self.ingest_text(text, metadata)

    def _wait_ingested(self, doc_id: str, timeout_s: float) -> None:
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            resp = self._http.get(f"/v3/documents/{doc_id}")
            if resp.status_code == 200:
                body = resp.json()
                results = body.get("results") or {}
                status = results.get("ingestion_status") or body.get("ingestion_status")
                if status in ("success", "failed", "error"):
                    if status != "success":
                        raise RuntimeError(f"R2R ingest failed: doc={doc_id} status={status}")
                    return
            time.sleep(1.0)
        raise TimeoutError(f"R2R ingest timeout: doc={doc_id}")

    def _filters(self, filters: dict | None) -> dict:
        base = {"collection": {"$eq": self._collection}}
        if filters and "modality" in filters:
            base["modality"] = {"$eq": filters["modality"]}
        return base

    def _map(self, payload: dict) -> list[Evidence]:
        results = payload.get("results", payload)
        chunks = results.get("chunk_search_results") or []
        out: list[Evidence] = []
        for item in chunks[: self._top_k]:
            metadata = item.get("metadata", {}) or {}
            out.append(
                Evidence(
                    doc_id=str(item.get("document_id") or metadata.get("document_id") or "r2r"),
                    quote=item.get("text", ""),
                    score=max(0.0, min(1.0, float(item.get("score", 0.0)))),
                    source=SourceRef(
                        file_path=metadata.get("file_path"),
                        section=metadata.get("section"),
                        page=metadata.get("page"),
                        time_code=metadata.get("time_code"),
                        modality=metadata.get("modality", "text"),
                    ),
                )
            )
        return out
