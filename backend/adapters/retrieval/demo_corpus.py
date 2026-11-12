from pathlib import Path

from adapters.parsing.markdown_parsing import MarkdownParser
from core.schemas.common import SourceRef
from core.schemas.evidence import Evidence

KNOWLEDGE_DIR = Path(__file__).resolve().parents[2] / "demo_assets" / "gluco_knowledge"


def build_demo_corpus() -> list[Evidence]:
    """离线语料直接读入库用的控糖知识卡，fake 与 live 因此命中同一批原文，不需要另维护一份假数据。"""
    parser = MarkdownParser()
    corpus: list[Evidence] = []
    for path in sorted(KNOWLEDGE_DIR.glob("*.md")):
        for passage in parser.parse(path):
            corpus.append(
                Evidence(
                    doc_id=path.stem,
                    quote=passage.text,
                    source=SourceRef(file_path=path.name, section=passage.section),
                )
            )
    return corpus