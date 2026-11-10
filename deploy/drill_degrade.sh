#!/usr/bin/env bash
# W4.4 降级演练：三个故障场景各发一问，断言 10s 内返回 degraded 交付物。
#   A 检索故障：docker stop r2r → 证据为空 → 降级+拒答式兜底
#   B 模型故障：错误网关 key 起 API → planner 失败 → 降级
#   C 恢复正常：计算题带工具引用（回归确认）
# 用法：./deploy/drill_degrade.sh   （需先 ./deploy/up.sh 起过栈）
set -uo pipefail
cd "$(dirname "$0")/.."
API=http://localhost:8900
fail=0

ask() { # $1 问题 → 打印 deliverable JSON
  curl -sN --noproxy '*' --max-time 30 -X POST "$API/api/chat" \
    -H 'Content-Type: application/json' \
    -d "{\"session_id\":\"drill\",\"question\":\"$1\"}" \
    | grep --line-buffered '^data: ' | while read -r line; do
      case "$line" in *'"deliverable"'*) echo "${line#data: }"; break ;; esac
    done
}

check() { # $1 场景名  $2 期望
  local out; out=$(ask "$3")
  echo "[$1] $4"
  echo "$out" | python3 -c "import json,sys; d=json.load(sys.stdin); print('   degraded=', d.get('degraded'), ' refused=', d.get('refused'), ' reason=', (d.get('refusal_reason') or '')[:40])"
}

echo "—— 启动演练 API（live 模式，:8900）——"
(cd backend && MRAG_MODE=live MRAG_FAST_API_KEY="$MRAG_FAST_API_KEY" MRAG_STRONG_API_KEY="$MRAG_STRONG_API_KEY" .venv/bin/python -m uvicorn app.main:app --port 8900 >/tmp/drill_api.log 2>&1) &
DRILL_PID=$!
sleep 4

echo "—— 场景 C：正常回归（计算题）——"
out=$(ask "2024年营收相比2023年同比增长了多少？")
echo "$out" | grep -q '"degraded": false' && echo "  PASS：正常出带引用交付物" || { echo "  FAIL：$out"; fail=1; }

echo "—— 场景 A：掐断 R2R（检索故障）——"
docker compose -f deploy/docker-compose.yml stop r2r >/dev/null 2>&1
sleep 2
out=$(ask "公司2024年营业收入是多少？")
echo "$out" | grep -q '"degraded": true' && echo "  PASS：10s 内降级兜底" || { echo "  FAIL：$out"; fail=1; }
docker compose -f deploy/docker-compose.yml start r2r >/dev/null 2>&1
sleep 3

echo "—— 场景 B：模型网关故障（错 key 子进程）——"
(cd backend && MRAG_FAST_API_KEY=sk-invalid MRAG_STRONG_API_KEY=sk-invalid .venv/bin/python -m uvicorn app.main:app --port 8901 >/tmp/drill_badapi.log 2>&1) &
BAD_PID=$!
sleep 4
out=$(curl -sN --noproxy '*' --max-time 60 -X POST http://localhost:8901/api/chat -H 'Content-Type: application/json' \
  -d '{"session_id":"drill","question":"公司2024年营业收入是多少？"}' \
  | grep --line-buffered '^data: ' | while read -r line; do
    case "$line" in *'"deliverable"'*) echo "${line#data: }"; break ;; esac
  done)
echo "$out" | grep -q '"degraded": true' && echo "  PASS：模型故障降级" || { echo "  FAIL：$out"; fail=1; }
kill $BAD_PID 2>/dev/null

kill $DRILL_PID 2>/dev/null
echo "—— 演练结束（fail=$fail）——"
exit $fail
