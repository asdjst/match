class SessionMemory:
    """会话短期记忆（W1 内存版；PG 化随 checkpoint 一起做）。"""

    def __init__(self) -> None:
        self._sessions: dict[str, list[dict]] = {}

    def append(self, session_id: str, item: dict) -> None:
        self._sessions.setdefault(session_id, []).append(item)

    def history(self, session_id: str, last: int = 5) -> list[dict]:
        return self._sessions.get(session_id, [])[-last:]
