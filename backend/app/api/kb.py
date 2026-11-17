"""知识库维护可视化：只读聚合 R2R 现状，不在接口层改数据。"""

import time
from collections import defaultdict
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app.api.deps import current_user

router = APIRouter()

LEVEL_ORDER = {"ok": 0, "warn": 1, "bad": 2}


class KbSearchIn(BaseModel):
    query: str = Field(min_length=1, max_length=200)
    limit: int = Field(default=6, ge=1, le=20)


def _client(request: Request):
    client = getattr(request.app.state, "kb", None)
    if client is None:
        raise HTTPException(503, "知识库维护只在 live 模式可用")
    return client


def _int(value) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _document_view(doc: dict, chunk: dict | None, collection: str) -> dict:
    metadata = doc.get("metadata") or {}
    text = (chunk or {}).get("text") or ""
    return {
        "id": str(doc.get("id") or ""),
        "file_path": metadata.get("file_path") or "未标注文件",
        "section": metadata.get("section") or "",
        "modality": metadata.get("modality") or "text",
        "collection": metadata.get("collection") or "",
        "tokens": _int(doc.get("total_tokens")),
        "status": doc.get("ingestion_status") or "unknown",
        "created_at": doc.get("created_at") or "",
        "in_collection": metadata.get("collection") == collection,
        "preview": " ".join(text.split())[:180],
        "text": text,
    }


def _signal(level: str, title: str, detail: str, action: str | None = None) -> dict:
    return {"level": level, "title": title, "detail": detail, "action": action}


@router.get("/api/kb/overview")
async def kb_overview(request: Request, user: str = Depends(current_user)):
    client = _client(request)
    try:
        health = client.health()
        documents, _ = client.list_documents(limit=1000)
        chunks, total_chunks = client.list_chunks(limit=1000)
        collections = client.list_collections()
    except Exception as exc:
        raise HTTPException(502, f"R2R 读取失败：{type(exc).__name__}") from exc

    configured = client.collection
    chunk_by_doc = {c["document_id"]: c for c in chunks if c.get("document_id")}
    docs = [_document_view(doc, chunk_by_doc.get(str(doc.get("id"))), configured) for doc in documents]

    files: dict[str, dict] = {}
    for doc in docs:
        entry = files.setdefault(doc["file_path"], {
            "file_path": doc["file_path"],
            "documents": 0,
            "tokens": 0,
            "in_collection": 0,
            "modalities": set(),
            "sections": [],
        })
        entry["documents"] += 1
        entry["tokens"] += doc["tokens"]
        entry["in_collection"] += int(doc["in_collection"])
        entry["modalities"].add(doc["modality"])
        entry["sections"].append({
            key: doc[key]
            for key in ("id", "section", "modality", "tokens", "status", "preview", "text", "in_collection")
        })
    for entry in files.values():
        entry["sections"].sort(key=lambda s: (s["status"], s["section"] or "~"))
        entry["modalities"] = sorted(entry["modalities"])
    file_list = sorted(files.values(), key=lambda f: (-f["documents"], f["file_path"]))

    by_text: dict[str, list[dict]] = defaultdict(list)
    for doc in docs:
        normalized = " ".join(doc["text"].split())
        if normalized:
            by_text[normalized].append(doc)
    duplicate_groups = []
    for normalized, items in by_text.items():
        if len(items) < 2:
            continue
        duplicate_groups.append({
            "count": len(items),
            "file_path": items[0]["file_path"],
            "section": items[0]["section"],
            "preview": normalized[:180],
            "document_ids": [item["id"] for item in items],
        })
    duplicate_groups.sort(key=lambda d: (-d["count"], d["file_path"]))

    modalities = defaultdict(int)
    statuses = defaultdict(int)
    for doc in docs:
        modalities[doc["modality"]] += 1
        statuses[doc["status"]] += 1

    in_collection = sum(1 for doc in docs if doc["in_collection"])
    total_tokens = sum(doc["tokens"] for doc in docs)
    # 媒体切片按文件定位即可；只有文本切片缺少小节才影响引用精度
    missing_section = sum(1 for doc in docs if doc["modality"] == "text" and not doc["section"])
    failed = sum(1 for doc in docs if doc["status"] != "success")
    mismatch = len(docs) - in_collection
    selected_collection = max(collections, key=lambda c: _int(c.get("document_count")), default={})

    if not docs or in_collection == 0 or failed:
        status = "bad"
    elif mismatch or duplicate_groups or missing_section:
        status = "warn"
    else:
        status = "ok"

    signals = [
        _signal(
            "ok" if health.get("message") == "ok" else "bad",
            "R2R 服务在线" if health.get("message") == "ok" else "R2R 健康检查异常",
            f"存储集合 {selected_collection.get('name', '未知')} 共 {selected_collection.get('document_count', 0)} 个文档",
        ),
    ]
    if not docs:
        signals.append(_signal("bad", "知识库为空", "没有可召回的文档，先运行 seed_r2r.py 入库。"))
    elif in_collection == 0:
        signals.append(_signal(
            "bad",
            "当前集合没有可召回切片",
            f"应用过滤 collection={configured}，但现有切片都不属于这个集合。",
            "核对 backend/.env 的 MRAG_R2R_COLLECTION 后重启后端。",
        ))
    elif mismatch:
        signals.append(_signal(
            "warn",
            "集合过滤有遗漏",
            f"{in_collection}/{len(docs)} 个切片属于 collection={configured}，其余切片不会被线上检索命中。",
            "统一入库 metadata.collection，或调整应用配置。",
        ))
    else:
        signals.append(_signal(
            "ok",
            "集合过滤一致",
            f"{in_collection} 个切片全部带 collection={configured}，与线上召回一致。",
        ))
    if duplicate_groups:
        signals.append(_signal(
            "warn",
            f"{len(duplicate_groups)} 组重复切片",
            "按正文精确比对发现同一内容多次入库，召回时可能重复占位。",
            "在 R2R Swagger 删除多余文档后重跑入库脚本。",
        ))
    else:
        signals.append(_signal("ok", "无重复切片", "按切片正文精确比对，未发现重复内容。"))
    if missing_section:
        signals.append(_signal(
            "warn",
            f"{missing_section} 个文本切片缺少小节",
            "引用只能定位到文件，无法落到具体小节。",
            "在源文件补二级标题后重新切片入库。",
        ))
    else:
        signals.append(_signal("ok", "引用定位完整", "全部切片都带 section 字段。"))
    signals.append(_signal(
        "ok" if failed == 0 else "bad",
        "入库状态正常" if failed == 0 else f"{failed} 个切片入库失败",
        "所有文档 ingestion_status=success。" if failed == 0 else "失败切片不会被召回，需要重新入库。",
    ))

    return {
        "status": status,
        "health": health,
        "configured_collection": configured,
        "base_url": client.base_url,
        "storage_collection": selected_collection.get("name") or "未创建",
        "storage_documents": _int(selected_collection.get("document_count")),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "totals": {
            "documents": len(docs),
            "chunks": total_chunks,
            "tokens": total_tokens,
            "files": len(file_list),
            "in_collection": in_collection,
            "mismatched": mismatch,
            "missing_section": missing_section,
            "failed": failed,
            "modalities": dict(sorted(modalities.items())),
            "statuses": dict(sorted(statuses.items())),
        },
        "files": file_list,
        "duplicates": duplicate_groups[:20],
        "signals": signals,
    }


@router.post("/api/kb/search")
async def kb_search(body: KbSearchIn, request: Request, user: str = Depends(current_user)):
    client = _client(request)
    started = time.monotonic()
    try:
        hits = client.search_chunks(body.query, body.limit)
    except Exception as exc:
        raise HTTPException(502, f"知识库召回失败：{type(exc).__name__}") from exc
    return {
        "query": body.query,
        "configured_collection": client.collection,
        "latency_ms": int((time.monotonic() - started) * 1000),
        "hits": hits,
    }
