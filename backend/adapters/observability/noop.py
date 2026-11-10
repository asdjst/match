import uuid


class NoopTracer:
    """W1 无观测后端时的占位 trace：run_id 仍生成，供 SSE 与任务查询。"""

    def start(self, name: str, metadata: dict | None = None) -> str:
        return str(uuid.uuid4())

    def event(self, trace_id: str, name: str, data: dict | None = None) -> None:
        pass

    def end(self, trace_id: str, output: dict | None = None) -> None:
        pass
