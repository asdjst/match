from pathlib import Path

from adapters.parsing.audio_parsing import FunASRParser, TranscriptParser
from adapters.parsing.image_parsing import VlmImageParser
from adapters.parsing.pdf_parsing import PdfParser
from core.schemas.ingest import Passage
from infra.config import Settings

_SUFFIX_MODALITY = {".pdf": "text", ".png": "image", ".jpg": "image", ".jpeg": "image", ".json": "audio"}


def get_parser(path: Path, settings: Settings):
    """按后缀选解析器；图片用 fast 档 VLM，转写 JSON 走兜底通道，
    配了 MRAG_FUNASR_URL 的 .wav/.m4a 走 FunASR。"""
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return PdfParser()
    if suffix in (".png", ".jpg", ".jpeg"):
        return VlmImageParser(settings.fast)
    if suffix in (".wav", ".m4a") and settings.funasr_url:
        return FunASRParser(settings.funasr_url)
    if suffix == ".json":
        return TranscriptParser()
    raise ValueError(f"暂不支持的文件类型：{path.name}")


def parse_file(path: Path, settings: Settings) -> tuple[list[Passage], str]:
    """返回 (段落列表, 该文件的模态)。"""
    suffix = path.suffix.lower()
    modality = _SUFFIX_MODALITY.get(suffix, "audio" if suffix in (".wav", ".m4a") else "text")
    return get_parser(path, settings).parse(path), modality


def passage_metadata(
    file_path: str,
    modality: str,
    passage: Passage,
    collection: str,
    display_file: str | None = None,
) -> dict:
    metadata = {
        "collection": collection,
        "modality": modality,
        "file_path": display_file or file_path,
    }
    if passage.section:
        metadata["section"] = passage.section
    if passage.page is not None:
        metadata["page"] = passage.page
    if passage.time_code:
        metadata["time_code"] = passage.time_code
    return metadata
