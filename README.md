# Glucoguard · 控糖饮食多智能体

慢性病（2 型糖尿病）饮食助手：**拍一张餐盘照片 → 识别食物与份量 → 算碳水/升糖负荷 → 检索指南与权威资料 → 安全护栏 → 输出逐句带引用的饮食建议**。所有结论都能点回证据（本地指南摘编 / 联网页面 / 食物数据库），检索与工具调用全程可在轨迹页回放。

> 定位是饮食与生活方式参考，不是医疗器械：不做诊断、不给胰岛素或降糖药剂量建议。演示用食物数据为公开食物成分表整理，联网搜索结果取决于当时页面内容。

## 能力

| 通道 | 实现 |
|---|---|
| 拍照识餐 | 上传图片 → VLM 返回食物名/份量/置信度 → 逐项可修正；图片落盘后可按 `image_id` 回放 |
| 语音输入 | 浏览器 Web Speech API（`zh-CN`）把口述转成问题，识别结果直接追加到输入框；不支持或没授权时只提示，不影响打字 |
| 本地知识库 | R2R 检索 8 篇指南摘编（食养指南 2023、T2DM 防治指南 2020、医学营养治疗 2022 等），按 H2 切段 |
| 联网检索 | 博查 / Tavily / DDGS 三选一，官方与学会域名加权，结果短时缓存 + 失败冷却，避免反复重试拖慢回答 |
| 餐食工具 | MCP 工具算碳水、升糖负荷（GL）、餐盘结构；调用流水进审计 |
| 编排 | LangGraph 六角色：planner → retriever → (executor｜analyst) → analyst → critic → critic→analyst｜retriever｜writer；分析员最多 7 条断言、按“当前餐→怎么改→长期”排序，审校只拦硬错误，打回意见回传到下一轮分析员，轮数用尽时在 Writer 前挂起等人工放行 |
| 个人餐食记忆 | 拍照后或“我吃了…”时弹出记录框，存食物/份量/时间/备注/餐前餐后血糖；提问含食物名、“上次/之前”或“今天/昨天吃了什么”时，这些记录作为 `memory` 通道证据入池，和指南、联网结果一起被引用 |
| 健康档案 | 身高/体重/年龄/活动量/目标 → 后端算 BMI → 作为份量与活动建议上下文，不进证据池；下方是餐食记录、血糖，以及近 7 天碳水柱状图、最近 14 天血糖折线 |
| 回答图表 | 问题涉及个人记录时，回答下方按问题自动附「血糖走势 / 每日碳水 / 今天各餐碳水」自绘 SVG；只画已记录数据，不补点、不预测 |
| 可观测 | SSE 实时节点事件、每节点耗时、持久化任务快照、轨迹页 DAG 回放；历史提问与运行轨迹同页可回放 |

## 快速开始

前置：Docker（R2R 栈）、Python 3.12+、Node 20+。

```bash
# 1. 本地知识库（R2R + PG + embeddings，:7272）
docker compose -f deploy/docker-compose.yml up -d

# 2. 后端配置：模型 key 填在 backend/.env（模板见 backend/.env.example）
cd backend
cp .env.example .env            # 填 MRAG_FAST_* / MRAG_STRONG_*
.venv/bin/python scripts/seed_r2r.py
.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000

# 3. 前端（:5173，代理到 :8000）
cd ../frontend
npm install
npm run dev
```

`./deploy/up.sh` 会把第 1、2 步串起来；`./deploy/up.sh --offline` 用 fake 模式全离线跑通界面与测试。

冒烟：

```bash
curl -s localhost:8000/api/health
curl -N -X POST localhost:8000/api/chat -H 'content-type: application/json' \
  -d '{"question":"今天血糖 12.8，晚饭还能吃米饭吗？"}'
```

## 运行模式（MRAG_MODE）

| 模式 | LLM | 检索 | 工具 | 用途 |
|---|---|---|---|---|
| fake（默认） | FakeLLM（确定性脚本） | FakeRetriever | FakeTools | 单测 / 断网演示 |
| live | LiteLLM 双档路由 | R2R + 可选联网 | MCP stdio Server + 治理层 | 联调 / 演示 |

模型按档位分工：`fast` 跑规划、结构化抽取与置信度评分，`strong` 跑分析与写作。延迟优先时保留 `deepseek-flash` 并用 `MRAG_FAST_EXTRA_BODY={"thinking":{"type":"disabled"}}` 关掉思考模式（实测与换 `deepseek-chat` 同耗时，但不用换模型）；需要更强推理时再给 strong 单独开思考。

## 配置

后端只读 `backend/.env`（`MRAG_` 前缀，[config.py](backend/infra/config.py)）；`deploy/.env` 仅给 compose 使用。**密钥不要提交**。

| 变量 | 必填 | 说明 |
|---|---|---|
| `MRAG_FAST_MODEL` / `_BASE_URL` / `_API_KEY` | live 必须 | 快档模型（规划/抽取/评分） |
| `MRAG_STRONG_MODEL` / `_BASE_URL` / `_API_KEY` | live 必须 | 强档模型（分析/写作） |
| `MRAG_FAST_EXTRA_BODY` / `MRAG_STRONG_EXTRA_BODY` | 可选 | 透传请求体；快档默认 `{"thinking":{"type":"disabled"}}` |
| `MRAG_R2R_BASE_URL` / `_COLLECTION` | live 必须 | 默认 `http://localhost:7272` / `demo` |
| `MRAG_RETRIEVAL_TIMEOUT_S` | 可选 | 单次检索超时，默认 8s |
| `MRAG_WEB_SEARCH` / `_TOP_K` | 可选 | 联网开关与条数，默认开 / 3 |
| `MRAG_WEB_PROVIDER` | 可选 | `bocha`（博查，国内，有免费额度）｜`tavily`（1000 次/月免费）｜`ddgs`（免 key，易限流） |
| `MRAG_WEB_API_KEY` | 选 provider 时必填 | 博查或 Tavily 的 key；缺失自动回退 DDGS |
| `MRAG_WEB_SEARCH_TIMEOUT_S` | 可选 | 联网单次超时，默认 3s |
| `MRAG_WEB_SEARCH_PROXY` | 可选 | 出网代理，如 `http://127.0.0.1:7890` |
| `MRAG_CORS_ORIGINS` | 可选 | 逗号分隔，默认本地 5173 |
| `MRAG_UPLOAD_DIR` / `MRAG_DB_PATH` | 可选 | 餐图与运行快照目录，默认 `backend/data/` |
| `MRAG_GDRIVE_*` | 可选 | 云端网盘通道，当前未配置即自动关闭 |

百度千帆本身是大模型平台（送 ERNIE 免费调用额度），不提供独立的可引用搜索接口；要换搜索源用博查或 Tavily。

## API

| 端点 | 说明 |
|---|---|
| `GET /api/health` | 存活、模式、是否联网、当前搜索源 |
| `POST /api/chat` | SSE：`run → (guard) → node* → deliverable → done`；体可带 `profile` 与 `session_id` |
| `POST /api/food/analyze` | 上传餐图，返回食物项、份量、置信度与 `image_id` |
| `GET /api/food/images/{image_id}` | 回放已存餐图（32 位十六进制 ID） |
| `GET /api/tasks/{run_id}` | 任务快照：节点轨迹、证据、交付物、耗时、`pending_human` |
| `POST /api/tasks/{run_id}/approve` | 人工放行断点 → 返回兜底交付物（degraded） |
| `GET/POST /api/meals` | 个人餐食记录列表 / 新建（食物、份量、碳水、GL、备注） |
| `GET/PATCH/DELETE /api/meals/{meal_id}` | 单条记录读取、修改、删除 |
| `POST/DELETE /api/meals/{meal_id}/glucose` | 追加 / 删除血糖读数（`minutes_after` 0 表示餐前，默认 120；可为接入 CGM 预留） |

`POST /api/chat` 可带 `user_id`（默认 `local`），后端按问题里的食物名与“上次/之前”等线索，从这个用户的历史餐食里挑记录并入证据池。

## 测试与评测

```bash
cd backend
.venv/bin/python -m pytest -q            # 单测 + 集成，全离线，225 条
.venv/bin/python eval/run_metrics.py     # Recall@5 / MRR（不花 LLM）
.venv/bin/python eval/run_guard_eval.py  # 注入拦截率 / 误拦率
../deploy/drill_degrade.sh               # 掐 R2R / 错 key → degraded 兜底
```

## 目录

```
backend/
  adapters/    LLM 路由、R2R/联网检索、VLM、MCP 工具、护栏
  core/        领域模型、LangGraph 图与节点、置信度、注入清洗、存储
  app/         FastAPI 入口与 API
  demo_assets/ 指南摘编与演示物料
frontend/      React 19 + Astryx 工作台（工作台 / 健康档案 / 合规审计）
deploy/        R2R compose 与降级演练脚本
```

## 约定

- `core/` 不依赖第三方轮子，`adapters/` 只做协议翻译，装配集中在 `app/main.py`。
- 所有 R2R 调用只在 `adapters/retrieval/r2r_client.py`；镜像版本在 compose 里 pin 死。
- 工具治理（审计 JSONL / 超时 / 参数校验）在 `adapters/tools/governance.py`。
- 检索证据进 prompt 前经 `core/services/injection.py` 中和指令型片段，引用卡片仍展示原文。
- 测试一律用临时库，不写演示数据库。
