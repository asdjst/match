import re

from adapters.retrieval.demo_corpus import build_demo_corpus
from core.schemas.evidence import Evidence

_TOKEN_RE = re.compile(r"[A-Za-z0-9]+|[\u4e00-\u9fff]+")


def _tokenize(text: str) -> set[str]:
    toks: set[str] = set()
    for w in _TOKEN_RE.findall(text.lower()):
        if w.isascii():
            # 纯数字不参与匹配：血糖读数 12.8 会撞上食物成分表里的任意数值，把无关段落顶到第一
            if not w.isdigit():
                toks.add(w)
        else:
            toks.update(w[i : i + 2] for i in range(len(w) - 1))
    return toks


class FakeRetriever:
    """内存关键词检索：中文按二元组切词打分，替代 R2R 做离线验证。"""

    def __init__(self, corpus: list[Evidence] | None = None, top_k: int = 5, min_score: float = 2.0) -> None:
        self._docs = corpus if corpus is not None else build_demo_corpus()
        self._top_k = top_k
        self._min_score = min_score
        self._doc_tokens = [(_tokenize(d.quote), d) for d in self._docs]

    def recall(self, query: str, filters: dict | None = None) -> list[Evidence]:
        q_tokens = _tokenize(query)
        scored: list[tuple[float, int, Evidence]] = []
        for i, (doc_toks, doc) in enumerate(self._doc_tokens):
            if filters and "modality" in filters and doc.source.modality != filters["modality"]:
                continue
            hits = float(len(q_tokens & doc_toks))
            if hits >= self._min_score:
                scored.append((hits, -i, doc))
        scored.sort(reverse=True)
        total = max(len(q_tokens), 1)
        return [
            doc.model_copy(update={"score": round(min(hits / total, 1.0), 3)})
            for hits, _, doc in scored[: self._top_k]
        ]
