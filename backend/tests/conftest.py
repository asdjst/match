"""pytest 全局前置：测试一律跑 fake 模式（显式 env 优先于 backend/.env 文件）。"""

import os

os.environ.setdefault("MRAG_MODE", "fake")
