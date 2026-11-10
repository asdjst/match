import json
import time
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
                    score=float(item.get("score", 0.0)),
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
