import re
from pathlib import Path

from pypdf import PdfReader

from core.schemas.ingest import Passage

_NUM = re.compile(r"^\s*(\d+)[\.、]\s*")


class PdfParser:
    """PDF 逐页解析成段；带“N.”编号的段落把编号提为 section（如 第87段），
    页码取 PDF 实际页。这样引用定位信息来自文件本身，不是人工标注。"""

    def parse(self, path: Path) -> list[Passage]:
        reader = PdfReader(str(path))
        out: list[Passage] = []
        for i, page in enumerate(reader.pages, start=1):
            text = (page.extract_text() or "").strip()
            if not text:
                continue
            blocks = re.split(r"\n(?=\s*\d+[\.、])", text)
            for block in blocks:
                block = block.strip()
                if not block:
                    continue
                m = _NUM.match(block)
                out.append(Passage(text=block, page=i, section=f"第{m.group(1)}段" if m else None))
        return out
