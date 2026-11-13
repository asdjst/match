import json
import os
from dataclasses import dataclass, field
from pathlib import Path


def _fix_broken_no_proxy() -> None:
    """本机 NO_PROXY 带 [::1]，httpx 解析会抛 Invalid port 让所有出网请求崩；
    括号形式条目对直连网关无用，进程内剔除。"""
    for var in ("NO_PROXY", "no_proxy"):
        val = os.environ.get(var)
        if val and "[::1]" in val:
            os.environ[var] = ",".join(x for x in val.split(",") if x.strip() != "[::1]")


def _use_local_model_cost_map() -> None:
    """litellm 默认联网拉模型价目表，出网受限时首次调用要白等 30–90s 重试；
    价目表只用于成本统计，用内置备份即可，也不影响断网演示。"""
    os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")


def _load_env_file() -> None:
    """加载 backend/.env；已在 os.environ 的变量优先，不被覆盖。"""
    _fix_broken_no_proxy()
    _use_local_model_cost_map()
    path = Path(__file__).resolve().parent.parent / ".env"
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())


def _env(key: str, default: str = "") -> str:
    return os.environ.get(f"MRAG_{key}", default)


def _json_env(key: str) -> dict:
    raw = _env(key)
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


@dataclass
class TierConfig:
    model: str = ""
    api_base: str = ""
    api_key: str = ""
    extra_headers: dict = field(default_factory=dict)
    # 透传给 OpenAI 兼容端点的额外请求体，如关闭思考模式 {"thinking":{"type":"disabled"}}
    extra_body: dict = field(default_factory=dict)


@dataclass
class Settings:
    mode: str = "fake"                  # fake | live
    r2r_base_url: str = "http://localhost:7272"
    r2r_api_key: str = ""
    r2r_collection: str = "gluco"
    fast: TierConfig = field(default_factory=TierConfig)
    strong: TierConfig = field(default_factory=TierConfig)
    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""
    langfuse_host: str = "http://localhost:3000"
    refusal_threshold: float = 0.45
    retriever_top_k: int = 8
    web_search: bool = True
    web_search_top_k: int = 3
    web_search_proxy: str = ""
    web_search_timeout_s: float = 3.0
    web_provider: str = "ddgs"          # ddgs | bocha | tavily
    web_api_key: str = ""
    gdrive_api_key: str = ""
    gdrive_folder_id: str = ""
    gdrive_client_id: str = ""
    gdrive_client_secret: str = ""
    gdrive_refresh_token: str = ""
    gdrive_service_account_json: str = ""
    gdrive_proxy: str = ""
    gdrive_top_k: int = 3
    # 整轮检索硬上限：本地库通常 <1s，联网失败最多等这么久，不能让用户陪跑
    retrieval_timeout_s: float = 8.0
    answer_cache: bool = True
    answer_cache_sim: float = 0.93
    answer_cache_ttl_s: int = 604800
    embeddings_url: str = "http://localhost:7997"
    embeddings_model: str = "BAAI/bge-small-zh-v1.5"
    embeddings_timeout_s: float = 1.5
    db_path: str = ""
    runs_retention_days: int = 0
    upload_dir: str = ""
    funasr_url: str = ""
    # 逗号分隔的白名单；默认只放本机开发端口，部署时显式改成前端域名
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            mode=_env("MODE", "fake"),
            r2r_base_url=_env("R2R_BASE_URL", "http://localhost:7272"),
            r2r_api_key=_env("R2R_API_KEY"),
            r2r_collection=_env("R2R_COLLECTION", "gluco"),
            fast=TierConfig(
                model=_env("FAST_MODEL", "openai/gpt-4o-mini"),
                api_base=_env("FAST_BASE_URL"),
                api_key=_env("FAST_API_KEY"),
                extra_headers=_json_env("FAST_EXTRA_HEADERS"),
                extra_body=_json_env("FAST_EXTRA_BODY"),
            ),
            strong=TierConfig(
                model=_env("STRONG_MODEL", "openai/gpt-4o"),
                api_base=_env("STRONG_BASE_URL"),
                api_key=_env("STRONG_API_KEY"),
                extra_headers=_json_env("STRONG_EXTRA_HEADERS"),
                extra_body=_json_env("STRONG_EXTRA_BODY"),
            ),
            langfuse_public_key=_env("LANGFUSE_PUBLIC_KEY"),
            langfuse_secret_key=_env("LANGFUSE_SECRET_KEY"),
            langfuse_host=_env("LANGFUSE_HOST", "http://localhost:3000"),
            refusal_threshold=float(_env("REFUSAL_THRESHOLD", "0.45")),
            retriever_top_k=int(_env("RETRIEVER_TOP_K", "8")),
            web_search=_env("WEB_SEARCH", "1") not in ("0", "false", "off"),
            web_search_top_k=int(_env("WEB_SEARCH_TOP_K", "3")),
            web_search_proxy=_env("WEB_SEARCH_PROXY"),
            web_search_timeout_s=float(_env("WEB_SEARCH_TIMEOUT_S", "3")),
            web_provider=_env("WEB_PROVIDER", "ddgs").strip().lower() or "ddgs",
            web_api_key=_env("WEB_API_KEY").strip(),
            gdrive_api_key=_env("GDRIVE_API_KEY"),
            gdrive_folder_id=_env("GDRIVE_FOLDER_ID"),
            gdrive_client_id=_env("GDRIVE_CLIENT_ID"),
            gdrive_client_secret=_env("GDRIVE_CLIENT_SECRET"),
            gdrive_refresh_token=_env("GDRIVE_REFRESH_TOKEN"),
            gdrive_service_account_json=_env("GDRIVE_SERVICE_ACCOUNT_JSON"),
            gdrive_proxy=_env("GDRIVE_PROXY"),
            gdrive_top_k=int(_env("GDRIVE_TOP_K", "3")),
            retrieval_timeout_s=float(_env("RETRIEVAL_TIMEOUT_S", "8")),
            answer_cache=_env("ANSWER_CACHE", "1") not in ("0", "false", "off"),
            answer_cache_sim=float(_env("ANSWER_CACHE_SIM", "0.93")),
            answer_cache_ttl_s=int(_env("ANSWER_CACHE_TTL_S", "604800")),
            embeddings_url=_env("EMBEDDINGS_URL", "http://localhost:7997"),
            embeddings_model=_env("EMBEDDINGS_MODEL", "BAAI/bge-small-zh-v1.5"),
            embeddings_timeout_s=float(_env("EMBEDDINGS_TIMEOUT_S", "1.5")),
            db_path=_env("DB_PATH"),
            runs_retention_days=int(_env("RUNS_RETENTION_DAYS", "0")),
            upload_dir=_env("UPLOAD_DIR"),
            funasr_url=_env("FUNASR_URL"),
            cors_origins=_env("CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173"),
        )

    def require_live(self) -> None:
        if self.mode != "live":
            return
        if not self.r2r_base_url:
            raise ValueError("live 模式必须配置 MRAG_R2R_BASE_URL")
        for name, tier in (("fast", self.fast), ("strong", self.strong)):
            if not tier.model or not tier.api_key:
                raise ValueError(f"live 模式必须配置 MRAG_{name.upper()}_MODEL 与 MRAG_{name.upper()}_API_KEY")


def get_settings() -> Settings:
    _load_env_file()
    return Settings.from_env()
