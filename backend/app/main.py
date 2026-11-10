from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from langgraph.checkpoint.memory import MemorySaver

from adapters.guard.rule_guard import RuleGuard
from adapters.llm.fake import FakeLLM
from adapters.llm.router import LiteLLMRouter
from adapters.observability.langfuse_trace import LangfuseTracer
from adapters.observability.noop import NoopTracer
from adapters.retrieval.fake import FakeRetriever
from adapters.retrieval.gdrive import GDriveRetriever
from adapters.retrieval.multi import MultiSourceRetriever
from adapters.retrieval.r2r_client import R2RClient
from adapters.retrieval.web import WebSearchRetriever
from adapters.tools.fake import FakeTools
from adapters.tools.mcp_client import MCPToolGateway
from app.api.chat import router as chat_router
from app.api.tasks import router as tasks_router
from core.graph.builder import build_graph
from core.services.memory import SessionMemory
from core.services.store import RunStore
from infra.config import Settings, get_settings


def build_adapters(settings: Settings):
    if settings.mode == "live":
        llm = LiteLLMRouter(settings.fast, settings.strong)
        sources: dict[str, object] = {
            "local": R2RClient(settings.r2r_base_url, settings.r2r_collection, settings.r2r_api_key, settings.retriever_top_k),
        }
        if settings.web_search:
            sources["web"] = WebSearchRetriever(
                top_k=settings.web_search_top_k, proxy=settings.web_search_proxy or None
            )
        sources["cloud"] = GDriveRetriever(
            api_key=settings.gdrive_api_key,
            folder_id=settings.gdrive_folder_id or None,
            top_k=settings.gdrive_top_k,
            client_id=settings.gdrive_client_id,
            client_secret=settings.gdrive_client_secret,
            refresh_token=settings.gdrive_refresh_token,
            service_account=settings.gdrive_service_account_json,
            proxy=settings.gdrive_proxy,
        )
        retriever = MultiSourceRetriever(
            sources,
            per_channel_top_k={"local": settings.retriever_top_k, "web": settings.web_search_top_k, "cloud": settings.gdrive_top_k},
            timeout_s=settings.retrieval_timeout_s,
        )
        tools = MCPToolGateway()
        tools.start()
    else:
        # fake 模式全离线：断网演示与单测不依赖 MCP 子进程
        llm = FakeLLM()
        retriever = FakeRetriever()
        tools = FakeTools()
    guard = RuleGuard()
    if settings.langfuse_public_key and settings.langfuse_secret_key:
        tracer = LangfuseTracer(settings.langfuse_public_key, settings.langfuse_secret_key, settings.langfuse_host)
    else:
        tracer = NoopTracer()
    return llm, retriever, tools, guard, tracer


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    close = getattr(app.state.tools, "close", None)
    if close:
        close()
    app.state.store.close()


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    settings.require_live()
    llm, retriever, tools, guard, tracer = build_adapters(settings)

    app = FastAPI(title="multi-agent-rag", version="0.1.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.state.settings = settings
    app.state.llm = llm
    app.state.graph = build_graph(
        llm, retriever, tools,
        checkpointer=MemorySaver(),
        refusal_threshold=settings.refusal_threshold,
    )
    app.state.guard = guard
    app.state.tools = tools
    app.state.tracer = tracer
    app.state.runs = {}
    app.state.store = RunStore(settings.db_path or Path(__file__).resolve().parent.parent / "data" / "runs.db")
    app.state.memory = SessionMemory()
    app.include_router(chat_router)
    app.include_router(tasks_router)
    return app


app = create_app()
