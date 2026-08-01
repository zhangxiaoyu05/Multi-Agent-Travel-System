# 入境定制游多 Agent 系统

基于 **LangGraph** + **FastAPI** + **阿里百炼** 的智能旅游规划平台，由意图路由器统一分发到多个业务 Agent，为入境游客提供行程定制、FAQ 答疑、人工接管等一站式服务。

---

## 架构概览

```
用户消息 → input_guard → session_context → intent_router → route_decision
                                                                    │
        ┌──────────────────┰────────────────────┼──────────────────────────┐
        ▼                  ▼                    ▼                          ▼
 customer_service      sales_agent         trip_planner               human_handoff
  FAQ / 转人工         报价 / 签约         需求采集 / 草案                (人工接管)
        │                  │             生成 / 修订循环                      │
        ▼                  ▼                    │                            │
   human_handoff     operations_sync    ────────┘                            │
        │                  │                    │                            │
        └──────────────────╋────────────────────┼────────────────────────────│
                           ▼                    ▼                            ▼
                    operations_agent      operations_sync ←──────────────────┘
                     入驻 / 履约 / 工单   (终态：CRM + CAPI)
```

> 💡 **共享黑板**：所有节点共用 `AgentState`，字段有明确 owner。新增 `handoff`（转人工上下文）、`agent_traces`（追加式审计日志）、`branch_history`（路径追踪）。分支切换时自动重置控制信号防止跨分支污染。
> 
> 🛡️ **意图预过滤**：能力询问/寒暄/道谢类消息跳过 LLM，正则匹配后直接免转人工路由到客服——消除 LLM hallucinate `need_human=true` 导致的误判。
>
> 🧠 **三层记忆系统（AI 可读）**：短期（Redis+MySQL 对话缓存 → Agent 上下文）、中期（LLM 提取旅行偏好 → 自动补全需求）、长期（用户画像 → Agent Prompt 注入）。切换窗口不丢失，AI 主动引用用户偏好减少追问。
>
> 🎨 **Markdown 渲染**：AI 回复使用原生 Markdown 格式（标题/分隔线/列表/代码块/粗体），前端块级解析引擎渲染，告别 ASCII `====`/`----` 符号。
>
> 🛑 **用户可打断**：AI 生成过程中支持随时中断（红色停止按钮），前端 AbortController + SSE 流中断 + 后端优雅处理，用户可补充纠正后继续对话。
>
> 🤖 **智能客服模式**：左下角模式下拉框可切换"行程定制 / 智能客服"。智能客服走在线（FAQ 知识库自动应答）/离线（转人工工单）流程，检索签证/支付/退改/交通等 11 大类 QA 对。
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
| 路由模型 | 百炼 qwen-plus | 意图识别（平衡速度与质量） |
| 生成模型 | 百炼 qwen3-max | 行程生成、客服回复（强推理） |
| 认证 | JWT (python-jose) + bcrypt | 最简用户名+密码登录 |
| 前端 | 原生 HTML/CSS/JS（仿 DeepSeek） | 登录/多对话/SSE 流式输出 |
| 多语言 | zh / en / ja / ko | 中文 + 英文 + 日文 + 韩文 |
| Embedding | 百炼 text-embedding-v4 | 1024 维向量 |
| 向量数据库 | Milvus 2.4（单机） | HNSW 索引 + COSINE 相似度 + REST API v2 |
| 关系数据库 | MySQL 8.0 | 会话存储 + LangGraph Checkpoint |
| 缓存 | Redis 7 | 会话历史 + 摘要缓存 |
| Python | 3.12 | |
| 容器化 | Docker + docker-compose | 一键部署 |

**环境变量**：`TOOL_MODE=mock` 切换工具后端（mock=模拟数据 / real=真实 API）。当前天气已对接 Open-Meteo 免费 API（无需 API Key）。

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
├── tools/                 # LangChain Tools
│   ├── rag_faq.py         # RAG FAQ（Milvus 向量检索 + 关键词兜底）
│   ├── mock_handoff.py    # 转人工评估
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
│   └── capi_real.py       # 真实 CAPI API 骨架
├── services/              # 基础设施
│   ├── llm.py             # LLM 工厂（qwen-plus + qwen3-max）
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
├── prompts/               # System Prompt 模板（7 个）
│   ├── intent_router.txt
│   ├── customer_service.txt
│   ├── trip_planner.txt
│   ├── sales_agent.txt
│   ├── operations_agent.txt
│   ├── summary.txt            # 🆕 对话摘要 Prompt
│   └── preference_extract.txt # 🆕 偏好提取 Prompt
├── tests/                 # 单元测试（193 个用例）
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

### Docker 部署（推荐）

> 💡 国内网络环境已配置阿里云镜像源（apt + pip），无需额外配置即可快速构建。

```bash
# 1. 克隆项目
git clone https://github.com/zhangxiaoyu05/Multi-Agent-Travel-System.git
cd Multi-Agent-Travel-System

# 2. 配置环境变量
cp .env.example .env
# 编辑 .env，将 LLM_API_KEY 替换为你的百炼 API Key

# 3. 一键启动所有服务
docker-compose up --build -d

# 4. 导入知识库（首次启动后）
docker-compose exec app python scripts/ingest_knowledge.py

# 5. 访问
# 前端：http://localhost:8000（若端口冲突则用 8001）
# API 文档：http://localhost:8000/docs
# 健康检查：http://localhost:8000/health
```

> **端口说明**：若宿主机 8000/3306 已被占用，docker-compose.yml 已配置回退端口 8001→8000 / 3307→3306。

### 本地开发

```bash
# 前置条件：启动基础设施服务
docker-compose up -d mysql redis etcd minio milvus-standalone

# 若端口冲突，通过环境变量指定端口
export MYSQL_HOST=localhost MYSQL_PORT=3307
export REDIS_HOST=localhost
export MILVUS_HOST=localhost

# 安装依赖
pip install -r requirements.txt

# 启动服务
python -m api.main

# 或运行测试
python -m api.main test
python -m api.main test --quick   # 快速模式（跳过行程生成）
```

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
| `GET` | `/profile` | 获取当前用户画像（基础信息 + 旅行偏好 + LLM 建议） |
| `PUT` | `/profile` | 更新画像（可同时 `accept_suggestions: true` 采纳 AI 建议） |
| `GET` | `/profile/suggestions` | 获取 LLM 待确认的画像更新建议 |
| `POST` | `/profile/suggestions/accept` | 采纳所有 LLM 建议 → 合并到画像主字段 |
| `POST` | `/profile/suggestions/reject` | 忽略所有 LLM 建议 |
| `GET` | `/preferences` | 获取 LLM 自动提取的中期偏好快照 |

### 页面路由

| 路径 | 说明 |
|------|------|
| `/` | 聊天主界面 |
| `/profile` | 用户画像编辑页 |

### 🧠 AI 记忆注入

> Phase 11-续：AI Agent 在对话时主动读取用户画像和偏好，无需用户重复描述。
>
> - **trip_planner**：画像自动补全行程需求（主题/节奏/特殊需求）→ 减少追问，Prompt 包含「客户画像」+「💡 根据您的历史偏好...」
> - **customer_service** / **sales_agent**：`extra_context` 注入国籍/兴趣/预算/目的地
> - **历史消息**：`/chat` 端点从 MySQL 加载历史 → checkpoint 空时回退

## 测试

```bash
# 运行全部 193 个单元测试（~8s，含异步测试 + auth/API/SSE + 记忆系统）
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
| Phase 14 | UI 全局重设计——Skyline 天蓝旅行主题（浅色侧边栏 + 统一色系 + 两层同步） | ✅ |

## 许可证

MIT
