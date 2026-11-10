"""把 demo_assets/ 演示物料解析入库：PDF 逐段、截图走 VLM、录音走转写 JSON。
引用定位信息（段落号/页码/时间码）来自文件本身。库重置：deploy 下 docker compose down -v。

用法: .venv/bin/python scripts/seed_r2r.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from adapters.parsing import parse_file, passage_metadata
from adapters.retrieval.r2r_client import R2RClient
from infra.config import get_settings

# (文件名, 引用展示名)。转写 JSON 的引用展示挂音频文件名
ASSETS = [
    ("A公司2024年报.pdf", None),
    ("报表截图.png", "报表截图.png"),
    ("业绩说明会_转写.json", "业绩说明会.m4a"),
]


def main() -> None:
    settings = get_settings()
    assets = Path(__file__).resolve().parent.parent / "demo_assets"
    client = R2RClient(settings.r2r_base_url, settings.r2r_collection, settings.r2r_api_key)
    total = 0
    for name, display in ASSETS:
        path = assets / name
        if not path.exists():
            print(f"跳过（缺物料，先跑 scripts/make_demo_assets.py）：{name}")
            continue
        passages, modality = parse_file(path, settings)
        for p in passages:
            meta = passage_metadata(name, modality, p, settings.r2r_collection, display_file=display)
            client.ingest_text(p.text, meta)
        total += len(passages)
        print(f"{name}: {len(passages)} 段 ({modality})")
    print(f"done: {total} 段入库")


if __name__ == "__main__":
    main()
