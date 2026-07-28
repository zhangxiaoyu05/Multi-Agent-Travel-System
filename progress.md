# 项目进度日志

> 入境定制游多 Agent 系统——基于 LangGraph + FastAPI + 阿里百炼
>
> 最后更新：2026-07-28

---

## 一、项目概述

基于 LangGraph 构建入境定制游平台的智能 Agent，由意图路由器统一分发到业务分支。Python 3.12 + FastAPI + Docker，LLM 使用阿里百炼平台。

### 技术栈速览

| 层级 | 技术 | 说明 |
|------|------|------|
| 编排引擎 | LangGraph ≥ 0.2 | 图结构、State 管理、Checkpoint |
| Agent 框架 | LangChain ≥ 0.3 | Agent 抽象、Tool 封装 |
| Web 框架 | FastAPI ≥ 0.115 | /chat 接口 |
| LLM | 阿里百炼 | qwen-turbo（路由）+ qwen-plus（生成） |
| 容器化 | Docker + docker-compose | 开发/生产一致 |
| Python | 3.12 | — |

### 关键文档

| 文档 | 说明 |
|------|------|
| `langgraph_agent实现方案.md` | 原始设计文档，详细架构与 Agent 定义 |
| `implementation_plan.md` | 完整实现方案，逐 Phase 展开，含具体代码 |

---

## 二、已确认技术决策（2026-07-28）

| # | 决策项 | 结论 |
|---|--------|------|
| 1 | LLM Provider | 阿里百炼（qwen-turbo + qwen-plus），API Key 已配置 |
| 2 | MVP Agent 范围 | 客服 + 定制（2个）；销售、运营 Phase 6 补齐 |
| 3 | RAG 知识库 | MVP 不做，Mock 假数据替代；Phase 7 接真实 RAG |
| 4 | 离线批处理 | 不做（与实际业务场景不符） |
| 5 | 语言支持 | 仅中文 |
| 6 | 前端 | 后续做一个简单聊天测试页面 |
| 7 | API 鉴权 | MVP 不加 |
| 8 | Checkpoint | MVP 用 MemorySaver（内存），生产切 PostgresSaver |

---

## 三、Phase 0 完成——项目骨架与 Docker 环境 ✅

**完成时间**：2026-07-28

### 创建的文件清单

```
D:\Multi_Agent\
├── .env.example              # 配置模板（提交 Git）
├── .env                      # 实际配置（含真实 API Key，不提交 Git）
├── .gitignore                # Git 忽略规则（7 大类）
├── .dockerignore             # Docker 镜像构建忽略
├── Dockerfile                # 应用镜像（python:3.12-slim）
├── docker-compose.yml        # 本地开发编排（单容器 + 代码热挂载）
├── requirements.txt          # 6 个核心依赖包
├── main.py                   # 本地快速启动入口（python main.py）
│
├── api/                      # FastAPI 层
│   ├── __init__.py
│   ├── main.py               # /health 已可用，/chat 待实现
│   └── schemas.py            # ChatRequest / ChatResponse Pydantic 模型
│
├── graph/                    # LangGraph 编排层（空骨架）
│   ├── __init__.py
│   ├── nodes/__init__.py
│   └── conditions/__init__.py
│
├── agents/__init__.py        # Agent 业务层（空骨架）
├── tools/__init__.py         # Tools 能力层（空骨架）
├── services/__init__.py      # 基础设施层（空骨架）
├── prompts/__init__.py       # Prompt 模板（空骨架）
└── tests/__init__.py         # 测试（空骨架）
```

### 验证结果

- `pip install -r requirements.txt` — 成功
- `python -c "from api.main import app"` — FastAPI 加载正常
- `python main.py` → `http://localhost:8000/health` 可响应

### 环境变量说明

`.env.example` 为配置模板，包含以下配置组：

- **LLM 配置**（LLM_API_KEY, LLM_BASE_URL, ROUTER_MODEL, AGENT_MODEL）
- **模型参数**（ROUTER/AGENT 的 temperature 和 max_tokens）
- **服务配置**（HOST, PORT, LOG_LEVEL, REQUEST_TIMEOUT）
- **业务配置**（MAX_REVISIONS, MAX_MESSAGE_LENGTH）
- **未来预留**（DATABASE_URL, REDIS_URL, VECTOR_DB, LANGFUSE，均为注释状态）

使用方式：`cp .env.example .env` → 编辑 `.env` 填入真实 API Key。`.env` 已被 `.gitignore` 排除，不会提交到 Git。

---

## 四、实施路线图

```
Phase 0  ██████████  ✅ 项目骨架 + Docker 环境         2026-07-28 完成
Phase 1  ░░░░░░░░░░  State 定义 + 最简图               待开始
Phase 2  ░░░░░░░░░░  意图路由器完善                    待开始
Phase 3  ░░░░░░░░░░  客服 Agent + 人工接管             待开始
Phase 4  ░░░░░░░░░░  定制 Agent + 修订循环             待开始
Phase 5  ░░░░░░░░░░  终态写入 + /chat API 联调         待开始
────────── MVP 完成线 ─────────────────────────────────────
Phase 6  ░░░░░░░░░░  销售 Agent + 运营 Agent           后续
Phase 7  ░░░░░░░░░░  RAG 增强（真实向量检索）           后续
Phase 8  ░░░░░░░░░░  生产化（按需）                     后续
```

### 下一步：Phase 1

**目标**：定义完整的 AgentState，搭建从用户消息到路由结果的最简图，验证 LangGraph 能正常 invoke。

**将创建的文件**：

```
graph/state.py                # AgentState 定义
graph/builder.py              # build_graph() 图构建
graph/nodes/input_guard.py    # 入参保护
graph/nodes/session_context.py # 会话初始化
graph/nodes/intent_router.py  # 意图路由（骨架版）
graph/conditions/route_decision.py  # 路由分发条件
services/llm.py               # LLM 工厂（百炼）
prompts/__init__.py           # Prompt 加载工具
prompts/intent_router.txt     # 路由 Prompt 模板
```

**验证方式**：`python main.py test` → 输出意图分数和路由结果。

---

## 五、操作记录

| 日期 | 操作 | 状态 |
|------|------|------|
| 2026-07-28 | 需求讨论：阅读原始方案、确定技术栈 MVP 范围 | ✅ |
| 2026-07-28 | 编写 `implementation_plan.md` 完整实现方案 | ✅ |
| 2026-07-28 | 决策确认：百炼、2 Agent、Mock、中文、无离线 | ✅ |
| 2026-07-28 | Phase 0：配置文件 + 项目骨架搭建 | ✅ |
| 2026-07-28 | pip install 依赖安装 | ✅ |
| 2026-07-28 | FastAPI 启动验证 | ✅ |
| 2026-07-28 | 写入 `progress.md` 进度日志 | ✅ |
