import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout, as_completed

from core.schemas.evidence import Evidence

CHANNEL_LABELS = {"local": "本地库", "web": "Web", "cloud": "云端网盘"}


class MultiSourceRetriever:
    """三通道扇出：本地库（R2R）必选，Web/云端网盘可缺省。
    recall 返回合并去重后的证据；每次调用后 last_report 记录各通道命中/耗时/状态，
    检索节点把它写进 node_results，前端与数据库都可见。"""

    def __init__(
        self,
        sources: dict[str, object],
        per_channel_top_k: dict[str, int] | None = None,
        timeout_s: float = 20.0,
    ) -> None:
        self._sources = sources
        self._top_k = per_channel_top_k or {}
        self._timeout_s = timeout_s
        self.last_report: list[dict] = []

    def recall(self, query: str, filters: dict | None = None) -> list[Evidence]:
        started = time.monotonic()
        report: dict[str, dict] = {}
        merged: list[Evidence] = []

        futures = {}
        pool = ThreadPoolExecutor(max_workers=max(len(self._sources), 1))
        try:
            for name, source in self._sources.items():
                if not getattr(source, "enabled", True):
                    report[name] = {"hits": 0, "latency_ms": 0, "status": "未配置"}
                    continue
                futures[pool.submit(source.recall, query, filters)] = name
            try:
                for fut in as_completed(futures, timeout=self._timeout_s):
                    name = futures[fut]
                    latency = int((time.monotonic() - started) * 1000)
                    try:
                        hits = fut.result()[: self._top_k.get(name, 10**6)]
                        merged.extend(hits)
                        report[name] = {"hits": len(hits), "latency_ms": latency, "status": "ok"}
                    except Exception as exc:  # 单通道故障不拖垮整体检索
                        report[name] = {"hits": 0, "latency_ms": latency, "status": f"失败：{type(exc).__name__}"}
            except FutureTimeout:
                pass
            for fut, name in futures.items():
                if name not in report:
                    report[name] = {"hits": 0, "latency_ms": int((time.monotonic() - started) * 1000), "status": "超时"}
        finally:
            pool.shutdown(wait=False)

        self.last_report = [
            {"channel": name, **r} for name, r in report.items()
        ]
        return _dedup(merged)


def _dedup(items: list[Evidence]) -> list[Evidence]:
    seen: set[tuple[str, str]] = set()
    out: list[Evidence] = []
    for ev in items:
        key = (ev.doc_id, ev.quote[:80])
        if key in seen:
            continue
        seen.add(key)
        out.append(ev)
    return out
