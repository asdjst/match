# Glucoguard · 控糖饮食多智能体

慢性病（2 型糖尿病）饮食助手：**拍一张餐盘照片 → 识别食物与份量 → 算碳水/升糖负荷 → 检索指南与权威资料 → 安全护栏 → 输出连贯成文、逐句带引用的饮食建议**。所有结论都能点回证据（本地指南摘编 / 联网页面 / 食物数据库），检索与工具调用全程可在执行过程卡片回放。

> 定位是饮食与生活方式参考，不是医疗器械：不做诊断、不给胰岛素或降糖药剂量建议，也不回答控糖饮食以外的问题（物理推导、翻译、天气、代码等即使联网搜到了资料也拒答）。食物碳水取自《中国食物成分表》（逐项出处写在 `backend/data/food_nutrition.json` 的 `source` 里），GI 取自公开 GI 表；查不到权威 GI 的食物只报碳水、不估算 GL。联网搜索结果取决于当时页面内容。

## 团队

| 项目 | 信息 |
|---|---|
| 团队名称 | Milkbabby |
| 团队编号 | 45545 |
| 所属院校 | 西安交通大学 |
| 参赛组别 | 研究生组 |
| 团队人数 | 3 人 |
| 指导老师 | 刘帅 |

## 能力

| 通道 | 实现 |
|---|---|
| 拍照识餐 | 上传图片 → VLM 返回食物名/份量/置信度 → 逐项可修正；图片落盘后可按 `image_id` 回放 |
| 语音输入 | 浏览器 Web Speech API（`zh-CN`）把口述转成问题，识别结果直接追加到输入框；不支持或没授权时只提示，不影响打字 |
| 本地知识库 | R2R 检索 8 篇指南摘编（食养指南 2023、T2DM 防治指南 2020、医学营养治疗 2022 等），按 H2 切段 |
| 联网检索 | 博查 / Tavily / DDGS 三选一，官方与学会域名加权，结果短时缓存 + 失败冷却，避免反复重试拖慢回答 |
| 餐食工具 | MCP 10 个工具：食物成分、单项 GL、整餐 GL 合计、个人血糖统计（均值/SD/CV/LAGE/区间读数占比）、每日碳水目标与三餐分配，外加通用增减/求和/均值；入参由后端从餐食、档案、读数里取，模型不填数；调用流水进审计 |
| 食物库 | 54 项常见食物（主食/蔬果/肉蛋水产/豆制品/水果/坚果），碳水查中国营养学会《中国食物成分表》官方平台并在 `source` 里标条目 id 与生熟重；认别名（冰激凌/雪糕 → 冰淇淋）；GI 未收录的只报碳水不猜 GL，库外食物标「未收录」并说明合计不代表整餐真实值 |
| 编排 | LangGraph 六角色：planner → retriever → (executor｜analyst) → analyst → critic → critic→planner｜retriever｜analyst｜writer；分析员最多 7 条断言、按“当前餐→怎么改→长期”排序，审校只拦硬错误，打回意见回传到下一轮分析员，轮数用尽时在 Writer 前挂起等人工放行 |
| 成文回答 | writer 里的成文智能体把审校通过的断言连成 2–4 段口语化回答：引用编号一个不多一个不少、硬数字与区间照抄、长度受约束，任一项不过或模型调用失败就退回逐条断言，原因写进执行轨迹；前端正文里的 `[E#]` 可点开证据，「逐条依据」展开逐条核对 |
| 个人餐食记忆 | 拍照后或“我吃了…”时弹出记录框，存食物/份量/时间/备注/餐前餐后血糖；只写名字和克数时按食物库折算碳水与 GL 并标「估算」，用户自填的不覆盖，库外食物留空；记录可随时编辑（改克数会重算）或删除；提问含食物名、“上次/之前”或“今天/昨天吃了什么”时，这些记录作为 `memory` 通道证据入池，和指南、联网结果一起被引用 |
| 健康档案 | 身高/体重/年龄/活动量/目标 → 后端算 BMI → 作为份量与活动建议上下文，不进证据池；下方是餐食记录、血糖，以及近 7 天碳水柱状图、最近 14 天血糖折线 |
| 回答图表 | 问题涉及个人记录时，回答下方按问题自动附「血糖走势 / 每日碳水 / 今天各餐碳水」自绘 SVG；只画已记录数据，不补点、不预测 |
| 可观测 | SSE 实时节点事件、每节点耗时与文字反馈、持久化任务快照、执行过程卡片回放；历史提问与运行轨迹同页可回放 |
| 账号与多用户隔离 | 用户名 + 密码注册登录（scrypt 哈希、随机令牌），餐食/血糖/运行历史/会话记忆按 `user_id` 隔离，归属条件写在 SQL 里；不登录也能用，数据归单机演示身份 `local` |

## 快速开始

前置：Docker（R2R 栈）、Python 3.12+、Node 20+。

```bash
# 1. 本地知识库（R2R + PG + embeddings，:7272）
docker compose -f deploy/docker-compose.yml up -d

# 2. 后端配置：模型 key 填在 backend/.env（模板见 backend/.env.example）
cd backend
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env            # 填 MRAG_FAST_* / MRAG_STRONG_*
.venv/bin/python scripts/seed_r2r.py
.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000

# 3. 前端（:5173，代理到 :8000）
cd ../frontend
npm install
npm run dev
```

`./deploy/up.sh` 会把第 1、2 步串起来；`./deploy/up.sh --offline` 用 fake 模式全离线跑通界面与测试。后端未启动时前端会显式提示“后端未连接”并禁用提问，不会拿内置数据冒充回答；顶栏无账号入口，左下角有一个账号小图标：点开即可登录或注册，登录后点开可退出；登录令牌过期时图标上带提示点，界面上会提示“登录已过期”并给「重新登录」，不登录则以单机演示身份继续用。后端在跑但餐食记录接口失败时，档案卡与输入框下方会提示“餐食记录没读到”并给「重试」，同时不画统计图——读不到不等于没有记录，不会谎报空档案。

冒烟：

```bash
curl -s localhost:8000/api/health
curl -N -X POST localhost:8000/api/chat -H 'content-type: application/json' \
  -d '{"question":"一碗米饭大概多少碳水？"}'
```

fake 模式的检索是中文二元组关键词匹配（不是向量语义检索），长句问法可能召不到段落；离线演示用上面这种短问法。

## 运行模式（MRAG_MODE）

| 模式 | LLM | 检索 | 工具 | 用途 |
|---|---|---|---|---|
| fake（默认） | FakeLLM（确定性脚本） | FakeRetriever | FakeTools | 单测 / 断网演示 |
| live | LiteLLM 双档路由 | R2R + 可选联网 | MCP stdio Server + 治理层 | 联调 / 演示 |

fake 的检索语料直接读 `demo_assets/gluco_knowledge` 的同一批知识卡，所以离线与在线命中的是同一份原文，不另维护一份假数据；工具算法两边共用 `adapters/tools/health_tools.py` 与同一份食物成分表。

模型按档位分工：`fast` 跑规划、结构化抽取、成文与置信度评分，`strong` 跑分析。延迟优先时保留 `deepseek-flash` 并用 `MRAG_FAST_EXTRA_BODY={"thinking":{"type":"disabled"}}` 关掉思考模式（实测与换 `deepseek-chat` 同耗时，但不用换模型）；需要更强推理时再给 strong 单独开思考。

## 配置

后端只读 `backend/.env`（`MRAG_` 前缀，[config.py](backend/infra/config.py)）；`deploy/.env` 仅给 compose 使用。**密钥不要提交**。

| 变量 | 必填 | 说明 |
|---|---|---|
| `MRAG_FAST_MODEL` / `_BASE_URL` / `_API_KEY` | live 必须 | 快档模型（规划/抽取/成文/评分） |
| `MRAG_STRONG_MODEL` / `_BASE_URL` / `_API_KEY` | live 必须 | 强档模型（分析） |
| `MRAG_FAST_EXTRA_BODY` / `MRAG_STRONG_EXTRA_BODY` | 可选 | 透传请求体；快档默认 `{"thinking":{"type":"disabled"}}` |
| `MRAG_R2R_BASE_URL` / `_COLLECTION` | live 必须 | 默认 `http://localhost:7272` / `gluco` |
| `MRAG_RETRIEVER_TOP_K` | 可选 | 单通道召回条数，默认 8 |
| `MRAG_RETRIEVAL_TIMEOUT_S` | 可选 | 单次检索超时，默认 8s |
| `MRAG_REFUSAL_THRESHOLD` | 可选 | 交付置信度阈值，低于即拒答式兜底，默认 0.45 |
| `MRAG_WEB_SEARCH` / `_TOP_K` | 可选 | 联网开关与条数，默认开 / 3 |
| `MRAG_WEB_PROVIDER` | 可选 | `bocha`（博查，国内，有免费额度）｜`tavily`（1000 次/月免费）｜`ddgs`（免 key，易限流） |
| `MRAG_WEB_API_KEY` | 选 provider 时必填 | 博查或 Tavily 的 key；缺失自动回退 DDGS |
| `MRAG_WEB_SEARCH_TIMEOUT_S` | 可选 | 联网单次超时，默认 3s |
| `MRAG_WEB_SEARCH_PROXY` | 可选 | 出网代理，如 `http://127.0.0.1:7890` |
| `MRAG_CORS_ORIGINS` | 可选 | 逗号分隔，默认本地 5173 |
| `MRAG_UPLOAD_DIR` / `MRAG_DB_PATH` | 可选 | 餐图、运行快照与账号库目录，默认 `backend/data/`（账号与会话同在 `runs.db`） |
| `MRAG_TOOL_AUDIT_PATH` | 可选 | MCP 调用审计 JSONL，默认 `backend/logs/tool_audit.jsonl` |
| `MRAG_TOOL_TIMEOUT_S` | 可选 | 单次工具调用超时，默认 10s，超时返回 `ok:false` 不炸图 |
| `MRAG_GDRIVE_*` | 可选 | 云端网盘通道，当前未配置即自动关闭 |

百度千帆本身是大模型平台（送 ERNIE 免费调用额度），不提供独立的可引用搜索接口；要换搜索源用博查或 Tavily。

## API

| 端点 | 说明 |
|---|---|
| `GET /api/health` | 存活、模式、是否联网、当前搜索源、身份方式（`auth: "accounts"`）；不校验令牌 |
| `POST /api/auth/register` | 注册（用户名 3–24 位中英文/数字/`_`/`-`，密码 8–128 位）→ 201 返回令牌与用户；重名 409，不合规 400 |
| `POST /api/auth/login` | 登录 → 令牌与用户；用户名或密码错都回同一句 401，同一用户名连错 5 次冷却 300s（429） |
| `POST /api/auth/logout` | 吊销当前令牌（其他设备的登录不受影响） |
| `GET /api/auth/me` | 当前身份：`{user, guest, expired}`；令牌失效也回 200，前端据此静默清令牌 |
| `POST /api/chat` | SSE：`run → (guard) → node* → deliverable → done`；体可带 `profile` 与 `session_id` |
| `POST /api/food/analyze` | 上传餐图，返回食物项、份量、置信度与 `image_id` |
| `GET /api/food/images/{image_id}` | 回放已存餐图（32 位十六进制 ID） |
| `GET /api/tasks/{run_id}` | 任务快照：节点轨迹、证据、交付物、耗时、`pending_human` |
| `GET /api/runs?limit=N` | 历史运行列表（前端会话历史与断连探测都用它） |
| `POST /api/tasks/{run_id}/approve` | 人工放行断点 → 返回兜底交付物（degraded） |
| `GET/POST /api/meals` | 个人餐食记录列表 / 新建（食物、份量、碳水、GL、备注）；碳水留空时按食物库折算并标 `estimated` |
| `GET/PATCH/DELETE /api/meals/{meal_id}` | 单条记录读取、修改、删除 |
| `POST /api/meals/{meal_id}/glucose` | 追加血糖读数（`minutes_after` 0 表示餐前，默认 120；可为接入 CGM 预留） |
| `DELETE /api/meals/{meal_id}/glucose/{reading_id}` | 删除某条血糖读数 |

### 账号与多用户隔离

注册登录开箱可用，不需要配置。**没带令牌就是单机演示身份 `local`**（断网演示、单测、脚本都走这条路）；带上 `Authorization: Bearer <登录令牌>` 后数据按 `user_id` 隔离，令牌无效或过期返回 401。

```bash
# 注册即登录，令牌只在响应里出现一次
curl -s -X POST localhost:8000/api/auth/register \
  -H 'content-type: application/json' \
  -d '{"username":"demo_alice","password":"控糖日记2026"}'

curl -s localhost:8000/api/meals -H 'authorization: Bearer <上一步返回的 token>'
```

- **密码与令牌都不落明文**：密码存 `scrypt$16384$8$1$盐$派生值`（[accounts.py](backend/core/services/accounts.py)，标准库 `hashlib.scrypt` + 16 字节随机盐，`hmac.compare_digest` 比对）；令牌是 `secrets.token_urlsafe(32)`，库里只存 SHA-256，有效期 30 天，退出即删。用户名不存在时也跑一次哈希，避免用响应时间枚举账号。
- **令牌即身份**：用户由 [deps.py](backend/app/api/deps.py) 解析，请求体里的 `user_id` 一律忽略，归属条件写进 SQL（`WHERE … AND user_id=?`），跨用户读/改/删都当作不存在。
- 隔离范围：餐食记录、血糖读数、运行快照与历史列表、人工放行断点、会话记忆（键为 `用户:session_id`）、以及问答时从个人记录里挑证据的范围。同一个 `session_id` 在不同用户下互不可见。
- 前端账号入口是侧栏左下角的一个图标（登录 / 注册 / 退出都在这里），没有单独的“接口访问”面板；令牌只存浏览器 `localStorage`，换账号会清掉内存里上一个人的问答与图表再重连。登录失败的 401 只提示“用户名或密码不正确”，不会当成会话过期把人踢出去。
- 餐图按能力 URL 处理：`image_id` 是 128 位随机值，只经归属校验后的接口下发，`<img>` 带不了令牌，所以回放端点不校验。
- 旧库自动迁移：`runs` 表补 `user_id` 列（历史数据归 `local`）并建索引，`users` / `sessions` 表首次启动自建，不需要手工改库。
- 登录失败限流是进程内计数（重启清零），除此之外还没有请求级限流与配额。隔离与账号行为由 `tests/integration/test_auth_isolation.py`、`tests/unit/test_accounts.py` 覆盖。

后端按问题里的食物名与“上次/之前”等线索，从当前用户的历史餐食里挑记录并入 `memory` 证据通道；档案为空时给一条“还没有任何餐食记录”的证据，而不是让整轮变成无引用拒答。由食物库折算的碳水在证据原文里带“食物库估算”标记，不冒充用户实测值；分析员拿个人记录给这顿的具体动作（份量减到多少克、换成什么、餐后多久复测做对照），但不把单次记录说成因果结论，也不给用药或剂量建议。

## 测试与评测

```bash
cd backend
.venv/bin/python -m pytest -q            # 单测 + 集成，全离线，384 条
.venv/bin/python eval/golden.py          # 由知识卡标题重建金标 50 条（定位自动校验）
.venv/bin/python eval/run_metrics.py     # Recall@5 / MRR（不花 LLM）
.venv/bin/python eval/run_metrics.py --n 20  # + 关键来源命中 / 引用可解析 / 无源断言 / 成文率 / 库外拒答 / 直连大模型消融
.venv/bin/python eval/run_guard_eval.py  # 注入拦截率 / 误拦率
../deploy/drill_degrade.sh               # 掐 R2R / 错 key → degraded 兜底
```

金标 50 条 = 事实 30 + 对比 6 + 计算 8 + 库外负例 6，全部定位到 `demo_assets/gluco_knowledge` 的真实小标题；计算题在 CSV 的 `context` 列带个人血糖读数或代谢档案，工具入参由这里注入而不是让模型填数。拍照与语音通道由集成测试覆盖（需要真实上传），不进金标检索指标。

最近一次实测（384 测试全过、Recall@5 0.9737、关键来源命中 1.00、成文率 1.00、库外拒答 3/3、直连 0.725 vs RAG 1.00）与各项口径见 [docs/metrics.md](docs/metrics.md)，结果文件在 `backend/eval/results/`。

## 目录

```
backend/
  adapters/    LLM 路由、R2R/联网检索、VLM、MCP 工具、护栏
  core/        领域模型、LangGraph 图与节点、置信度、注入清洗、存储与账号
  app/         FastAPI 入口与 API（注册登录在 app/api/auth.py，身份解析在 app/api/deps.py）
  eval/        金标 50 条、指标与护栏评测脚本、结果 JSON
  demo_assets/ 8 篇控糖指南摘编（入库与离线检索共用同一批原文）
frontend/      React 19 + Astryx 工作台（控糖工作台 / 健康档案卡片 / 执行过程卡片）
deploy/        R2R compose 与降级演练脚本
docs/          指标与实测（metrics.md）
```

## 约定

- `core/` 不依赖第三方轮子，`adapters/` 只做协议翻译，装配集中在 `app/main.py`。
- 所有 R2R 调用只在 `adapters/retrieval/r2r_client.py`；镜像版本在 compose 里 pin 死。
- 工具治理（审计 JSONL / 超时 / 参数校验）在 `adapters/tools/governance.py`。
- 检索证据进 prompt 前经 `core/services/injection.py` 中和指令型片段，引用卡片仍展示原文。
- 测试一律用临时库，不写演示数据库。
