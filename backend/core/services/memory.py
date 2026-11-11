def answer_snippet(deliverable: dict | None, limit: int = 160) -> str:
    """把交付物压成一句可回填的答案摘要（拒答保留原因）。"""
    d = deliverable or {}
    if d.get("refused"):
        return f"（拒答）{d.get('refusal_reason') or ''}"[:limit]
    texts = [a.get("text", "") for a in d.get("assertions") or []]
    return "；".join(t for t in texts if t)[:limit]


class SessionMemory:
    """会话短期记忆：每个 session 保留最近 N 轮问答，进程重启后由 RunStore 兜底回填。"""

    def __init__(self, max_items: int = 20) -> None:
        self._max_items = max_items
        self._sessions: dict[str, list[dict]] = {}

    def append(self, session_id: str, item: dict) -> None:
        items = self._sessions.setdefault(session_id, [])
        items.append(item)
        if len(items) > self._max_items:
            del items[: len(items) - self._max_items]

    def history(self, session_id: str, last: int = 5) -> list[dict]:
        return self._sessions.get(session_id, [])[-last:]
