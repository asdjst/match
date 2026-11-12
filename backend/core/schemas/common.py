from typing import Literal, Optional

from pydantic import BaseModel


class SourceRef(BaseModel):
    """来源锚点：引用渲染成"指南·碳水化合物 / 截图第2页 / 录音03:12"。"""

    file_path: Optional[str] = None
    section: Optional[str] = None
    page: Optional[int] = None
    time_code: Optional[str] = None
    modality: Literal["text", "image", "audio"] = "text"

    def label(self) -> str:
        parts = []
        if self.file_path:
            parts.append(self.file_path)
        if self.section is not None:
            # 解析器给的 section 可能是已定位好的"第87段"，也可能是 md 小标题，后者不能再套一层
            parts.append(f"第{self.section}段" if self.section.isdigit() else self.section)
        if self.page is not None:
            parts.append(f"第{self.page}页")
        if self.time_code:
            parts.append(self.time_code)
        return " ".join(parts) if parts else "未知来源"
