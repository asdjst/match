from typing import Literal, Optional

from pydantic import BaseModel

from core.schemas.common import SourceRef


class IngestDoc(BaseModel):
    """入库统一形态：所有模态写进 R2R 同一 collection。"""

    doc_id: str
    modality: Literal["text", "image", "audio"]
    source: SourceRef
    collection_id: str
    text: Optional[str] = None


class Passage(BaseModel):
    """解析产物：一个可独立入库、可被引用定位的文本段落。"""

    text: str
    section: Optional[str] = None
    page: Optional[int] = None
    time_code: Optional[str] = None
