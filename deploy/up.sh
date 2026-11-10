#!/usr/bin/env bash
# 一键起栈：docker(R2R/PG/embeddings) + 建库 + API 服务。
#   ./deploy/up.sh            live 模式（R2R + opencode 网关）
#   ./deploy/up.sh --offline  断网演示包：fake 模式全离线（假 LLM/检索/工具）
set -euo pipefail
cd "$(dirname "$0")/.."

MODE=live
if [ "${1:-}" = "--offline" ]; then
  MODE=fake
else
  docker compose -f deploy/docker-compose.yml up -d
  echo "等待 R2R 健康…"
  for _ in $(seq 1 60); do
    if curl -sf --noproxy '*' http://localhost:7272/v3/health >/dev/null 2>&1; then break; fi
    sleep 2
  done
  echo "建库（演示物料三模态）…"
  (cd backend && MRAG_MODE=live .venv/bin/python scripts/seed_r2r.py)
fi

echo "启动 API（:8000，模式=$MODE）…"
cd backend && MRAG_MODE=$MODE exec .venv/bin/python -m uvicorn app.main:app --port 8000
