import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from urllib.parse import urlparse

import httpx

from core.schemas.common import SourceRef
from core.schemas.evidence import Evidence

_CACHE_TTL_S = 300.0
# DDGS 各引擎在本机网络下会被间歇性限流；单次约 1-7s，失败多为「No results」。
# 长查询常被引擎判定为无结果，因此先用截短的关键词查，再回退到完整 query；
# Bing 与 Yahoo 的召回互补，任一成功即缓存。
_BACKENDS = ("yahoo", "bing")
# 串行 + 最小间隔，避免多检索节点并发触发同一引擎限流
_MIN_GAP_S = 0.8
# 整次联网检索的硬截止：本地库已经能答时，联网只是补充，不能让用户陪跑
_DEADLINE_S = 4.0
# 一次失败后的冷却：同一轮里多个检索节点不再重复撞同一个限流
_COOLDOWN_S = 20.0
_MAX_QUOTE_CHARS = 420

# 医疗健康问题优先采信官方/学会/期刊来源；只做排序加权，不做硬过滤
_AUTHORITATIVE_DOMAINS = (
    "nhc.gov.cn",
    "chinacdc.cn",
    "cds.org.cn",
    "cma.org.cn",
    "who.int",
    "diabetesjournals.org",
    "cnki.net",
    "medlive.cn",
)

_BOCHA_URL = "https://api.bocha.cn/v1/web-search"
_TAVILY_URL = "https://api.tavily.com/search"


def _query_variants(query: str) -> list[str]:
    """长 query 先截成前两个关键词，再去掉口语填充词，避免引擎判为 No results。"""
    full = " ".join((query or "").split())
    cleaned = re.sub(r"(请问|大概|大约|约|一下|呢|吗|[？?！!。])", "", full).strip()
    short = " ".join(cleaned.split()[:2]).replace("碳水化合物", "碳水")
    out: list[str] = []
    for q in (short, cleaned):
        if q and q not in out:
            out.append(q)
    return out


def _clip(text: str) -> str:
    text = " ".join((text or "").split())
    return text[:_MAX_QUOTE_CHARS]


def _is_authoritative(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return any(host == d or host.endswith("." + d) for d in _AUTHORITATIVE_DOMAINS)


def _evidence(doc_id: str, title: str, body: str, rank: int, url: str) -> Evidence:
    title = (title or "").strip()
    quote = f"{title}：{body}" if title and body else (title or body)
    return Evidence(
        doc_id=url,
        quote=_clip(quote),
        score=min(1.0, (1.0 - rank * 0.1) + (0.15 if _is_authoritative(url) else 0.0)),
        source=SourceRef(file_path=url),
        channel="web",
    )


class WebSearchRetriever:
    """Web 渠道：优先调用带 key 的搜索 API（博查/Tavily），失败或未配置时回退 DDGS。
    结果标题+摘要映射成 Evidence，doc_id 用链接；同一 query 短时缓存。"""

    def __init__(
        self,
        top_k: int = 3,
        timeout_s: float = 4.0,
        proxy: str | None = None,
        provider: str = "ddgs",
        api_key: str = "",
        deadline_s: float = _DEADLINE_S,
    ) -> None:
        self._top_k = top_k
        self._timeout_s = timeout_s
        self._proxy = proxy or None
        self._provider = provider if provider in ("bocha", "tavily") and api_key else "ddgs"
        self._api_key = api_key if self._provider != "ddgs" else ""
        self._deadline_s = deadline_s
        self._cache: dict[str, tuple[float, list[Evidence]]] = {}
        self._lock = threading.Lock()
        self._search_lock = threading.Lock()
        self._last_search_at = 0.0
        self._cooldown_until = 0.0

    @property
    def provider(self) -> str:
        return self._provider

    def recall(self, query: str, filters: dict | None = None) -> list[Evidence]:
        cached = self._cached(query)
        if cached is not None:
            return cached
        if time.monotonic() < self._cooldown_until:
            raise RuntimeError("联网检索冷却中（上次失败，20s 后重试）")
        # DDGS 自带的 timeout 只约束单次 HTTP 请求，遇到卡住的后端仍会超出截止；
        # 外层再套一层硬超时，保证检索节点不会被联网拖过 deadline。
        executor = ThreadPoolExecutor(max_workers=1)
        try:
            fut = executor.submit(self._search_with_retry, query)
            hits = fut.result(timeout=self._deadline_s)
        except (FutureTimeout, TimeoutError) as exc:
            self._cooldown_until = time.monotonic() + _COOLDOWN_S
            raise TimeoutError(f"联网检索超过 {self._deadline_s:g}s") from exc
        except Exception:
            self._cooldown_until = time.monotonic() + _COOLDOWN_S
            raise
        finally:
            executor.shutdown(wait=False)
        self._cooldown_until = 0.0
        with self._lock:
            self._cache[query] = (time.monotonic(), hits)
        return hits

    def _search_with_retry(self, query: str) -> list[Evidence]:
        last_exc: Exception | None = None
        deadline = time.monotonic() + self._deadline_s
        for q in _query_variants(query):
            for provider in self._provider_chain():
                if time.monotonic() >= deadline:
                    raise TimeoutError(f"联网检索超过 {self._deadline_s:g}s") from last_exc
                try:
                    with self._search_lock:
                        if provider == "ddgs":
                            gap = time.monotonic() - self._last_search_at
                            if gap < _MIN_GAP_S:
                                time.sleep(_MIN_GAP_S - gap)
                        try:
                            return self._search(q, provider, deadline)
                        finally:
                            if provider == "ddgs":
                                self._last_search_at = time.monotonic()
                except Exception as exc:  # 限流/无结果：换后端、换 provider 或缩短 query 再试
                    last_exc = exc
        assert last_exc is not None
        raise last_exc

    def _provider_chain(self) -> tuple[str, ...]:
        if self._provider == "ddgs":
            return ("ddgs",)
        # 付费 API 失败时仍用免 key 搜索兜底，避免整条联网通道空转
        return (self._provider, "ddgs")

    def _cached(self, query: str) -> list[Evidence] | None:
        with self._lock:
            entry = self._cache.get(query)
        if entry and time.monotonic() - entry[0] < _CACHE_TTL_S:
            return entry[1]
        return None

    def _search(self, query: str, provider: str, deadline: float) -> list[Evidence]:
        if provider == "bocha":
            return self._search_bocha(query, deadline)
        if provider == "tavily":
            return self._search_tavily(query, deadline)
        return self._search_ddgs(query, deadline)

    def _remaining(self, deadline: float) -> float:
        return max(0.8, min(self._timeout_s, deadline - time.monotonic()))

    def _search_ddgs(self, query: str, deadline: float) -> list[Evidence]:
        from ddgs import DDGS

        last_exc: Exception | None = None
        for backend in _BACKENDS:
            if time.monotonic() >= deadline:
                break
            try:
                results = DDGS(proxy=self._proxy).text(
                    query, max_results=self._top_k, timeout=self._remaining(deadline), backend=backend
                )
                return self._map_ranked(
                    [(r.get("title"), r.get("href"), r.get("body")) for r in results]
                )
            except Exception as exc:
                last_exc = exc
        if last_exc is None:
            raise TimeoutError("联网检索截止时间已到")
        raise last_exc

    def _search_bocha(self, query: str, deadline: float) -> list[Evidence]:
        resp = httpx.post(
            _BOCHA_URL,
            headers={"Authorization": f"Bearer {self._api_key}"},
            json={"query": query, "count": self._top_k, "summary": True, "freshness": "noLimit"},
            timeout=self._remaining(deadline),
            trust_env=False,
        )
        resp.raise_for_status()
        data = resp.json().get("data") or {}
        pages = (data.get("webPages") or {}).get("value") or []
        return self._map_ranked(
            [(p.get("name"), p.get("url"), p.get("summary") or p.get("snippet")) for p in pages]
        )

    def _search_tavily(self, query: str, deadline: float) -> list[Evidence]:
        resp = httpx.post(
            _TAVILY_URL,
            headers={"Authorization": f"Bearer {self._api_key}"},
            json={
                "api_key": self._api_key,
                "query": query,
                "max_results": self._top_k,
                "search_depth": "basic",
            },
            timeout=self._remaining(deadline),
            trust_env=False,
        )
        resp.raise_for_status()
        results = resp.json().get("results") or []
        return self._map_ranked([(r.get("title"), r.get("url"), r.get("content")) for r in results])

    def _map_ranked(self, rows) -> list[Evidence]:
        """统一映射：跳过无链接结果，原文截断控制 prompt 体积，权威域名加权后重排。"""
        out: list[Evidence] = []
        for title, url, body in rows:
            url = (url or "").strip()
            if not url:
                continue
            out.append(_evidence(url, title or "", body or "", len(out), url))
            if len(out) >= self._top_k:
                break
        out.sort(key=lambda ev: (_is_authoritative(ev.doc_id), ev.score), reverse=True)
        return out

    def probe(self) -> float:
        """连通性自检，返回耗时；不可用抛异常。"""
        start = time.monotonic()
        self._search_with_retry("糖尿病 膳食指南")
        return time.monotonic() - start
