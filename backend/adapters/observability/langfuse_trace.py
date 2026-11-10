class LangfuseTracer:
    """Langfuse 全链路 trace（pip install langfuse 后启用；W3 接入）。"""

    def __init__(self, public_key: str, secret_key: str, host: str) -> None:
        from langfuse import Langfuse

        self._client = Langfuse(public_key=public_key, secret_key=secret_key, host=host)

    def start(self, name: str, metadata: dict | None = None) -> str:
        trace = self._client.trace(name=name, metadata=metadata or {})
        return trace.id

    def event(self, trace_id: str, name: str, data: dict | None = None) -> None:
        self._client.span(trace_id=trace_id, name=name, metadata=data or {})

    def end(self, trace_id: str, output: dict | None = None) -> None:
        trace = self._client.trace(id=trace_id)
        trace.update(output=output or {})
