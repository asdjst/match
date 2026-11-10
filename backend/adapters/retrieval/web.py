import threading
import time

from core.schemas.common import SourceRef
from core.schemas.evidence import Evidence

_CACHE_TTL_S = 120.0
# DDGS 各引擎在本机网络下会被间歇性限流；单次约 1-7s，失败多为「No results」，
# 因此按「Yahoo → 聚合(auto) → Yahoo」轮换重试，成功后再缓存 2 分钟。
_ATTEMPTS = ("yahoo", "auto", "yahoo")
# 串行 + 最小间隔，避免多检索节点并发触发同一引擎限流
_MIN_GAP_S = 0.8


class WebSearchRetriever:
    """Web 渠道：DuckDuckGo 系元搜索（免 key）。结果标题+摘要映射成 Evidence，doc_id 用链接。
    同一 query 的短时缓存避免审校打回重查触发限流。"""

    def __init__(self, top_k: int = 3, timeout_s: float = 8.0, proxy: str | None = None) -> None:
        self._top_k = top_k
        self._timeout_s = timeout_s
        self._proxy = proxy or None
        self._cache: dict[str, tuple[float, list[Evidence]]] = {}
        self._lock = threading.Lock()
        self._search_lock = threading.Lock()
        self._last_search_at = 0.0

    def recall(self, query: str, filters: dict | None = None) -> list[Evidence]:
        cached = self._cached(query)
        if cached is not None:
            return cached
        hits = self._search_with_retry(query)
        with self._lock:
            self._cache[query] = (time.monotonic(), hits)
        return hits

    def _search_with_retry(self, query: str) -> list[Evidence]:
        # 有代理时先走代理；最后一轮直连兜底（代理挂掉时仍可取证）
        proxies = [self._proxy, self._proxy] if self._proxy else [None]
        last_exc: Exception | None = None
        for i, backend in enumerate(_ATTEMPTS):
            proxy = proxies[i] if i < len(proxies) else None
            try:
                with self._search_lock:
                    gap = time.monotonic() - self._last_search_at
                    if gap < _MIN_GAP_S:
                        time.sleep(_MIN_GAP_S - gap)
                    try:
                        return self._search(query, backend, proxy)
                    finally:
                        self._last_search_at = time.monotonic()
            except Exception as exc:  # 引擎限流/超时：换后端（或换直连）再试
                last_exc = exc
        assert last_exc is not None
        raise last_exc

    def _cached(self, query: str) -> list[Evidence] | None:
        with self._lock:
            entry = self._cache.get(query)
        if entry and time.monotonic() - entry[0] < _CACHE_TTL_S:
            return entry[1]
        return None

    def _search(
        self, query: str, backend: str = "auto", proxy: str | None = None
    ) -> list[Evidence]:
        from ddgs import DDGS

        results = DDGS(proxy=proxy).text(
            query, max_results=self._top_k, timeout=self._timeout_s, backend=backend
        )
        out: list[Evidence] = []
        for i, item in enumerate(results):
            url = item.get("href") or ""
            if not url:
                continue
            title = (item.get("title") or "").strip()
            body = (item.get("body") or "").strip()
            out.append(
                Evidence(
                    doc_id=url,
                    quote=f"{title}：{body}" if title else body,
                    score=1.0 - i * 0.1,
                    source=SourceRef(file_path=url),
                    channel="web",
                )
            )
        return out

    def probe(self) -> float:
        """连通性自检，返回耗时；不可用抛异常。"""
        start = time.monotonic()
        self._search_with_retry("ping")
        return time.monotonic() - start
