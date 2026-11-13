# Glucoguard 项目总览 + 技术文档整理 Brief

> 用途一：把本文件直接交给其他 AI，让它**只凭本文就完全了解本项目**，进而把 `docs/tech-report.md` 初稿组织成最终提交用的《技术文档》PDF。
> 用途二：本文件本身就是一份不依赖代码的项目说明（产品、架构、模块、流程、指标、部署俱全）。
> 本文件是工作母稿，不需要提交给赛事。

---

## 第一部分 · 只凭本文了解整个项目

### 1. 项目是什么

**Glucoguard（慢病控糖膳食助手）**是一个面向 2 型糖尿病等慢病控糖人群的 **AI Native 饮食助手**。用户拍一张餐盘照片，系统识别食物与份量、折算碳水化合物与升糖负荷（GL），再检索权威控糖指南与联网资料，经过安全护栏，输出**连贯成文、逐句带引用编号 `[E#]`** 的饮食建议——每一句结论都可以点击证据编号，在右侧面板里回看证据原文（本地指南摘编 / 联网页面 / 食物数据库 / 个人餐食记录），检索与工具调用全程可在「执行过程」卡片中回放。

一句话能力：**拍照识餐、语音提问、多智能体检索问答、证据可回放、健康档案与趋势报告、饮食日记本、账号体系与多用户数据隔离。**

合规边界（产品硬约束）：定位为「饮食与生活方式参考」，**不是医疗器械**——不做诊断、不给胰岛素/降糖药剂量建议，也不回答控糖饮食以外的问题（物理推导、翻译、天气、代码等，即使联网搜到也拒答）。

### 2. 团队信息（固定写法，出现在封面/概述）

团队名称 **Milkbabby**，团队编号 **45545**，西安交通大学，**研究生组**，成功组队 **3 人**，指导老师 **刘帅**。

### 3. 技术栈总览

| 层 | 技术 | 端口/说明 |
|---|---|---|
| 前端 | React 19 + TypeScript（strict）+ Vite + Astryx 设计系统（主题 token，深浅色自动跟随）；霞鹜文楷 webfont 用于日记手写体 | dev :5173，代理到后端 :8000 |
| 后端 | Python 3.12 + FastAPI + LangGraph（多智能体图）+ LiteLLM（双档模型路由）+ SQLite 业务库 | uvicorn :8000 |
| 检索栈 | docker compose：PostgreSQL 16 + pgvector、infinity（本地中文 embedding，模型 BAAI/bge-small-zh-v1.5）、R2R 3.6.6（镜像 pin） | r2r 宿主机 :7272（容器内 8000），embeddings :7997 |
| 工具协议 | MCP（Model Context Protocol）stdio server，10 个控糖工具 + 治理层 | 子进程启动 |
| 部署 | `deploy/up.sh` 一键串联；`--offline` 全离线 fake 模式；`deploy/drill_degrade.sh` 降级演练 | — |

### 4. 后端架构（backend/）

分层约定：**`core/` 不依赖第三方轮子（纯领域层），`adapters/` 只做协议翻译，装配集中在 `app/main.py`。**

```
backend/
├── app/            FastAPI 入口与路由
│   ├── main.py     装配：guard / retriever / llm / tools / stores，挂路由与 CORS
│   ├── deps.py     令牌即身份的解析（请求体里的 user_id 一律忽略）
│   └── api/        auth.py 注册登录 / chat.py SSE 问答 / food.py 餐图 / meals.py 餐食血糖 / tasks.py 任务快照与放行
├── core/           领域层
│   ├── graph/      LangGraph：builder.py（图与条件边）、state.py（GraphState）、events.py（SSE 事件）、nodes/（roles.py 六角色实现、critic.py 审校）
│   ├── schemas/    agent/evidence/deliverable/food/guard/profile/prompt 等 Pydantic 模型
│   ├── services/   accounts（scrypt+令牌）、meals（餐食与血糖 CRUD）、memory（个人记录转 memory 证据）、
│   │               confidence（置信度双通道）、compose（成文智能体）、injection（引用注入中和）、
│   │               degrade（降级兜底）、store（SQLite 持久化）、citation（引用解析）、food（食物折算）
│   └── ports/      检索/工具等端口抽象
├── adapters/
│   ├── llm/        router.py（LiteLLM 双档 fast/strong 路由）、fake.py（FakeLLM 离线脚本）、structured.py（结构化输出，HistoryIntent 意图分类等）
│   ├── retrieval/  r2r_client.py（唯一 R2R 调用点）、web.py（博查/Tavily/DDGS 联网，缓存+冷却+域名加权）、gdrive.py（云盘通道，未配置自动关）、multi.py（多通道扇出+总超时）、fake.py、demo_corpus.py（离线读同一批知识卡）
│   ├── tools/      mcp_server.py（MCP stdio server，10 个工具）、mcp_client.py（作为 ToolGateway 挂进图）、governance.py（审计 JSONL/10s 超时/参数镜像校验）、health_tools.py（工具算法，fake 与 live 共用）、food_data.py、fake.py
│   ├── guard/      rule_guard.py（主题+注入护栏，规则确定性，单次 0.01ms）
│   ├── vision/     food.py（VLM 拍照识餐）
│   └── observability/  节点耗时、审计
├── infra/config.py 只读 backend/.env（MRAG_ 前缀）
├── data/           runs.db（users/sessions/runs/meal_logs/glucose_readings）、checkpoints.db（LangGraph checkpointer）、food_nutrition.json（54 项食物库）、uploads/（餐图）
├── demo_assets/gluco_knowledge/   8 篇控糖指南摘编（入库与离线检索共用同一批原文）
├── eval/           golden_50.csv 金标 50 条、run_metrics.py、run_guard_eval.py、results/*.json
├── scripts/seed_r2r.py             按 H2 切段入库（8 篇 37 段）
└── tests/          unit + integration，全离线，一律用临时库
```

### 5. 多智能体编排（核心 AI 架构）

LangGraph `StateGraph`，六个节点 + 条件边（`core/graph/builder.py`）：

```
planner → retriever ─┬─(需要工具)─→ executor ─┐
                     └─(直接分析)─────────────┴→ analyst → critic ─┬─ pass → writer → END
                                                                      └─ send_back → 回到 planner/retriever/analyst（打回重做）
                                                                      └─ 轮数用尽 → writer 前挂起 pending_human，等人工「一键放行」
```

- **planner**：把问题拆成子任务（TaskDAG），含轮数预算 `max_rounds`。
- **retriever**：多通道扇出（local R2R 混合检索向量+BM25+RRF+服务端精排 / web 联网 / cloud 云盘 / memory 个人记录），线程池 + 总超时，各通道独立超时互不拖垮；证据统一编号 `E1…En` 汇入证据池；引用进 prompt 前经 `injection.py` 中和指令型片段（引用卡片仍展示原文）。
- **executor**：调用 MCP 工具，**入参由后端从餐食/档案/读数中取，模型不填数**；超时返回 `ok:false` 不炸图。
- **analyst**：产出最多 7 条断言，按「当前餐→怎么改→长期」排序，每条必须带引用。
- **critic**：只拦硬错误（无源、越界、剂量建议等），打回意见回传下一轮 analyst。
- **writer**：先置信度评分（LLM 评分 + 确定性公式兜底，双通道标 `confidence_source`），低于阈值 0.45 拒答（「无源不答」）；再由**成文智能体**把审校通过的断言连成 2–4 段口语化回答，经过确定性校验（引用集合必须与断言完全相等、硬数字照抄、长度 0.5–1.5 倍），任一项不过或调用失败就退回逐条断言并把原因写进轨迹。

问答接口 `POST /api/chat` 走 **SSE**，事件流：`run → (guard) → node* → deliverable → done`，每个 node 事件带角色名、耗时 `elapsed_ms`、文字反馈；任务快照持久化到 SQLite，历史可回放。前端执行卡实时显示当前角色、六段进度条、已用/总耗时。

**个人记忆召回**（问「上一餐吃了什么」这类）：入口先用**正则 cue** 命中自然说法（上一餐/上一顿/上次/之前/那次/这顿/吃过/记得/记录等），未命中再用 **fast 档模型做结构化意图分类（HistoryIntent）**，失败回退纯规则；命中后从该用户餐食记录取最近若干条转成 `memory` 证据入池；空档案给「还没有任何餐食记录」的占位证据，避免整轮无引用拒答。

### 6. MCP 工具清单（10 个，`adapters/tools/mcp_server.py`）

| 工具 | 作用 |
|---|---|
| `query_food_nutrition(name)` | 食物成分查询（碳水/GL/出处，来自 54 项食物库） |
| `calculate_gl(name, carbs_g)` | 单项食物升糖负荷 |
| `meal_gl_total(foods)` | 整餐 GL 合计 |
| `glucose_summary(values, low=3.9, high=10.0)` | 个人血糖统计：均值/SD/CV/LAGE/区间读数占比（TIR） |
| `carb_target(...)` | 每日碳水目标与三餐分配（按档案 BMI/活动量算） |
| `growth_rate(a,b)` / `yoy_diff(a,b)` | 通用增减/差值 |
| `sum(values)` / `avg(values)` | 求和 / 均值 |
| `slow_sum(a,b,delay_s)` | 可注入延迟的加法（用于超时演练） |

治理层 `governance.py`：调用审计写 JSONL、单次超时 10s、入参按 schema 镜像校验。fake 模式的 FakeTools 与 live 共用同一套 `health_tools.py` 算法和同一份食物表。

### 7. 知识库与食物库

- **本地知识库**：8 篇权威指南摘编（成人糖尿病食养指南 2023 两篇、中国 2 型糖尿病防治指南 2020 的医学营养治疗与血糖控制目标、糖尿病医学营养治疗指南 2022 的 GI/GL、低血糖与监测、常见食物碳水速查、膳食纤维盐糖），共 **37 段**（按 H2 切段），经 `scripts/seed_r2r.py` 入 R2R；离线 fake 模式直接读同一批文件，不另维护假数据。
- **食物库** `data/food_nutrition.json`：**54 项**常见食物（主食/蔬果/肉蛋水产/豆制品/水果/坚果），其中 **29 项带逐项出处**——碳水取自中国营养学会《中国食物成分表》官方平台（`source` 记条目 id、生熟重、可食部），GI 取自公开 GI 表；别名（冰激凌/雪糕→冰淇淋）；GI 来源分歧过大（莲藕/花生/核桃、冰淇淋不同配方）的记 `null`，**只报碳水不估算 GL**；库外食物标「未收录」，合计不代表整餐真实值。
- 记餐只写名字+克数时，后端按食物库折算碳水/GL 并标 `estimated=true`（证据里带「食物库估算」），用户自填值不被覆盖；改克数会重算。

### 8. 前端架构（frontend/，约 6000 行 TSX）

- **页面**：`pages/ChatPage.tsx`（控糖工作台，851 行：会话列表、输入框+语音按钮、消息流、执行过程 HUD、证据面板、左下角健康档案 FAB、右侧日记图钉迷你卡）和 `pages/ProfilePage.tsx`（健康档案：基础信息+BMI、健康趋势；餐食记录已全部迁到日记本）。
- **组件**（15+）：`DeliverableView`（成文正文，`[E#]` 可点击 chip）、`EvidenceCard`（右侧证据面板：来源/通道徽标/行号段落定位/原文）、`AgentActivity`+`ThinkingTimeline`（执行 HUD 与轨迹回放）、`FlowDag`（任务 DAG 可视化）、`HealthFileCard`（浮动档案卡）、`HealthTrends`（954 行 AGP 风格趋势报告）、`MealCharts`（自绘 SVG 图表）、`MealCard`/`MealLogDialog`（餐食卡与记录弹窗）、`MealDiary`+`MealDiaryBook`（饮食日记本）、`AuthDialog`/`AccountEntry`（登录注册/账号入口）、`VoiceInputButton`（Web Speech API zh-CN 语音输入）、`ConversationList`、`BrandMark`。
- **状态管理**：三个 Context Store——`store/auth.tsx`（令牌，localStorage）、`store/runs.tsx`（SSE 流式状态机，520 行）、`store/ui.tsx`。网络层 `api/client.ts` + `api/transport.ts`（SSE 解析）。工具函数 `lib/glucoseStats.ts`、`lib/demoMeals.ts`。
- **设计系统**：Astryx 主题 token，深浅色自动跟随；图表全部自绘 SVG；**饮食日记本**是手账风格——右侧红图钉钉住的迷你卡（手写体预览），点击展开大日记本：螺旋装订+和纸胶带+横线纸+霞鹜文楷手写体，一页一天、可翻页、餐次为荧光笔高亮块、照片拍立得样式，日记内可直接记一顿/编辑/补血糖/删除（删除走红色 AlertDialog 二次确认，不用浏览器原生 confirm）。
- **健康趋势**（AGP 风格，明确按「读数占比」统计口径）：概览指标卡（平均血糖、达标占比 TIR、CV、极差）、读数分布、单日 24 小时曲线（目标区间阴影带）、按小时叠加、餐后时段、碳水×血糖散点、近 7 天每日碳水柱状、近 14 天血糖折线，支持范围切换与 CSV 导出；只画已记录数据，不补点不预测。回答涉及个人记录时，回答下方自动附「血糖走势/每日碳水/今天各餐碳水」图。
- 前端容错：后端未启动显式提示「后端未连接」并禁用提问；餐食接口失败提示「餐食记录没读到」+重试，不谎报空档案；登录过期提示「登录已过期」+重新登录。

### 9. 账号与多用户隔离

- 注册/登录开箱可用：用户名 3–24 位（中英文/数字/`_`/`-`），密码 8–128 位；**密码存 `scrypt$16384$8$1$盐$派生值`**（标准库 `hashlib.scrypt`+16 字节随机盐，`hmac.compare_digest` 比对，用户名不存在也跑一次哈希防时序枚举）；**令牌 `secrets.token_urlsafe(32)`，库里只存 SHA-256，30 天有效**；同一用户名连错 5 次冷却 300s（429）；退出吊销当前令牌。
- **令牌即身份**：`app/api/deps.py` 解析，请求体里 user_id 一律忽略；归属条件写进 SQL（`WHERE … AND user_id=?`），跨用户读改删当不存在。不登录归单机演示身份 `local`。
- 隔离范围：餐食、血糖、运行快照与历史、人工放行断点、会话记忆（键 `用户:session_id`）。旧库自动迁移（runs 补 user_id 列，历史归 local）。
- 餐图按 capability URL 处理：`image_id` 128 位随机，只经归属校验的接口下发，回放端点不校验（`<img>` 带不了令牌）。

### 10. API 一览

| 端点 | 说明 |
|---|---|
| `GET /api/health` | 存活、模式、是否联网、当前搜索源、身份方式 |
| `POST /api/auth/register` / `login` / `logout`，`GET /api/auth/me` | 注册（201+令牌）/ 登录（统一 401 防枚举）/ 吊销 / 当前身份 `{user,guest,expired}` |
| `POST /api/chat` | SSE：`run → guard → node* → deliverable → done`，可带 `profile` 与 `session_id` |
| `POST /api/food/analyze`，`GET /api/food/images/{image_id}` | 餐图识别（食物/份量/置信度/image_id，逐项可修正）与回放 |
| `GET /api/tasks/{run_id}`，`GET /api/runs?limit=N`，`POST /api/tasks/{run_id}/approve` | 任务快照（轨迹/证据/交付物/`pending_human`）、历史、人工放行 |
| `GET/POST /api/meals`，`GET/PATCH/DELETE /api/meals/{id}` | 餐食 CRUD，碳水留空按食物库折算并标 estimated |
| `POST /api/meals/{id}/glucose`，`DELETE …/glucose/{rid}` | 血糖读数（`minutes_after` 0=餐前，默认 120，为 CGM 预留） |

### 11. 运行模式与关键配置

`MRAG_MODE=fake|live`（默认 fake 全离线演示，live 走真实模型+R2R+联网+MCP）。模型双档：`MRAG_FAST_*`（deepseek-flash，默认 `MRAG_FAST_EXTRA_BODY={"thinking":{"type":"disabled"}}` 关思考模式）跑规划/结构化抽取/成文/置信度评分；`MRAG_STRONG_*`（deepseek-chat）跑分析。其余：`MRAG_R2R_BASE_URL`（默认 localhost:7272）、`MRAG_RETRIEVER_TOP_K=8`、`MRAG_RETRIEVAL_TIMEOUT_S=8`、`MRAG_REFUSAL_THRESHOLD=0.45`、`MRAG_WEB_SEARCH/ _PROVIDER(bocha|tavily|ddgs)/ _API_KEY/ _TIMEOUT_S=3`、`MRAG_TOOL_TIMEOUT_S=10`、`MRAG_UPLOAD_DIR`/`MRAG_DB_PATH`/`MRAG_TOOL_AUDIT_PATH`、`MRAG_CORS_ORIGINS`。**密钥只走 `backend/.env`（模板 `.env.example`），不入库**。另设 `LITELLM_LOCAL_MODEL_COST_MAP=True` 避免断网时 litellm 拉价目表卡住首题。

### 12. 测试与实测指标（全部本机可复现，命令见 docs/metrics.md）

| 指标 | 实测 | 备注 |
|---|---|---|
| 后端测试 | **389 passed**（全离线 pytest；metrics.md 页记录的 384 为上一批次，提交前请重跑并同步） | tests/unit + tests/integration，临时库 |
| Recall@5 / MRR | **0.9737 / 0.9257** | 金标 50 条（事实 30+对比 6+计算 8+库外 6），口径 n=38（去掉库外 6 + 纯工具题 6） |
| 关键来源命中 / 引用可解析 | **1.00 / 1.00** | 管线子集 n=23 |
| 无源断言率 / 成文率 / 答案分（LLM-as-judge） | **0.00 / 1.00 / 1.00** | 严格精确率 0.4412 属口径偏低，勿当质量指标 |
| 护栏 | 注入拦截 **39/39（100%）**、良性误拦 **0/11**、单次 0.01ms | rule_guard 规则确定性 |
| 降级演练 | **3/3**（掐 R2R / 错 key / 工具超时 → degraded 兜底） | drill_degrade.sh + test_degrade.py |
| 库外拒答 | 3/3 | 不编答案 |
| 消融 | 直连大模型 **0.725** vs 六角色 RAG **1.00**（六次重跑直连 0.525–0.725，RAG 五次 1.00 一次 0.975） | 同题同模型同裁判，RAG 多花约 16s |
| 端到端延迟 | 金标 20 题 11.9–48.1s，均值 18.3s；单题 14.8–32.5s，writer 稳定 5.8–6.3s（成文代价约 +4s），波动来自网关 | 节点耗时取自 SSE elapsed_ms |
| 检索通道耗时 | local(R2R) 50–70ms / web 成功 2.3s·失败 4s 硬截止 / cloud 未配置 0ms 自动关 / memory <5ms | — |

### 13. 部署

`docker compose -f deploy/docker-compose.yml up -d` 起 postgres(pgvector:pg16) + infinity(bge-small-zh-v1.5, :7997) + R2R 3.6.6（宿主机 :7272，镜像版本写在 deploy/.env 的 R2R_IMAGE 并 pin 住）；后端 `uvicorn app.main:app --port 8000`；前端 `npm install && npm run dev`（:5173 代理 :8000）或 build 后静态托管。`./deploy/up.sh` 串起检索栈+后端，`--offline` 全离线 fake 模式。在线演示可选方案：云厂商学生机按月部署（评审结束即释放）或内网穿透临时地址，并提供评审专用测试账号。

### 14. 创新点（技术创新 / 应用创新，两节分开列）

技术创新：①证据可回放的引用体系（`[E#]` 点开原文面板，引用可解析率 1.00，注入中和与原文分离展示）；②成文智能体+审校打回+人工断点闭环；③MCP 标准协议+治理层（审计/超时/参数镜像校验，后端注入入参模型不填数）；④置信度双通道与无源拒答（阈值 0.45，无源断言 0.00）；⑤个人记忆双保险召回（正则 cue + fast 模型意图分类兜底）；⑥端侧原生 AI（Web Speech 本机语音）+ 手账式承载（日记本书：手写体/荧光笔/图钉）。
应用创新：①拍照→碳水/GL→指南→带引用建议的完整闭环（食物碳水来自《中国食物成分表》并逐项标来源，无权威 GI 只报碳水）；②饮食日记本书（图钉迷你卡入口，一页一天，可翻阅可编辑）；③AGP 风格个人血糖趋势报告（目标区间阴影带、餐后时段、碳水×血糖散点，回答内自动附个人数据图）；④多用户隔离开箱即用（不登录也有 local 演示身份）；⑤全链路可观测（SSE 节点事件、工具审计、历史回放）。

---

## 第二部分 · 用本文档组织最终《技术文档》PDF 的施工说明

### 15. 交付物与硬要求

| 要求项 | 具体要求 |
|---|---|
| 格式 | PDF，**不超过 30 页**（封面、目录、参考文献都计入） |
| 内容 | 项目概述、需求分析、系统架构设计、AI 技术方案、核心功能实现、测试与部署、总结与展望 |
| AI 技术说明 | 须重点阐述**选型理由、集成方式、优化策略** |
| 创新点说明 | 须明确列出**技术创新点与应用创新点** |

素材：本文（第一部分，项目全部事实）+ `docs/tech-report.md`（九章初稿，主体骨架）+ `docs/metrics.md`（指标原文）。**文档里的任何数字只能来自这三处，禁止编造。**

### 16. 建议目录与篇幅（正文 24–28 页，留余量）

1. 封面（Glucoguard · 慢病控糖膳食助手 + 团队信息）
2. 目录
3. 项目概述（背景痛点 ①饭前不知碳水/GL ②网上建议真假难辨 ③知道要少吃但缺可执行可核验的个性化建议；产品定位；合规边界）— 1–2 页
4. 需求分析（用户画像 35–65 岁拍照记录三餐；功能需求表 F1–F8：拍照识餐/语音输入/带引用问答/执行过程可视化/健康档案与趋势/饮食日记本/个人记忆问答/账号隔离；非功能需求：安全合规、隐私、可观测、可用性、性能；差异化「无源不答」）— 2–3 页
5. 系统架构设计（总体架构图、后端分层、六角色图与条件边、SSE 时序、前端结构、部署拓扑）— 3–4 页含图
6. **AI 技术方案（重点，6–8 页，占 1/4–1/3）**：选型理由表（LangGraph 多智能体图 vs 单次 RAG；LiteLLM 双档分工 fast/strong；R2R 混合检索向量+BM25+RRF+精排；MCP stdio 工具协议；Web Speech 端侧语音；SQLite+结构化记忆）；集成方式（SSE /api/chat 事件流；MCP 10 工具挂进 executor、治理层、后端注入入参；证据池 E1…En 与 [E#] 回看；memory 通道正则+LLM 意图双保险；护栏与置信度双通道）；优化策略（联网缓存+失败冷却、域名加权、通道独立超时；fast 档关思考模式；编排预算与人工断点；成文确定性校验；降级兜底 fake/live；实测指标表）
7. 核心功能实现（F1–F8 各一小节，配界面截图）— 4–5 页含图
8. 测试与部署（389 测试、金标/护栏/降级评测命令、部署步骤、环境变量模板说明、在线演示方案）— 2–3 页
9. 创新点说明（技术创新 6 条 / 应用创新 5 条，分两节）— 1–2 页
10. 总结与展望（已完成 / 已知局限：推理仍全云端、无请求级限流、手动点测无法估 CGM 指标；后续：ONNX Runtime Web+WebGPU 端侧小模型做端云协同、接 CGM、限流配额、长期在线演示；可呼应 AI Native / MCP 标准化 / 端云协同三大趋势）— 1 页
11. 附录（API 表、关键配置项、目录结构）— 1–2 页

### 17. 截图清单（tech-report.md 的【图 x】占位必须逐一替换）

| 占位 | 内容 | 来源 |
|---|---|---|
| 图 1-1 | 产品主界面（控糖工作台） | 前端 :5173 截图 |
| 图 1-2 | 饮食日记本书展开态 | 同上 |
| 图 3-1 | 系统总体架构图 | 手绘（draw.io/excalidraw） |
| 图 3-2 | 问答链路时序图（guard→六角色→SSE） | 手绘 |
| 图 3-3 | 部署拓扑图（compose 栈 + 端口 7272/7997/8000/5173） | 手绘 |
| 图 5-1 | 问答 + 右侧证据面板 | 运行后提问一次截图 |
| 图 5-2 | 健康趋势报告 | 档案卡健康趋势页 |
| 图 5-3 | 日记本书展开态 | 同上 |

图片单张 < 300KB、整文 < 5MB；页眉项目名+页码；正文 10–10.5pt、行距 1.4–1.5；正式书面中文，术语首次出现给中文解释。

### 18. 禁止事项

- 禁止出现任何真实 API Key/密码/token；配置只以 `MRAG_*` 变量名 + `.env.example` 模板方式出现。
- 禁止编造指标/测试数/功能；数字以本文第一部分 §12 与 docs/metrics.md 为准（测试数以最新一次 `pytest -q` 实跑为准）。
- 不写「已获医疗认证」；合规口径固定为「饮食与生活方式参考，非医疗器械，不做诊断、不给药剂量建议」。
- 不把 tech-report.md 的「转 PDF 说明 / 送审稿」母稿腔调带进最终文档。

### 19. 推荐产出步骤

1. 通读本文第一部分 + tech-report.md，按 §16 目录重组（保留九章骨架，创新点单独成章）。
2. 精炼语言，保留表格（需求表/选型表/指标表/API 表 PDF 中观感好）。
3. 画 3 张架构图、截 5 张界面图，替换全部【图 x】。
4. 导出 PDF：Typora 导出，或 VS Code「Markdown PDF」插件，或 `pandoc --pdf-engine=xelatex`（指定中文字体如 Noto Serif CJK SC）。
5. 检查：页数 ≤ 30、目录页码正确、图片清晰、无 API key、封面有团队信息。
6. 命名建议：`Glucoguard-技术文档.pdf`。

### 20. 风格定位（面向四类考察点）

评委考察前端工程能力、AI 技术集成能力、创新思维能力、用户体验设计能力。对应落点：架构图与分层/装配体现工程能力；第 6 章体现 AI 集成与优化；创新点章节体现创新思维；功能实现里的证据面板、执行 HUD、日记本书等交互细节体现 UX 设计能力。
