"""把本地控糖知识卡（Markdown 摘编）解析入库：按二级标题切段，section 直接来自标题。

用法:
  .venv/bin/python scripts/seed_r2r.py                  # 入库整个目录
  .venv/bin/python scripts/seed_r2r.py 某文件.md ...    # 只入库指定文件（避免重复导入）
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from adapters.parsing import parse_file, passage_metadata
from adapters.retrieval.r2r_client import R2RClient
from infra.config import get_settings

KNOWLEDGE_DIR = Path(__file__).resolve().parent.parent / "demo_assets" / "gluco_knowledge"


def main() -> None:
    settings = get_settings()
    parser = argparse.ArgumentParser(description="把知识卡入库到本地 R2R")
    parser.add_argument("files", nargs="*", help="只入库这些文件；省略则入库整个知识卡目录")
    args = parser.parse_args()
    if args.files:
        files = [Path(f).resolve() for f in args.files]
        missing = [str(f) for f in files if not f.is_file()]
        if missing:
            print(f"文件不存在：{', '.join(missing)}")
            return
    else:
        files = sorted(KNOWLEDGE_DIR.glob("*.md"))
    if not files:
        print(f"未找到知识卡：{KNOWLEDGE_DIR}")
        return
    client = R2RClient(settings.r2r_base_url, settings.r2r_collection, settings.r2r_api_key)
    total = 0
    for path in files:
        passages, modality = parse_file(path, settings)
        for p in passages:
            meta = passage_metadata(path.name, modality, p, settings.r2r_collection)
            client.ingest_text(p.text, meta)
        total += len(passages)
        print(f"{path.name}: {len(passages)} 段 ({modality})")
    print(f"done: {total} 段入库 → collection={settings.r2r_collection}")


if __name__ == "__main__":
    main()
