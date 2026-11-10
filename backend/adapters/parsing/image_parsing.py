import base64
import re
from pathlib import Path

from core.schemas.ingest import Passage
from infra.config import TierConfig

_PROMPT = (
    "把图片里的表格完整转成 Markdown 表格，不解释、不漏行列；"
    "如果图里有标题或页码文字，把标题/页码放在首行输出。"
)
_PAGE = re.compile(r"第\s*(\d+)\s*页")


class VlmImageParser:
    """表格截图 → 支持图像输入的 fast 档网关模型 → markdown 文本，单段入库。"""

    def __init__(self, tier: TierConfig) -> None:
        self._tier = tier

    def parse(self, path: Path) -> list[Passage]:
        from litellm import completion

        b64 = base64.b64encode(path.read_bytes()).decode()
        resp = completion(
            model=self._tier.model,
            api_base=self._tier.api_base or None,
            api_key=self._tier.api_key or None,
            extra_headers=self._tier.extra_headers or None,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": _PROMPT},
                        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
                    ],
                }
            ],
            temperature=0,
            max_tokens=2048,
            num_retries=3,
        )
        text = (resp.choices[0].message.content or "").strip()
        if not text:
            return []
        page = None
        m = _PAGE.search(text.splitlines()[0]) if text else None
        if m:
            page = int(m.group(1))
        return [Passage(text=text, page=page)]
