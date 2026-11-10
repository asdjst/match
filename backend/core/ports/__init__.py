from typing import Literal, Protocol

from pydantic import BaseModel

from core.schemas.guard import GuardVerdict
from core.schemas.ingest import IngestDoc, Passage
from core.schemas.prompt import PromptBundle


class LLMClient(Protocol):
    """双档模型客户端：tier 决定快/强路由；schema 非空时必须返回该类型实例。"""

    def complete(
        self,
        prompt: PromptBundle,
        tier: Literal["fast", "strong"],
        schema: type[BaseModel] | None = None,
    ) -> BaseModel: ...


class Retriever(Protocol):
    """混合召回 + 精排 + top-k 全在 R2R 内部，实现只把检索载荷映射成 Evidence。"""

    def recall(self, query: str, filters: dict | None = None) -> list: ...


class Ingestor(Protocol):
    """多模态入库统一入口：文本/PDF 直入；表格/语音先转 markdown/转写再入。"""

    def ingest(self, doc: IngestDoc, content: str | bytes) -> str: ...


class Parser(Protocol):
    """文件 → 带定位信息的段落序列；每段独立入库形成可引用 chunk。"""

    def parse(self, path) -> list[Passage]: ...


class ToolGateway(Protocol):
    def list_tools(self) -> list[str]: ...

    def call(self, name: str, args: dict) -> dict: ...


class Guard(Protocol):
    def inspect_input(self, text: str) -> GuardVerdict: ...

    def sanitize(self, text: str) -> str: ...

    def inspect_output(self, text: str) -> GuardVerdict: ...


class Tracer(Protocol):
    def start(self, name: str, metadata: dict | None = None) -> str: ...

    def event(self, trace_id: str, name: str, data: dict | None = None) -> None: ...

    def end(self, trace_id: str, output: dict | None = None) -> None: ...
