import re
from pathlib import Path

from core.schemas.ingest import Passage

_H2 = re.compile(r"^##\s+(.+?)\s*$", re.M)


class MarkdownParser:
    """Markdown 知识卡按二级标题切段；标题即引用定位的 section。"""

    def parse(self, path: Path) -> list[Passage]:
        text = path.read_text(encoding="utf-8")
        matches = list(_H2.finditer(text))
        if not matches:
            body = text.strip()
            return [Passage(text=body)] if body else []
        out: list[Passage] = []
        for i, m in enumerate(matches):
            end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
            body = text[m.end() : end].strip()
            if body:
                out.append(Passage(text=body, section=m.group(1).strip()))
        return out
