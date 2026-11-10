import json
import re
import time
from pathlib import Path

import httpx

from core.schemas.common import SourceRef
from core.schemas.evidence import Evidence

_SNIPPET_MAX = 400
_SCOPES = "https://www.googleapis.com/auth/drive.readonly"

# fullText 逐字匹配，中文整句几乎搜不到；按虚词/年份切开，只保留实义词组
_SPLIT_CHARS = set("的了是和与及或年月份相比怎么样多少什么如何哪这那请帮我查一下找")


class GDriveRetriever:
    """云端网盘渠道：Google Drive API v3。
    鉴权优先级：OAuth 刷新令牌（私有网盘）> 服务账号 JSON（共享文件夹）> API key（仅公开文件）。
    fullText 全文检索 → 拉取文本内容 → 切片为可引用证据。
    未配置凭据或请求失败时 recall 返回空，由 MultiSourceRetriever 在报告里标注。"""

    SEARCH_URL = "https://www.googleapis.com/drive/v3/files"
    EXPORT_URL = "https://www.googleapis.com/drive/v3/files/{file_id}/export"
    DOWNLOAD_URL = "https://www.googleapis.com/drive/v3/files/{file_id}"
    TOKEN_URL = "https://oauth2.googleapis.com/token"

    # 文本类 MIME：Google Docs 直接导出纯文本，纯文本类型走 alt=media
    EXPORTABLE = {
        "application/vnd.google-apps.document": "text/plain",
        "application/vnd.google-apps.spreadsheet": "text/csv",
    }
    PLAIN_TEXT = {
        "text/plain",
        "text/csv",
        "text/markdown",
        "application/json",
        "text/html",
    }

    def __init__(
        self,
        api_key: str = "",
        folder_id: str | None = None,
        top_k: int = 3,
        timeout_s: float = 15.0,
        client_id: str = "",
        client_secret: str = "",
        refresh_token: str = "",
        service_account: str = "",
        proxy: str = "",
    ) -> None:
        self._key = api_key
        self._folder = folder_id
        self._top_k = top_k
        self._oauth = (client_id, client_secret, refresh_token)
        self._service_account = self._load_service_account(service_account)
        self._access_token: str | None = None
        self._token_expiry = 0.0
        # Google 域名通常需走本地代理；trust_env=False 避免 NO_PROXY 解析问题，代理显式传入
        self._http = httpx.Client(timeout=timeout_s, trust_env=False, proxy=proxy or None)

    @staticmethod
    def _load_service_account(raw: str) -> dict:
        """支持 JSON 文本或 JSON 文件路径。"""
        if not raw:
            return {}
        try:
            if raw.lstrip().startswith("{"):
                return json.loads(raw)
            return json.loads(Path(raw).expanduser().read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}

    @property
    def enabled(self) -> bool:
        return bool(self._key or all(self._oauth) or self._service_account)

    def recall(self, query: str, filters: dict | None = None) -> list[Evidence]:
        if not self.enabled:
            return []
        files = self._search(query)
        out: list[Evidence] = []
        for f in files:
            text = self._fetch_text(f)
            if not text:
                continue
            name = f.get("name") or f["id"]
            out.append(
                Evidence(
                    doc_id=f"drive:{f['id']}",
                    quote=text[:_SNIPPET_MAX],
                    score=0.8,
                    source=SourceRef(file_path=f"drive://{name}"),
                    channel="cloud",
                )
            )
            if len(out) >= self._top_k:
                break
        return out

    def _auth_params(self) -> tuple[dict, dict]:
        """OAuth / 服务账号走 Bearer（能看私有网盘），否则退回 API key。"""
        token = ""
        if all(self._oauth):
            token = self._get_refresh_token_access()
        elif self._service_account:
            token = self._get_service_account_access()
        if token:
            return {}, {"Authorization": f"Bearer {token}"}
        return {"key": self._key}, {}

    def _cached_token(self) -> str:
        if self._access_token and time.monotonic() < self._token_expiry - 60:
            return self._access_token
        return ""

    def _store_token(self, body: dict) -> str:
        self._access_token = body["access_token"]
        self._token_expiry = time.monotonic() + float(body.get("expires_in", 3600))
        return self._access_token

    def _get_refresh_token_access(self) -> str:
        cached = self._cached_token()
        if cached:
            return cached
        client_id, client_secret, refresh_token = self._oauth
        resp = self._http.post(
            self.TOKEN_URL,
            data={
                "client_id": client_id,
                "client_secret": client_secret,
                "refresh_token": refresh_token,
                "grant_type": "refresh_token",
            },
        )
        resp.raise_for_status()
        return self._store_token(resp.json())

    def _get_service_account_access(self) -> str:
        cached = self._cached_token()
        if cached:
            return cached
        import jwt  # PyJWT[crypto]：仅服务账号模式需要

        info = self._service_account
        now = int(time.time())
        assertion = jwt.encode(
            {
                "iss": info["client_email"],
                "scope": _SCOPES,
                "aud": info.get("token_uri", self.TOKEN_URL),
                "iat": now,
                "exp": now + 3600,
            },
            info["private_key"],
            algorithm="RS256",
        )
        resp = self._http.post(
            info.get("token_uri", self.TOKEN_URL),
            data={
                "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                "assertion": assertion,
            },
        )
        resp.raise_for_status()
        return self._store_token(resp.json())

    def _search(self, query: str) -> list[dict]:
        terms = _terms(query)
        if not terms:
            return []
        clauses = " or ".join(f'fullText contains "{t}"' for t in terms)
        q = f"({clauses}) and trashed = false"
        if self._folder:
            q += f' and "{self._folder}" in parents'
        params, headers = self._auth_params()
        resp = self._http.get(
            self.SEARCH_URL,
            params={
                "q": q,
                "pageSize": self._top_k * 3,
                "fields": "files(id,name,mimeType)",
                "includeItemsFromAllDrives": "true",
                "supportsAllDrives": "true",
                **params,
            },
            headers=headers,
        )
        resp.raise_for_status()
        return resp.json().get("files", [])

    def _fetch_text(self, f: dict) -> str:
        mime = f.get("mimeType", "")
        if mime == "application/pdf":
            return self._fetch_pdf(f)
        if mime == "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
            return self._fetch_docx(f)
        if mime not in self.EXPORTABLE and mime not in self.PLAIN_TEXT:
            return ""
        _, headers = self._auth_params()
        try:
            if mime in self.EXPORTABLE:
                resp = self._http.get(
                    self.EXPORT_URL.format(file_id=f["id"]),
                    params={"mimeType": self.EXPORTABLE[mime]},
                    headers=headers,
                )
            else:
                resp = self._http.get(
                    self.DOWNLOAD_URL.format(file_id=f["id"]),
                    params={"alt": "media", "supportsAllDrives": "true"},
                    headers=headers,
                )
            resp.raise_for_status()
            return resp.text.strip()
        except httpx.HTTPError:
            return ""

    def _fetch_pdf(self, f: dict) -> str:
        """Drive 里的 PDF：下载后用 pypdf 抽前几页文本，作为可引用证据。"""
        from io import BytesIO

        from pypdf import PdfReader

        _, headers = self._auth_params()
        try:
            resp = self._http.get(
                self.DOWNLOAD_URL.format(file_id=f["id"]),
                params={"alt": "media", "supportsAllDrives": "true"},
                headers=headers,
            )
            resp.raise_for_status()
            reader = PdfReader(BytesIO(resp.content))
            pages = [(page.extract_text() or "").strip() for page in reader.pages[:5]]
            return "\n".join(p for p in pages if p).strip()
        except Exception:
            return ""

    def _fetch_docx(self, f: dict) -> str:
        """Drive 里上传的 Word 文档：抓正文段落文本。"""
        from io import BytesIO

        from docx import Document

        _, headers = self._auth_params()
        try:
            resp = self._http.get(
                self.DOWNLOAD_URL.format(file_id=f["id"]),
                params={"alt": "media", "supportsAllDrives": "true"},
                headers=headers,
            )
            resp.raise_for_status()
            doc = Document(BytesIO(resp.content))
            return "\n".join(p.text.strip() for p in doc.paragraphs if p.text.strip())
        except Exception:
            return ""


def _terms(query: str) -> list[str]:
    """Drive fullText 逐字匹配：去掉数字/标点，按虚词切出实义词组（2-6 字），OR 连接提高召回。"""
    cleaned = re.sub(r"[^\u4e00-\u9fffA-Za-z0-9]+", " ", query)
    cleaned = re.sub(r"[0-9]+", " ", cleaned)
    words: list[str] = []
    for chunk in re.findall(r"[\u4e00-\u9fff]+", cleaned):
        segment = ""
        for ch in chunk:
            if ch in _SPLIT_CHARS:
                if len(segment) >= 2:
                    words.append(segment)
                segment = ""
            else:
                segment += ch
        if len(segment) >= 2:
            words.append(segment)
    words.extend(re.findall(r"[A-Za-z]{3,}", cleaned))
    return [w[:6] for w in dict.fromkeys(words)][:4]
