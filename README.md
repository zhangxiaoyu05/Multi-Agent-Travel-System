# 入境定制游多 Agent 系统

基于 **LangGraph** + **FastAPI** + **阿里百炼** 的智能旅游规划平台，由意图路由器统一分发到多个业务 Agent，为入境游客提供行程定制、FAQ 答疑、人工接管等一站式服务。

---

## 架构概览

```
用户消息 → input_guard → session_context → query_rewrite → intent_router → route_decision
                                                                                   │
                    ┌────────────────── 粗粒度 Journey Stage ────────────────────┐  │
                    │  discovery ──→ planning ──→ sales ──→ post_purchase     │  │
                    │  (意图分类)   (定制中)   (销售中)   (运营中)             │  │
                    └──────────────────────────────────────────────────────────┘  │
         ┌────────────┰───────────┰──────────────┰────────────────────────────────┼──────────────────────┐
         ▼            ▼           ▼              ▼                                ▼                      ▼
  customer_service  sales_agent  operations    trip_planner                  human_handoff
   FAQ / 转人工     Pipeline    _agent        (需求采集/草案生成/             (人工接管)
                  (5阶段销售)  (运营/订单/工单) 修订循环)                       │
         │            │           │              │                                │
         └────────────╋───────────╋──────────────╋────────────────────────────────┼
                      │           │              │                                │
                      └───────────┴──────────────┴────→ _agent_exit ←─────────────┘
                                              (统一出口：need_human→handoff
                                              / next_agent≠current→intent_router
                                              / 默认→operations_sync→END)
```

> 💡 **运营 Agent 重设计（Phase 21）**：运营重新定位为"用户与产品的桥梁"——① 10 个共享工具（产品查询 search_hotels/flights/tickets/guides + 订单管理 get_order/list_orders/cancel_order/modify_order + 工单 create_ticket/check_ticket）；② WON 成交后自动接管（operations_handoff 节点生成接管消息）；③ 活跃订单自动路由加权（has_active_order → operations ×1.5）；④ 产品查询工具作为平台共享能力层，trip_planner/sales 也可调用。
>
> 🔗 **旅程驱动多 Agent 协作（Phase 22 + 22-续）**：核心架构升级——引入 `journey_stage`（粗粒度 4 阶段：discovery→planning→sales→post_purchase）+ `next_agent`（Agent 自主声明下一站）+ `handoff_context`（交接上下文）。路由从意图分类主导向旅程阶段驱动转变：非 discovery 阶段跳过 LLM 意图分类，直接路由到 stage 对应 Agent。Agent 间通过 `handoff_context` 接力：trip_planner 确认 → sales_agent（同轮自动接管，QUALIFIED 阶段跳过 LEAD）；sales_agent 假支付 → `process_payment` mock 工具 → WON → operations_agent（同轮自动接管）；operations_agent 回流转 → trip_planner/sales_agent。三个 Agent 出口统一为 `_agent_exit`（仅当 next_agent ≠ current_branch 时重路由，避免循环）。E2E 验证通过：行程定制(85%)→确认→销售咨询(85%)同轮切换。

> 💡 **共享黑板**：所有节点共用 `AgentState`，字段有明确 owner。新增 `handoff`（转人工上下文）、`agent_traces`（追加式审计日志）、`branch_history`（路径追踪）。分支切换时自动重置控制信号防止跨分支污染。
> 
> 🛡️ **意图预过滤**：能力询问/寒暄/道谢类消息跳过 LLM，正则匹配后直接免转人工路由到客服——消除 LLM hallucinate `need_human=true` 导致的误判。
>
> 🎯 **行程定制预检（Phase 22-续-2）**：行程规划类消息（如"我想去拉萨，一个人，预算5000元"）在调用 LLM 前由正则预检拦截——8 个正向模式（独立"定制"、设计/规划行程、目的地改为X、多要素组合、独立"我想去X"等）+ 4 个 FAQ 排除模式（签证/边防证/流程/材料询问），命中后直接返回 `planner=0.85` + `journey_stage="planning"`，跳过 LLM 意图分类，消除对话历史惯性导致的误判。Chrome DevTools E2E 验证：全链路 定制(85%)→销售(85%) 接力正常。
>
> 🕐 **侧边栏时间修复（Phase 22-续-3）**：`save_message()` 插入消息后未同步更新 `conversations.updated_at`，导致前端左侧对话列表时间不随新消息刷新。修复后每次保存消息时同步 `UPDATE conversations SET updated_at = CURRENT_TIMESTAMP`。
>
> 🧠 **三层记忆系统（AI 可读）**：短期（Redis+MySQL 对话缓存 → Agent 上下文）、中期（LLM 提取旅行偏好 → 自动补全需求）、长期（用户画像 → Agent Prompt 注入）。切换窗口不丢失，AI 主动引用用户偏好减少追问。
>
> 🎨 **Markdown 渲染**：AI 回复使用原生 Markdown 格式（标题/分隔线/列表/代码块/粗体），前端块级解析引擎渲染，告别 ASCII `====`/`----` 符号。
>
> 🛑 **用户可打断**：AI 生成过程中支持随时中断（红色停止按钮），前端 AbortController + SSE 流中断 + 后端优雅处理，用户可补充纠正后继续对话。
>
> 🤖 **智能客服模式**：左下角模式下拉框可切换"默认（智能路由）/ 行程定制 / 智能客服 / 销售咨询 / 运营处理"。选择"默认"时自动走意图路由分发到最合适的 Agent；智能客服采用双路 RAG 检索管道——向量语义检索（Milvus 余弦相似度）+ BM25 关键词检索（中英文混合分词）→ RRF 倒数排名融合 → Top-K 注入 Prompt → LLM 生成回答，检索签证/支付/退改/交通等 30 篇知识库文档。
>
> 🔌 **MCP 标准化工具层**：6 个独立 MCP Server 子进程（weather/calendar/inventory/quote/crm/capi），自研 JSON-RPC 2.0 over stdio 协议（零外部依赖），Agent 通过 `tools/mcp_tools.py` 透明调用。真实数据源：Open-Meteo 天气（48城市/chinese-calendar 节假日/动态定价引擎/MySQL CRM），MCP 离线时自动降级到 mock 实现。TripPlanner 工具调用从串行改为 `asyncio.gather` 并行（响应时间预计节省 50%+）。
>
> 🔍 **查询改写**：在意图路由前新增 `query_rewrite` 节点——将用户拼音/中英混杂/错别字输入（如"bei jing 3天 2 person"）自动改写为规范中文（"北京3天2人行程"）。快速跳过机制：短确认和已规范中文直接跳过 LLM 调用，零额外成本。显著提升下游意图分类、RAG 检索、字段提取的准确率。
>
> 💰 **模型分层成本优化**：三层模型架构——Light（qwen-plus：客服、运营、查询改写，支持多工具 function calling）、Mid（qwen-plus：销售、路由、打分）、Heavy（qwen3-max：行程定制）。客服/运营从最贵模型降至中档模型，每次对话成本降低 ~85%。所有模型均支持 function calling，Agent 代码零改动，环境变量可控。
>
> 🛒 **销售 Pipeline 状态机**：五阶段销售漏斗（LEAD→QUALIFIED→NEGOTIATION→CLOSING→WON/LOST），分阶段 Prompt 动态加载（引导定制→回顾行程→处理异议→促成成交），5 个销售工具（行程加载/报价/下单/支付链接/优惠券）。跟进策略：24h 温和追问 → 3d 小额优惠（机票/酒店/门票选 1-2 项）→ 7d 自动放弃。支持销售中随时跳转 trip_planner 修改行程后回来继续。
>
> 🌐 **多语言支持**：左下角语言下拉框支持 5 种语言（中文/English/हिन्दी/Español/العربية），选择后 AI 以目标语言回复——语言指令注入所有 Agent system prompt（qwen 原生多语言能力）。
>
> 🎨 **Skyline 天蓝主题**：全局浅色旅行风格——天蓝主色调 `#0ea5e9`、白色侧边栏、轻灰背景，告别紫色系。

## 技术栈

| 层级 | 技术 | 说明 |
|------|------|------|
| 编排引擎 | LangGraph ≥ 0.2 | StateGraph + 条件边 + Checkpoint |
| Agent 框架 | LangChain ≥ 0.3 | @tool 装饰器 + Tool 封装 |
| Web 框架 | FastAPI ≥ 0.115 | 异步 API + 静态文件服务 |
| LLM 调用 | httpx 直连百炼 | 零 langchain-openai 依赖，支持 async/await |
| LLM Light | 百炼 qwen-plus | 客服、运营、查询改写（平衡速度与多工具调用） |
| LLM Mid | 百炼 qwen-plus | 销售、路由、意图打分（中等推理） |
| LLM Heavy | 百炼 qwen3-max | 行程定制（复杂长文本生成） |
| 认证 | JWT (python-jose) + bcrypt | 最简用户名+密码登录 |
| 前端 | 原生 HTML/CSS/JS（仿 DeepSeek） | 登录/多对话/SSE 流式输出 |
| 多语言 | zh / en / ja / ko | 中文 + 英文 + 日文 + 韩文 |
| Embedding | 百炼 text-embedding-v4 | 1024 维向量 |
| 向量数据库 | Milvus 2.4（单机） | HNSW 索引 + COSINE 相似度 + REST API v2 |
| 关系数据库 | MySQL 8.0 | 会话存储 + LangGraph Checkpoint |
| 缓存 | Redis 7 | 会话历史 + 摘要缓存 |
| Python | 3.12 | |
| 容器化 | Docker + docker-compose | 一键部署 |

**环境变量**：`TOOL_MODE=mock` 切换工具后端（mock=模拟数据 / real=真实 API）。当前全部 6 个工具已通过 MCP 标准化接入真实数据源：天气（Open-Meteo 免费 API，48城市）、日历（chinese-calendar 中国节假日）、库存（48城市×季节波动引擎）、报价（多因子动态定价）、CRM（MySQL 持久化）、CAPI（Meta/Google/TikTok 转化上报）。MCP Server 离线时自动降级到 mock，服务不中断。

## 项目结构

```
Multi_Agent/
├── api/                   # FastAPI 层（/chat 接口、请求模型、生命周期、认证）
│   ├── main.py            # FastAPI app + /chat/stream + 启动/测试入口
│   ├── schemas.py         # 请求/响应 Pydantic 模型
│   ├── auth.py            # 登录/注册 + JWT 签发
│   └── dependencies.py    # get_current_user 依赖注入
├── graph/                 # LangGraph 编排层
│   ├── state.py           # 全局共享 AgentState
│   ├── builder.py         # 图构建与编译（四分支完整版）
│   ├── nodes/             # 节点实现（薄层，调用 Agent）
│   │   ├── input_guard.py
│   │   ├── session_context.py
│   │   ├── query_rewrite.py  # 🆕 查询改写：纠错+规范化
│   │   ├── intent_router.py
│   │   ├── customer_service.py
│   │   ├── trip_planner.py
│   │   ├── intent_scorer.py
│   │   ├── revision_loop.py
│   │   ├── sales_agent.py
│   │   ├── operations_agent.py
│   │   ├── human_handoff.py
│   │   └── operations_sync.py
│   └── conditions/        # 条件边（路由判断）
│       ├── route_decision.py
│       ├── after_service.py
│       ├── after_sales.py
│       ├── requirements_complete.py
│       └── revision_decision.py
├── agents/                # Agent 业务实现
│   ├── base.py            # BaseAgent 抽象基类
│   ├── customer_service.py
│   ├── trip_planner.py
│   ├── sales_agent.py
│   └── operations_agent.py
├── mcp/                   # 🆕 MCP 标准化工具层（JSON-RPC 2.0 over stdio）
│   ├── __init__.py
│   ├── server.py          # MCP Server 基类（150行，零依赖）
│   └── servers/           # 6 个独立 MCP Server 子进程
│       ├── weather_server.py    # Open-Meteo 实时天气（48城市）
│       ├── calendar_server.py   # chinese-calendar 真实节假日 + 人流量
│       ├── inventory_server.py  # 48城市×季节系数库存引擎
│       ├── quote_server.py      # 多因子动态报价引擎
│       ├── crm_server.py        # MySQL CRM 记录写入
│       └── capi_server.py       # Meta/Google/TikTok 转化上报
├── tools/                 # LangChain Tools
│   ├── mcp_tools.py        # 🆕 MCP → LangChain @tool 包装器（6工具 + mock 自动降级）
│   ├── rag_faq.py         # RAG FAQ（双路检索：向量 + BM25 → RRF 融合）
│   ├── mock_handoff.py    # 转人工评估
│   ├── bm25_retriever.py   # BM25 关键词检索（中英文混合分词 + 30 篇索引）
│   ├── rrf_fusion.py       # RRF 倒数排名融合（k=60 + content hash 去重）
│   ├── mock_weather.py    # 天气查询（12 城市 Mock + Open-Meteo 真实 API）
│   ├── weather_real.py    # 真实天气（Open-Meteo 免费 API，45 城市）
│   ├── mock_calendar.py   # 节假日 / 人流量（真实星期计算 + 内置节假日）
│   ├── calendar_real.py   # 真实日历 API 骨架
│   ├── mock_inventory.py  # 酒店 / 门票 / 车辆库存
│   ├── inventory_real.py  # 真实库存 API 骨架
│   ├── mock_quote.py      # 报价生成（32 城市基准价）
│   ├── quote_real.py      # 真实报价 API 骨架
│   ├── mock_crm.py        # CRM 客户记录写入
│   ├── crm_real.py        # 真实 CRM API 骨架
│   ├── mock_capi.py       # CAPI 转化事件发送
│   ├── capi_real.py       # 真实 CAPI API 骨架
│   └── mock_sales.py      # 🆕 销售工具（下单/支付/优惠/行程加载）
├── services/              # 基础设施
│   ├── llm.py             # LLM 工厂（qwen-turbo + qwen-plus + qwen3-max 三层，含 astream 流式）
│   ├── mcp_client.py      # 🆕 MCP Client（子进程管理 + 工具发现 + JSON-RPC 通信）
│   ├── stream_bridge.py   # 🆕 SSE token 队列桥接（Agent → 前端打字机流式）
│   ├── memory.py          # 🆕 短/中/长期记忆管理器（消息双写 + Token估算 + 偏好提取 + 画像CRUD）—— Agent 可读
│   ├── embeddings.py      # Embedding（text-embedding-v4，DashScope 原生 API）
│   ├── vector_store.py    # 向量存储（Milvus + HNSW 索引）
│   ├── mysql.py           # MySQL 连接池（SQLAlchemy async）
│   ├── redis.py           # Redis 缓存（会话历史 + 摘要 + 消息 + 画像）
│   ├── checkpoint.py      # MySQL Checkpoint Saver（LangGraph 持久化）
│   └── user_store.py      # 用户/对话数据库操作
├── scripts/               # 运维脚本
│   ├── knowledge_base.py  # 知识库文档定义（30 篇）
│   ├── ingest_knowledge.py # 知识库摄入脚本（Milvus）
│   └── migrate_mysql.sql  # MySQL 初始化 DDL
├── frontend/              # 前端页面
│   ├── index.html         # 聊天界面（仿 DeepSeek 布局 + 登录/多对话）
│   └── profile.html       # 🆕 用户画像页面（编辑偏好 + AI 建议确认）
├── prompts/               # System Prompt 模板（11 个）
│   ├── intent_router.txt
│   ├── customer_service.txt
│   ├── trip_planner.txt
│   ├── operations_agent.txt
│   ├── summary.txt            # 🆕 对话摘要 Prompt
│   ├── preference_extract.txt # 🆕 偏好提取 Prompt
│   ├── query_rewrite.txt      # 🆕 查询改写 Prompt
│   ├── sales_lead.txt         # 🆕 销售 LEAD 阶段 Prompt
│   ├── sales_qualified.txt    # 🆕 销售 QUALIFIED 阶段 Prompt
│   ├── sales_negotiation.txt  # 🆕 销售 NEGOTIATION 阶段 Prompt
│   └── sales_closing.txt      # 🆕 销售 CLOSING 阶段 Prompt
├── tests/                 # 单元测试（243 个用例）
│   ├── conftest.py
│   ├── test_state.py
│   ├── test_graph.py
│   ├── test_router.py
│   ├── test_customer_service.py
│   ├── test_trip_planner.py
│   ├── test_sales.py
│   ├── test_operations.py
│   ├── test_auth.py        # 认证测试（JWT + 注册/登录）
│   ├── test_conversations.py  # 对话 CRUD 测试
│   └── test_api.py         # API 端点测试（/health /chat /chat/stream）
├── pytest.ini             # pytest-asyncio 配置
├── docker-compose.yml     # Docker Compose 编排（6 个服务）
├── Dockerfile
├── requirements.txt
└── .env.example          # 环境变量模板
```

## 快速开始

### 前置条件

| 依赖 | 版本 | 说明 |
|------|------|------|
| Docker Desktop | 最新版 | 容器运行环境（Windows/Mac/Linux） |
| Python | ≥ 3.12 | 仅本地开发模式需要 |
| 百炼 API Key | — | 阿里云百炼控制台获取 |

### Docker 部署（推荐）

> 💡 国内网络环境已配置阿里云镜像源（apt + pip），无需额外配置即可快速构建。

```bash
# 1. 克隆项目
git clone https://github.com/zhangxiaoyu05/Multi-Agent-Travel-System.git
cd Multi-Agent-Travel-System

# 2. 配置环境变量
cp .env.example .env
# 编辑 .env：
#   - 将 LLM_API_KEY 替换为你的百炼 API Key
#   - 生产环境务必修改 JWT_SECRET_KEY 为随机字符串
#   - 其余配置保持默认即可

# 3. 一键启动所有服务（首次构建约 3-5 分钟）
docker-compose up --build -d

# 4. 等待所有服务健康（约 60s）
docker-compose ps
# 确认各服务状态为 healthy 或 running

# 5. 导入知识库（首次启动后执行一次）
docker-compose exec app python scripts/ingest_knowledge.py
# 预期输出：Successfully ingested 30 documents in ~3s

# 6. 验证部署
curl http://localhost:8001/health
# → {"status":"ok","version":"0.3.0","components":{"mysql":"ok","redis":"ok","milvus":{"status":"ok","count":30,...}}}

# 7. 浏览器打开 http://localhost:8001
# 注册账号 → 登录 → 新建对话 → 发送消息测试
```

**Docker 服务端口映射**：

| 服务 | 容器端口 | 宿主机端口 | 说明 |
|------|:---:|:---:|------|
| app (FastAPI) | 8000 | 8001 | 若 8001 冲突可改为 8000 |
| mysql | 3306 | 3307 | 若 3307 冲突可改为 3306 |
| redis | 6379 | 6379 | — |
| milvus | 19530 | 19530 | REST API |

> **端口说明**：若宿主机 8000/3306 已被占用，docker-compose.yml 已配置回退端口 8001→8000 / 3307→3306。如仍需修改，编辑 `docker-compose.yml` 中 `ports` 映射即可。

### 本地开发

```bash
# 1. 启动基础设施（不含 app，避免端口冲突）
docker-compose up -d mysql redis etcd minio milvus-standalone

# 2. 配置 .env 中的连接地址为本地端口
# MYSQL_HOST=localhost  MYSQL_PORT=3307
# REDIS_HOST=localhost  REDIS_PORT=6379
# MILVUS_HOST=localhost MILVUS_PORT=19530

# 3. 安装 Python 依赖
pip install -r requirements.txt

# 4. 导入知识库
python scripts/ingest_knowledge.py

# 5. 启动应用
python -m api.main
# → 访问 http://localhost:8000

# 6. 运行测试
python -m pytest tests/ -v          # 全部 243 个测试
python -m api.main test             # E2E 集成测试（12 组）
python -m api.main test --quick     # 快速模式（跳过行程生成）
```

### 常见问题

| 现象 | 原因 | 解决方案 |
|------|------|------|
| **"令牌无效或已过期"** | Token 过期（24h）或浏览器缓存了旧 token | 刷新页面会自动跳转登录页（v0.3.1+），重新登录即可 |
| **"MySQL not initialized"** | Docker MySQL 容器未启动 | `docker-compose up -d mysql`，等待 healthy 后重试 |
| **端口冲突 (8000/3306)** | 宿主机端口被占用 | 使用备选端口 8001/3307（docker-compose 已配置），或修改 .env |
| **前端页面空白/无法加载** | API 服务离线或 CORS 问题 | `docker-compose ps` 确认 app 容器状态，检查浏览器控制台错误 |
| **知识库检索无结果** | Milvus 未就绪或未导入 | 等待 60s 后执行 `docker-compose exec app python scripts/ingest_knowledge.py` |
| **行程生成长时间无响应** | qwen3-max 推理需 30-120s | 正常现象，SSE 流式界面会显示实时进度（"正在分析意图…"→"正在生成行程…"） |
| **Docker 构建失败** | 镜像拉取超时（国内网络） | 已配置阿里云 apt/pip 镜像，如仍超时可配置 Docker 镜像加速器 |
| **登录后无法新建对话** | MySQL 连接失败但被静默处理 | 检查 `docker-compose logs mysql`，确认端口映射和密码正确 |

## API 接口

### 认证

| 方法 | 路径 | 说明 |
|------|------|------|
| `POST` | `/auth/register` | 注册（`{username, password}` → `{user_id, token}`） |
| `POST` | `/auth/login` | 登录（`{username, password}` → `{user_id, token, username}`） |

> 注册规则：用户名 3-20 位字母数字，密码 ≥ 6 位。登录后获得 JWT token，有效期 24h。

### 对话管理（需认证）

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/conversations` | 获取当前用户的对话列表 |
| `POST` | `/conversations` | 新建对话 |
| `DELETE` | `/conversations/{id}` | 删除对话（同时清理 checkpoint） |
| `GET` | `/conversations/{id}/messages` | 获取对话历史消息（含摘要，Redis→MySQL→Checkpoint 三级回退） |

### `GET /health`

健康检查，返回各组件连接状态。

```json
{
  "status": "ok",
  "version": "0.3.0",
  "components": {
    "api": "ok",
    "mysql": "ok",
    "redis": "ok",
    "milvus": {"status": "ok", "count": 30, "backend": "Milvus REST v2"}
  }
}
```

### `POST /chat/stream`

**流式对话接口**（SSE）—— 实时推送图节点执行进度，避免长时间等待"思考中"。

> ⚠️ 所有 `/chat` 端点需要 `Authorization: Bearer <token>` 请求头。

事件格式：
```
event: node_start      → {"node":"intent_router","label":"正在分析意图..."}
event: node_complete   → {"node":"intent_router"}
...
event: done            → {完整 ChatResponse}
```

> `/chat/stream` 暂不可用时前端自动降级回退到 `/chat` 普通 JSON 模式。

### 用户画像（需认证）

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/api/profile` | 获取当前用户画像（基础信息 + 旅行偏好 + LLM 建议） |
| `PUT` | `/api/profile` | 更新画像（可同时 `accept_suggestions: true` 采纳 AI 建议） |
| `GET` | `/api/profile/suggestions` | 获取 LLM 待确认的画像更新建议 |
| `POST` | `/api/profile/suggestions/accept` | 采纳所有 LLM 建议 → 合并到画像主字段 |
| `POST` | `/api/profile/suggestions/reject` | 忽略所有 LLM 建议 |
| `GET` | `/preferences` | 获取 LLM 自动提取的中期偏好快照 |

### 页面路由

| 路径 | 说明 |
|------|------|
| `/` | 聊天主界面 |
| `/profile` | 用户画像编辑页（浏览器直接访问） |

### 🧠 AI 记忆注入

> Phase 11-续：AI Agent 在对话时主动读取用户画像和偏好，无需用户重复描述。
>
> - **trip_planner**：画像自动补全行程需求（主题/节奏/特殊需求）→ 减少追问，Prompt 包含「客户画像」+「💡 根据您的历史偏好...」
> - **customer_service** / **sales_agent**：`extra_context` 注入国籍/兴趣/预算/目的地
> - **历史消息**：`/chat` 端点从 MySQL 加载历史 → checkpoint 空时回退

## 测试

```bash
# 运行全部 243 个单元测试（~17s，含异步测试 + auth/API/SSE + 记忆系统 + Pipeline + 运营工具）
python -m pytest tests/ -v

# 运行端到端集成测试
python -m api.main test          # 全量 12 组
python -m api.main test --quick  # 快速模式 8 组
```

### `POST /chat`

核心对话接口。

**请求体**：

```json
{
  "conversation_id": "conv-a1b2c3d4e5f6",
  "message": "我想去西安玩3天",
  "channel": "web",
  "language": "zh"
}
```

**响应体**：

```json
{
  "reply": "好的，还需要确认以下信息...",
  "current_branch": "planner",
  "draft": {
    "version": 1,
    "itinerary_md": "## 西安三日游行程...",
    "estimated_cost": "¥3500/人",
    "weather_summary": "晴转多云 22-28°C"
  },
  "need_human": false,
  "intent_scores": {
    "service": 0.1,
    "sales": 0.05,
    "operations": 0.05,
    "planner": 0.8
  }
}
```

## Docker 服务清单

| 服务 | 镜像 | 端口映射 | 用途 |
|------|------|:---:|------|
| app | python:3.12-slim | 8001→8000 | FastAPI 后端 |
| mysql | mysql:8.0 | 3307→3306 | 会话 + Checkpoint 持久化 |
| redis | redis:7-alpine | 6379→6379 | 会话缓存 |
| etcd | quay.io/coreos/etcd:v3.5.5 | 2379 | Milvus 元数据 |
| minio | minio/minio | 9000 | Milvus 对象存储 |
| milvus-standalone | milvusdb/milvus:v2.4.0 | 19530 | 向量检索（REST API） |

> 端口映射可根据宿主机实际情况调整，容器内端口不变。

## 开发阶段

| Phase | 内容 | 状态 |
|-------|------|:---:|
| Phase 0 | 项目骨架 + Docker 环境 | ✅ |
| Phase 1-2 | State 共享黑板 v2（字段所有权契约 + HandoffContext + AgentTrace）+ 意图路由器 v3（路由节点+条件分离，预过滤器防 LLM 误判，分支惯性偏向） | ✅ |
| Phase 3 | 客服 Agent + 人工接管 | ✅ |
| Phase 4 | 定制 Agent + 修订循环 | ✅ |
| Phase 5 | 终态写入 + /chat 联调 | ✅ |
| Phase 6 | 销售 Agent + 运营 Agent | ✅ |
| Phase 7 | RAG 增强（Milvus 向量检索） | ✅ |
| Phase 8 | 基础设施升级（MySQL + Redis + Docker 全容器化） | ✅ |
| Phase 9 | SSE 流式输出（进度推送 + 降级兼容） | ✅ |
| Phase 10 | 意图路由预过滤 + Markdown 渲染引擎 + AI 回复格式美化 + 消息框对齐 | ✅ |
| Phase 11 | 短/中/长期记忆系统（存储 + 前端展示） | ✅ |
| Phase 11-续 | AI 记忆注入——Agent 读取画像/偏好/历史消息，Prompt 注入 + 自动补全需求 | ✅ |
| Phase 12 | 用户可打断功能——SSE 流式中断（AbortController + 后端优雅处理），支持补充纠正后继续 | ✅ |
| Phase 12-续 | 打断后上下文丢失修复——预存用户消息 + 历史消息 regex 回溯提取需求字段 | ✅ |
| Phase 13 | 智能客服功能——模式选择器 + FAQ 检索（在线/离线流程）+ 快捷 FAQ 标签 | ✅ |
| Phase 13-续 | 语言选择器恢复——5 种语言（zh/en/hi/es/ar）完整支持，后端指令注入 + 前端并排下拉框 | ✅ |
| Phase 13-续-2 | 模式视觉区分增强——Bug 修复 current_branch 映射 + 前端三层标记（用户模式标签/Agent 左侧色条/气泡内分支标签/切换分隔线） | ✅ |
| Phase 13-续-3 | 自定义确认对话框——替换浏览器 confirm()，卡片式 UI + 动画 + ESC/遮罩关闭 | ✅ |
| Phase 14 | UI 全局重设计——Skyline 天蓝旅行主题（浅色侧边栏 + 统一色系） | ✅ |
| Phase 15 | Token 过期修复 + 环境变量补齐 + 启动流程文档完善 | ✅ |
| Phase 16 | 前端模式选择器补齐销售/运营 Agent——4 Agent 完整可手动切换 | ✅ |
| Phase 17 | 客服 RAG 管道重设计——双路检索（向量 + BM25）→ RRF 倒数排名融合 → Top-K → Prompt 注入 | ✅ |
| Phase 18 | MCP 标准化 + 全量真实 API 接入——6 个独立 MCP Server（自研 JSON-RPC 2.0 over stdio），真实数据源（Open-Meteo/chinese-calendar/动态定价引擎），三层降级（MCP→mock→错误提示），Agent 零感知切换，TripPlanner 工具并行化 | ✅ |
| Phase 18-续 | 流式输出打字机效果——BailianLLM.astream() 逐 token 推送 + stream_bridge 队列桥接 + SSE 端点重构（后台图任务+主循环读队列）；默认智能路由模式——前端 auto/默认 选项 + force_branch="" 触发意图分发；进度标签中文化——NODE_LABELS 补全 route_decision + fallback 去英文 | ✅ |
| Phase 19 | 查询改写节点——主干链路插入 query_rewrite（session_context → query_rewrite → intent_router），LLM 纠错规范化（拼音→中文、中英混杂→统一中文、错别字修正），快速跳过机制（短确认+已规范中文免 LLM 调用），改写效果： "bei jing 3天 2 person" → "北京3天2人行程" | ✅ |
| Phase 19-续 | 模型分层成本优化——三层架构（Light=qwen-turbo/Mid=qwen-plus/Heavy=qwen3-max），客服+运营 → qwen-turbo（↓~90% 费用），销售 → qwen-plus，行程保持 qwen3-max，新增 get_light_llm() 工厂，Agent 代码零改动 | ✅ |
| Phase 20 | 销售 Agent 重设计——Pipeline 五阶段状态机（LEAD→QUALIFIED→NEGOTIATION→CLOSING→WON/LOST）+ 4 个分阶段 Prompt 动态加载 + 5 个新 Mock 销售工具 + 跟进策略（24h 温和→3d 优惠→7d 放弃）+ 行程修改检测（goto_planner→trip_planner→回销售）+ 新建 5 文件/重写 2 文件/修改 10 文件/删除 1 文件 | ✅ |
| Phase 21 | 运营 Agent 重设计——用户与产品的桥梁：数据库 orders+tickets 表 + 10 个运营工具（产品查询×4 + 订单管理×4 + 工单×2）+ 工具即平台共享能力层（trip_planner/sales 也可调用）+ Agent 重写（12 工具 + WON 接管 + 紧急升级）+ operations_handoff 节点（销售成交运营自动接管）+ has_active_order 路由加权 + 新建 2 文件/重写 3 文件/修改 10 文件 + 243 测试全部通过 | ✅ |
| Phase 21-续 | E2E 测试修复：LIGHT_MODEL qwen-turbo→qwen-plus（多工具调用 400）+ 西班牙语回复中文（7语言指令）+ Profile 页面路由冲突（API→/api/*）+ ROUTER_MODEL 对齐 .env.example + reset_all_singletons() 免重启切换 | ✅ |
| Phase 21-续-4 | E2E 全功能测试——Chrome DevTools 测试 9 大功能模块 + 4 个 Bug 修复（P0 MCP Server 死锁、P1 Profile Pydantic 验证错误、P1 销售/运营 Agent 400 错误、P2 数据库缺表）+ 243 测试通过 | ✅ |
| Phase 21-续-5 | E2E 续测 11 项全覆盖（默认路由/运营/删除/画像/语言/销售Pipeline/西班牙语/空消息/客服FAQ/退出登录/模式视觉）+ Bug #5 修复（budget_range VARCHAR(32)→128） | ✅ |
| **Phase 22** | **旅程驱动的多 Agent 协作**——journey_stage 4阶段状态机 + next_agent 接力 + handoff_context 交接 + 意图路由降级为打断检测 + _agent_exit 统一出口 + Agent 交接协议（定制→销售→运营→回流转）+ Bug 修复（_agent_exit 无限循环）+ 14 文件修改 | ✅ |
| Phase 22-续 | **同轮交接 + 假支付——全链路自动接力**——revision_decision accept+阶段变更→route_decision（同轮交接）+ intent_scorer→route_decision 新边 + trip_planner `_is_confirm_signal()` 快速确认检测 + `process_payment` 假支付 mock 工具 + sales_agent WON 检测重构（仅支付成功触发，create_order 不再误判）+ sales_closing Prompt 支付流程引导 + 测试更新（98 全部通过）+ E2E 浏览器验证（定制→销售同轮切换） | ✅ |

## 许可证

MIT
