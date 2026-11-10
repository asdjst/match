# multi-agent-rag（多智能体 RAG 参赛系统）

请求 → 五角色图（planner→retriever→executor→analyst→critic→writer）→ 带引用交付物 → SSE。设计见 [../工程架构设计.md](../工程架构设计.md)，排期见 [../开发计划.md](../开发计划.md)，指标看板见 [docs/metrics.md](docs/metrics.md)。

## 快速开始

```bash
./deploy/up.sh            # 一键：R2R 栈 + 建库 + API（live）
./deploy/up.sh --offline  # 断网演示包：fake 模式全离线（假 LLM/检索/工具）
```

手动：

```bash
cd backend
uv venv --python 3.12 .venv && . .venv/bin/activate
uv pip install -r requirements.txt
pytest                 # 单测 + 集成（全离线，124 条）
uvicorn app.main:app   # 起服务后：
curl -N -X POST localhost:8000/api/chat -H 'content-type: application/json' \
  -d '{"question":"A公司2024年营业收入是多少？"}'
```

## 运行模式（MRAG_MODE）

| 模式 | LLM | 检索 | 工具 | 用途 |
|---|---|---|---|---|
| fake（默认） | FakeLLM（确定性脚本） | FakeRetriever（内置演示语料） | FakeTools | 单测 / 断网演示包 |
| live | LiteLLM 双档路由（opencode 网关） | R2R（r2r_client） | MCP stdio Server + 治理层 | 联调 / 评测 / 演示 |

live 模式 key 在 `backend/.env`（gitignored）：`MRAG_FAST_*` / `MRAG_STRONG_*` / `MRAG_R2R_*`。

## API

| 端点 | 说明 |
|---|---|
| `POST /api/chat` | SSE：`run → (guard) → node* → deliverable → done`；注入被拦走 guard 短路 |
| `POST /api/chat` 触发断点时 | 打回轮数用尽 → `needs_human` 事件后收流，任务挂起 |
| `GET /api/tasks/{run_id}` | 回放节点轨迹 / 交付物 / `pending_human` |
| `POST /api/tasks/{run_id}/approve` | 人工放行断点 → 返回兜底交付物（degraded） |

## 评测与演练

```bash
cd backend
.venv/bin/python eval/run_metrics.py          # 检索指标：Recall@5 / MRR（全量 50，不花 LLM）
.venv/bin/python eval/run_metrics.py --n 20   # + 管线指标（引用准确率/无源断言率/拒答）+ 消融（直连 vs RAG）
.venv/bin/python eval/run_guard_eval.py       # 注入拦截率 / 误拦率（50 条样本库）
.venv/bin/python eval/golden.py               # 重新生成金标 50（人工只需复核 human_review 列）
../deploy/drill_degrade.sh                    # 降级演练：掐 R2R / 错模型 key → 10s 内 degraded 兜底
```

## 约定

- core/ 零轮子依赖；adapters/ 只把轮子翻译成 ports；装配只在 `app/main.py`。
- 所有 R2R 调用只允许出现在 `adapters/retrieval/r2r_client.py`；镜像版本在 deploy compose pin 死。
- 工具治理（审计 JSONL/超时/参数校验）在 `adapters/tools/governance.py`，MCP 会话在 `adapters/tools/mcp_client.py`。
- 全节点轨迹：每次会话一条 Langfuse trace，节点事件 `node:<name>`；打回/断点/降级均有事件。
- 单文件 ≤300 行。
