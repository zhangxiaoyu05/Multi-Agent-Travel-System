# 入境定制游多 Agent 系统——完整实现方案

> 基于 `langgraph_agent实现方案.md` 的原设计，结合 Python + Docker + FastAPI 技术栈，
> 按从零到完整实现的顺序，逐层展开。
>
> **已确认的技术决策（2026-07-28）：**
> - LLM：阿里百炼平台（qwen-turbo 路由 + qwen-plus 生成）
> - MVP Agent：客服 + 定制（销售、运营 Phase 6 补齐）
> - 知识库：MVP Mock 假数据（Phase 7 接真实 RAG）
> - 语言：仅中文
> - 前端：简单测试页面
> - 离线批处理：不做

---

## 目录

1. [整体架构概览](#一整体架构概览)
2. [技术栈选型](#二技术栈选型)
3. [项目文件结构](#三项目文件结构)
4. [分层架构说明](#四分层架构说明)
5. [Phase 0：项目骨架与 Docker 环境](#五phase-0项目骨架与-docker-环境)
6. [Phase 1：State 定义 + 最简图](#六phase-1state-定义--最简图)
7. [Phase 2：意图路由器](#七phase-2意图路由器)
8. [Phase 3：客服 Agent + 人工接管](#八phase-3客服-agent--人工接管)
9. [Phase 4：定制 Agent + 修订循环](#九phase-4定制-agent--修订循环)
10. [Phase 5：终态写入 + API 联调](#十phase-5终态写入--api-联调)
11. [Phase 6：销售 Agent + 运营 Agent](#十一phase-6销售-agent--运营-agent)
12. [Phase 7：RAG 增强与在线/离线流程](#十二phase-7rag-增强与在线离线流程)
13. [Phase 8：生产化](#十三phase-8生产化)
14. [待决策事项汇总](#十四待决策事项汇总)

---

## 一、整体架构概览

### 1.1 系统拓扑

```
                     ┌──────────────┐
                     │   用户/前端   │
                     │ (WhatsApp/   │
                     │  WeChat/Web) │
                     └──────┬───────┘
                            │ HTTP POST /chat
                            ▼
              ┌─────────────────────────┐
              │   FastAPI (api/main.py) │
              │   - 请求校验             │
              │   - 路由到 LangGraph    │
              └──────────┬──────────────┘
                         │
                         ▼
              ┌─────────────────────────┐
              │   LangGraph 编排引擎     │
              │   (graph/builder.py)    │
              │   - 节点串联             │
              │   - 条件路由             │
              │   - State 管理 (内存)    │
              └──────────┬──────────────┘
                         │
          ┌──────────────┼──────────────┬──────────────┐
          ▼              ▼              ▼              ▼
    ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐
    │ 客服      │  │ 销售      │  │ 运营      │  │ 定制      │
    │ Agent    │  │ Agent    │  │ Agent    │  │ Agent    │
    └────┬─────┘  └────┬─────┘  └────┬─────┘  └────┬─────┘
         │              │              │              │
         └──────────────┼──────────────┼──────────────┘
                        │              │
                        ▼              ▼
              ┌─────────────┐  ┌──────────────┐
              │  LLM 网关    │  │  Tools       │
              │ (services/  │  │  (tools/)    │
              │  llm.py)    │  │  MVP: Mock   │
              └─────────────┘  └──────────────┘
```

### 1.2 图内节点流转（MVP）

```
START
  │
  ▼
input_guard          ← 入参保护：截断、脱敏
  │
  ▼
session_context      ← 会话初始化：读取历史、初始化字段
  │
  ▼
intent_router        ← 意图识别（LLM 结构化输出）
  │
  ├─ service ──→ customer_service ──→ after_service ──→ END / human_handoff
  │
  ├─ sales ────→ (MVP 暂不做，直接返回)
  │
  ├─ operations→ (MVP 暂不做，直接返回)
  │
  └─ planner ──→ trip_planner ←──────────────────────┐
                   │                                   │
                   ▼                                   │
                 requirements_complete?                │
                   │                                   │
                   ├─ NO ──→ 返回追问 → END            │
                   │            (下一轮继续 trip_planner)│
                   │                                   │
                   ▼                                   │
                 intent_scorer                         │
                   │                                   │
                   ▼                                   │
                 revision_decision                     │
                   │                                   │
                   ├─ accept ──→ operations_sync → END │
                   ├─ revise ──→ revision_loop ────────┘
                   └─ give_up → human_handoff → END
```

### 1.3 流程说明

本项目只做**在线实时流程**——用户发消息，系统实时响应。不做离线批处理。

```
用户消息 → 意图路由 → Agent 处理 → 返回结果
```

---

## 二、技术栈选型

### 2.1 核心依赖

| 层级 | 技术 | 说明 |
|------|------|------|
| 编排引擎 | **LangGraph** ≥ 0.2 | 图结构定义、State 管理、Checkpoint |
| Agent 框架 | **LangChain** ≥ 0.3 | Agent 抽象、Tool 封装、消息管理 |
| Web 框架 | **FastAPI** ≥ 0.115 | `/chat` 接口、自动 OpenAPI 文档 |
| ASGI 服务器 | **Uvicorn** ≥ 0.30 | 生产级 ASGI，支持 `--reload` 热重载 |
| LLM SDK | **langchain-openai** | 兼容 OpenAI / DeepSeek / 通义千问 |
| 容器化 | **Docker + docker-compose** | 开发/生产环境一致 |
| Python | **3.12** | 当前稳定版 |

### 2.2 LLM 选型 ✅ 已确认

使用**阿里百炼平台**，通过 OpenAI 兼容接口调用。

| 用途 | 模型 | 说明 |
|------|------|------|
| 路由（意图识别） | `qwen-turbo` | 速度快、成本低，分类任务足够 |
| 生成（行程草案） | `qwen-plus` | 长文本生成和推理（可升级为 `qwen-max`） |

base_url: `https://dashscope.aliyuncs.com/compatible-mode/v1`

通过 `services/llm.py` 统一管理，后续如需切换模型只需改 `.env`：

```python
# services/llm.py 的接口设计
def get_router_llm() -> ChatOpenAI:
    """意图路由器用（qwen-turbo）"""
    
def get_agent_llm() -> ChatOpenAI:
    """Agent 内容生成用（qwen-plus）"""
```

### 2.3 向量数据库（RAG 相关）✅ 已确认

**MVP 阶段不引入 RAG**。客服 FAQ 使用 Mock 假数据（`tools/mock_faq.py`）回答常见问题。

真实 RAG 知识库在 **Phase 7** 引入，届时向量数据库选型：

| 方案 | 部署方式 | 适合 |
|------|---------|------|
| **Chroma** | 嵌入 Python 进程，零配置 | MVP 快速验证 |
| **Milvus Lite** | 嵌入 Python 进程 | 后期可平滑升级 Milvus Server |
| **pgvector** | PostgreSQL 扩展 | 已有 PG 的理想选择 |

> ⚠️ **后续必须补齐**：Mock FAQ → 真实向量检索 + 知识库管理

---

## 三、项目文件结构

```
D:\Multi_Agent\
│
├── .env.example                 # 环境变量模板（提交到 Git）
├── .env                         # 实际环境变量（不提交 Git）
├── .gitignore
├── .dockerignore
│
├── Dockerfile                   # 应用镜像
├── docker-compose.yml           # 本地开发编排
│
├── requirements.txt             # Python 依赖
│
├── main.py                      # 本地快速调试入口（直接跑 python main.py）
│
├── api/                         # FastAPI 层
│   ├── __init__.py
│   ├── main.py                  # FastAPI app 定义 + /chat 路由
│   └── schemas.py               # Pydantic 请求/响应模型
│
├── graph/                       # LangGraph 编排层
│   ├── __init__.py
│   ├── state.py                 # AgentState 定义（全局共享 State）
│   ├── builder.py               # build_graph() 图构建函数
│   ├── nodes/                   # 各节点实现（薄层，调 Agent）
│   │   ├── __init__.py
│   │   ├── input_guard.py
│   │   ├── session_context.py
│   │   ├── intent_router.py
│   │   ├── customer_service.py
│   │   ├── trip_planner.py
│   │   ├── intent_scorer.py
│   │   ├── revision_loop.py
│   │   ├── human_handoff.py
│   │   └── operations_sync.py
│   └── conditions/              # 条件边（路由判断逻辑）
│       ├── __init__.py
│       ├── route_decision.py    # 路由分发条件
│       ├── after_service.py     # 客服后置条件
│       ├── requirements_complete.py  # 必填项检查
│       └── revision_decision.py     # 修订决策
│
├── agents/                      # Agent 业务实现（厚层，含 LLM+Tool 编排）
│   ├── __init__.py
│   ├── base.py                  # BaseAgent 抽象类
│   ├── customer_service.py      # 客服 Agent
│   ├── trip_planner.py          # 定制 Agent
│   ├── sales_agent.py           # 销售 Agent（Phase 6）
│   └── operations_agent.py      # 运营 Agent（Phase 6）
│
├── tools/                       # LangChain Tools
│   ├── __init__.py
│   ├── base.py                  # Tool 注册中心
│   ├── mock_weather.py
│   ├── mock_calendar.py
│   ├── mock_inventory.py
│   ├── mock_faq.py
│   ├── mock_handoff.py
│   ├── mock_quote.py
│   ├── mock_crm.py
│   └── mock_capi.py
│
├── services/                    # 基础设施
│   ├── __init__.py
│   └── llm.py                   # LLM 工厂（统一管理 provider/model）
│
├── prompts/                     # System Prompt 模板
│   ├── __init__.py
│   ├── customer_service.txt
│   ├── trip_planner.txt
│   └── intent_router.txt
│
└── tests/                       # 测试
    ├── __init__.py
    ├── conftest.py              # pytest fixtures
    ├── test_state.py
    ├── test_graph.py
    ├── test_router.py
    ├── test_customer_service.py
    └── test_trip_planner.py
```

---

## 四、分层架构说明

每一层的职责和依赖关系：

```
┌─────────────────────────────────────────┐
│  api/          ← HTTP 层                │  对外暴露接口
│                 依赖: graph, schemas     │  处理请求/响应
├─────────────────────────────────────────┤
│  graph/        ← 编排层                 │  只做编排，不做业务
│    state.py    ← 数据契约               │  定义 State 结构
│    builder.py  ← 图组装                 │  定义节点和边的连接
│    nodes/      ← 薄层节点函数           │  每个节点只做三件事：
│                 依赖: agents, conditions │  ① 从 State 取数据
│    conditions/ ← 条件路由判断           │  ② 调用对应 Agent
│                                          │  ③ 把结果写回 State
├─────────────────────────────────────────┤
│  agents/       ← 业务层                 │  包含完整业务逻辑
│                 依赖: tools, services    │  编排 LLM + Tool 调用
│                                          │  不关心图结构
├─────────────────────────────────────────┤
│  tools/        ← 能力层                 │  单一职责的外部调用
│                 依赖: 外部API/数据库     │  每个 Tool 只做一件事
│                                          │  MVP 全 Mock
├─────────────────────────────────────────┤
│  services/     ← 基础设施               │  跨层共享的通用能力
│                 无业务逻辑               │  LLM 网关、缓存、DB连接
├─────────────────────────────────────────┤
│  prompts/      ← Prompt 模板            │  纯文本/模板文件
│                 无代码依赖               │  与代码分离，方便调优
└─────────────────────────────────────────┘
```

**关键原则**：上层依赖下层，下层不依赖上层。
- `graph/nodes/` 可以调 `agents/` 和 `tools/`
- `agents/` 可以调 `tools/` 和 `services/`
- `tools/` 不知道 `agents/` 的存在
- `services/` 不知道业务的存在

---

## 五、Phase 0：项目骨架与 Docker 环境

**目标**：从零搭建到 `docker-compose up` 能看到 FastAPI 的 Swagger 页面。

### 5.1 文件清单

以下是 Phase 0 需要创建的全部文件：

```
D:\Multi_Agent\
├── .env.example
├── .gitignore
├── .dockerignore
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
├── api\__init__.py
├── api\main.py
├── api\schemas.py
├── graph\__init__.py
├── agents\__init__.py
├── tools\__init__.py
├── services\__init__.py
├── prompts\__init__.py
├── tests\__init__.py
└── main.py
```

### 5.2 各文件内容

#### `.env.example`（提交到 Git）

```ini
# LLM 配置（阿里百炼）
LLM_API_KEY=sk-your-bailian-api-key
LLM_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1

# 路由模型（轻量、快速）
ROUTER_MODEL=qwen-turbo
# 生成模型（强推理）
AGENT_MODEL=qwen-plus

# 服务配置
HOST=0.0.0.0
PORT=8000
LOG_LEVEL=info
```

#### `.gitignore`

```gitignore
# Python
__pycache__/
*.py[cod]
*.egg-info/
dist/
.venv/

# 环境变量（含密钥，不提交）
.env

# IDE
.idea/
.vscode/
*.swp

# Docker
.env

# OS
.DS_Store
Thumbs.db
```

#### `.dockerignore`

```dockerignore
.git
.gitignore
.idea
.vscode
__pycache__
*.pyc
.venv
.env
README.md
*.md
tests/
```

#### `Dockerfile`

```dockerfile
FROM python:3.12-slim

WORKDIR /app

# 安装系统依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# 安装 Python 依赖（分层缓存）
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制代码
COPY . .

# 暴露端口
EXPOSE 8000

# 启动命令
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

#### `docker-compose.yml`

```yaml
version: "3.8"

services:
  app:
    build: .
    container_name: travel-agent
    ports:
      - "8000:8000"
    volumes:
      - .:/app          # 代码挂载，修改即时生效
    env_file:
      - .env
    command: uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload
    # --reload: 开发模式热重载

  # ========== 后续阶段启用 ==========
  # redis:
  #   image: redis:7-alpine
  #   container_name: travel-redis
  #   ports:
  #     - "6379:6379"
  #
  # postgres:
  #   image: pgvector/pgvector:pg16
  #   container_name: travel-db
  #   ports:
  #     - "5432:5432"
  #   environment:
  #     POSTGRES_USER: travel
  #     POSTGRES_PASSWORD: travel123
  #     POSTGRES_DB: travel_agent
  #   volumes:
  #     - pgdata:/var/lib/postgresql/data
  #
  # volumes:
  #   pgdata:
```

#### `requirements.txt`

```
# ========== LangGraph 生态 ==========
langgraph>=0.2.0
langchain>=0.3.0
langchain-openai>=0.2.0
langchain-core>=0.3.0

# ========== Web 框架 ==========
fastapi>=0.115.0
uvicorn[standard]>=0.30.0

# ========== 工具库 ==========
pydantic>=2.0
python-dotenv>=1.0
httpx>=0.27

# ========== 测试 ==========
pytest>=8.0
pytest-asyncio>=0.24.0
```

#### `api/__init__.py`

```python
# API layer
```

#### `api/schemas.py`

```python
"""Pydantic 请求/响应模型"""

from pydantic import BaseModel, Field
from typing import Optional, Literal


class ChatRequest(BaseModel):
    """POST /chat 请求体"""
    session_id: str = Field(..., description="会话唯一标识")
    customer_id: str = Field(..., description="客户唯一标识")
    channel: Literal["whatsapp", "wechat", "web", "messenger", "tiktok"] = Field(
        ..., description="消息渠道"
    )
    message: str = Field(..., min_length=1, max_length=4000, description="用户消息")
    language: str = Field(default="zh", description="语言偏好")


class TripDraftResponse(BaseModel):
    """行程草案"""
    version: int
    itinerary_md: str
    estimated_cost: Optional[str] = None
    weather_summary: Optional[str] = None


class QuoteResponse(BaseModel):
    """报价单"""
    total_per_person: Optional[str] = None
    breakdown: Optional[str] = None


class ChatResponse(BaseModel):
    """POST /chat 响应体"""
    reply: str = Field(..., description="AI 回复内容")
    current_branch: Optional[str] = Field(None, description="当前分支")
    draft: Optional[TripDraftResponse] = None
    quote: Optional[QuoteResponse] = None
    need_human: bool = Field(default=False, description="是否需要转人工")
    intent_scores: Optional[dict] = None
```

#### `api/main.py`

```python
"""FastAPI 入口"""

from fastapi import FastAPI
from dotenv import load_dotenv

# 启动时加载环境变量
load_dotenv()

app = FastAPI(
    title="入境定制游 AI Agent",
    description="基于 LangGraph 的多 Agent 旅游规划系统",
    version="0.1.0",
)


@app.get("/health")
async def health_check():
    """健康检查"""
    return {"status": "ok", "version": "0.1.0"}


# Phase 4 启用 /chat 路由
# from api.schemas import ChatRequest, ChatResponse
# @app.post("/chat", response_model=ChatResponse)
# async def chat(req: ChatRequest):
#     ...
```

#### `graph/__init__.py`、`agents/__init__.py`、`tools/__init__.py`、`services/__init__.py`、`prompts/__init__.py`、`tests/__init__.py`

```python
# 各层模块标记（Phase 0 全部为空）
```

#### `main.py`（项目根目录，本地快速调试入口）

```python
"""本地快速调试入口

直接运行: python main.py
效果等同于: uvicorn api.main:app --reload
"""

import uvicorn

if __name__ == "__main__":
    uvicorn.run(
        "api.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info",
    )
```

### 5.3 Phase 0 验证

```bash
# 方式一：Docker
docker-compose up --build
# 浏览器打开 http://localhost:8000/docs → 看到 Swagger 页面 √

# 方式二：本地（需先 pip install -r requirements.txt）
python main.py
# 浏览器打开 http://localhost:8000/docs → 看到 Swagger 页面 √

# 测试 health 接口
curl http://localhost:8000/health
# → {"status":"ok","version":"0.1.0"}
```

---

## 六、Phase 1：State 定义 + 最简图

**目标**：定义完整的 AgentState，搭建一条从用户消息到路由结果的最简图，验证 LangGraph 能正常 invoke。

### 6.1 新增/修改文件

```
graph/
├── state.py      ← 新增：AgentState 定义
├── builder.py    ← 新增：build_graph() 最简图
├── nodes/
│   ├── __init__.py          ← 新增
│   ├── input_guard.py       ← 新增
│   ├── session_context.py   ← 新增
│   └── intent_router.py     ← 新增（骨架版）
├── conditions/
│   ├── __init__.py          ← 新增
│   └── route_decision.py    ← 新增
services/
└── llm.py                   ← 新增：LLM 工厂
prompts/
├── __init__.py              ← 新增（加载 prompt 的工具函数）
└── intent_router.txt        ← 新增
```

### 6.2 `graph/state.py`——State 定义

这是整个系统的**数据契约**，所有节点共享同一个 State。继承 LangGraph 的 `MessagesState`（自带消息管理），扩展业务字段：

```python
"""AgentState——全局共享的会话状态"""

from typing import TypedDict, Annotated, Optional, Literal
from langgraph.graph.message import add_messages
from langgraph.graph import MessagesState


# ========== 嵌套结构 ==========

class TripNeed(TypedDict, total=False):
    """客户出行需求——字段逐步填充"""
    destination: str          # 目的地城市
    days: int                 # 行程天数
    arrival_date: str         # 抵达日期 YYYY-MM-DD
    pax: int                  # 人数
    budget: str               # 预算（带币种，如 "$2000"）
    theme: str                # 偏好主题（历史文化 / 自然风光 / 美食）
    pace: str                 # 节奏偏好（轻松 / 适中 / 紧凑）
    special_requests: str     # 特殊需求（轮椅、儿童座椅等）


class TripDraft(TypedDict, total=False):
    """行程草案"""
    version: int              # 版本号（每次修订 +1）
    itinerary_md: str         # Markdown 格式行程
    estimated_cost: str       # 预估人均费用
    weather_summary: str      # 天气摘要


# ========== 主 State ==========

class AgentState(MessagesState):
    """
    全局共享 State。
    继承 MessagesState → 自带 messages 字段和 add_messages reducer。
    """

    # ---- 渠道与会话 ----
    session_id: str
    customer_id: str
    channel: str              # whatsapp / wechat / web / messenger / tiktok
    language: str             # zh / en / ja / ko

    # ---- 路由 ----
    current_branch: str       # service / sales / operations / planner
    intent_scores: dict       # {"service": 0.1, "sales": 0.05, ...}

    # ---- 业务数据 ----
    need: TripNeed            # 客户出行需求
    draft: TripDraft          # 行程草案
    revision_count: int       # 修订次数，硬上限 3
    intent_level: str         # high / mid / low

    # ---- 控制 ----
    need_human: bool          # 是否需要转人工
    next_action: str          # revise / accept / give_up

    # ---- 输出 ----
    final_reply: str          # 最终回复文本
    quote: str                # 报价单文本
```

### 6.3 `services/llm.py`——LLM 工厂

统一管理 LLM 实例创建，通过环境变量切换 provider：

```python
"""LLM 工厂——阿里百炼平台"""

import os
from langchain_openai import ChatOpenAI

# 百炼兼容 OpenAI SDK
BAILIAN_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"


def get_router_llm() -> ChatOpenAI:
    """意图路由器用轻量模型（qwen-turbo：快速、低成本）
    
    环境变量：
        ROUTER_MODEL: 模型名（默认 qwen-turbo）
        LLM_API_KEY: 百炼 API Key
        LLM_BASE_URL: base_url（默认百炼地址）
    """
    return ChatOpenAI(
        model=os.getenv("ROUTER_MODEL", "qwen-turbo"),
        api_key=os.getenv("LLM_API_KEY", "sk-placeholder"),
        base_url=os.getenv("LLM_BASE_URL", BAILIAN_BASE_URL),
        temperature=0.3,       # 路由需要确定性
        max_tokens=512,        # 路由输出短，节省成本
    )


def get_agent_llm() -> ChatOpenAI:
    """Agent 内容生成用强模型（qwen-plus：长文本、强推理）
    
    环境变量：
        AGENT_MODEL: 模型名（默认 qwen-plus）
    """
    return ChatOpenAI(
        model=os.getenv("AGENT_MODEL", "qwen-plus"),
        api_key=os.getenv("LLM_API_KEY", "sk-placeholder"),
        base_url=os.getenv("LLM_BASE_URL", BAILIAN_BASE_URL),
        temperature=0.7,       # 生成需要多样性
        max_tokens=4096,       # 行程生成较长
    )
```

### 6.4 `prompts/__init__.py`——Prompt 加载工具

```python
"""Prompt 模板加载工具"""

import os

_PROMPT_DIR = os.path.dirname(__file__)


def load_prompt(name: str) -> str:
    """加载 prompts/ 目录下的 .txt 模板文件"""
    path = os.path.join(_PROMPT_DIR, name)
    with open(path, "r", encoding="utf-8") as f:
        return f.read().strip()
```

### 6.5 `prompts/intent_router.txt`——路由 Prompt

```
你是入境定制游平台的智能路由助手。

分析用户消息，输出 JSON 格式的意图分类结果。

## 四类意图

1. **service（客服）**：FAQ 咨询、订单查询、退改政策、签证须知、投诉
2. **sales（销售）**：产品询价、购买意向、签约、支付问题
3. **operations（运营）**：商家入驻、订单履约、售后工单、平台规则
4. **planner（定制）**：行程规划、目的地推荐、天数/预算咨询、景点安排

## 输出格式

请严格输出以下 JSON：
{
  "service": 0.0-1.0 之间的概率,
  "sales": 0.0-1.0 之间的概率,
  "operations": 0.0-1.0 之间的概率,
  "planner": 0.0-1.0 之间的概率,
  "need_human": true/false,
  "reasoning": "简短原因"
}

## 转人工判断

用户消息含以下关键词时 need_human 设为 true：
投诉、退款、差评、人工、真人
```

### 6.6 各节点实现（Phase 1——骨架版）

#### `graph/nodes/input_guard.py`

```python
"""入参保护：消息长度截断 + 基础清洗"""

from graph.state import AgentState


def input_guard(state: AgentState) -> dict:
    """截断过长消息，做基础脱敏"""
    messages = state.get("messages", [])
    if not messages:
        return {}

    last_msg = messages[-1]
    content = last_msg.content if hasattr(last_msg, "content") else str(last_msg)

    # 长度截断
    if len(content) > 4000:
        content = content[:4000] + "..."

    # 简单 PII 脱敏：手机号
    import re
    content = re.sub(r'\b1[3-9]\d{9}\b', '[PHONE]', content)

    # 更新最后一条消息
    last_msg.content = content

    return {"messages": messages}
```

#### `graph/nodes/session_context.py`

```python
"""会话初始化：设置默认值，读取历史（Phase 1 简化版）"""

from graph.state import AgentState


def session_context(state: AgentState) -> dict:
    """初始化会话级默认值"""
    return {
        "language": state.get("language", "zh"),
        "need_human": False,
        "revision_count": state.get("revision_count", 0),
        "draft": state.get("draft", {}),
        "need": state.get("need", {}),
    }
```

#### `graph/nodes/intent_router.py`（骨架版）

```python
"""意图路由器——调用 LLM 做四分类"""

import json
from langchain_core.messages import HumanMessage
from graph.state import AgentState
from services.llm import get_router_llm
from prompts import load_prompt


def intent_router(state: AgentState) -> dict:
    """分析用户消息，输出意图分数"""
    messages = state.get("messages", [])
    if not messages:
        return {"current_branch": "service", "intent_scores": {}, "final_reply": "请发送消息"}

    last_msg = messages[-1]
    user_text = last_msg.content if hasattr(last_msg, "content") else str(last_msg)

    llm = get_router_llm()
    system_prompt = load_prompt("intent_router.txt")

    response = llm.invoke([
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_text},
    ])

    # 解析 LLM 输出的 JSON
    try:
        result = json.loads(response.content)
    except json.JSONDecodeError:
        # 解析失败默认进客服
        result = {
            "service": 1.0, "sales": 0.0, "operations": 0.0, "planner": 0.0,
            "need_human": False, "reasoning": "parse error"
        }

    return {
        "intent_scores": {
            "service": result.get("service", 0),
            "sales": result.get("sales", 0),
            "operations": result.get("operations", 0),
            "planner": result.get("planner", 0),
        },
        "current_branch": "",  # 由条件边设置
        "need_human": result.get("need_human", False),
    }
```

### 6.7 `graph/conditions/route_decision.py`

```python
"""路由决策：根据意图分数选择分支"""

from graph.state import AgentState


def route_decision(state: AgentState) -> str:
    """
    返回目标节点名称。
    
    优先级：
    1. need_human → human_handoff
    2. 最高分意图 → 对应 Agent
    3. 所有分数 < 0.3 → customer_service（兜底）
    """
    if state.get("need_human"):
        return "human_handoff"

    scores = state.get("intent_scores", {})
    if not scores:
        return "customer_service"

    max_branch = max(scores, key=scores.get)
    max_score = scores[max_branch]

    if max_score < 0.3:
        return "customer_service"

    branch_map = {
        "service": "customer_service",
        "sales": "customer_service",      # MVP 暂不启用 sales
        "operations": "customer_service",  # MVP 暂不启用 operations
        "planner": "trip_planner",
    }
    return branch_map.get(max_branch, "customer_service")
```

### 6.8 `graph/builder.py`——图构建

```python
"""LangGraph 图构建"""

from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver

from graph.state import AgentState
from graph.nodes.input_guard import input_guard
from graph.nodes.session_context import session_context
from graph.nodes.intent_router import intent_router
from graph.conditions.route_decision import route_decision


def build_graph():
    """构建并编译图"""
    builder = StateGraph(AgentState)

    # ---- 注册节点 ----
    builder.add_node("input_guard", input_guard)
    builder.add_node("session_context", session_context)
    builder.add_node("intent_router", intent_router)

    # 占位节点（Phase 3-4 替换为真实实现）
    builder.add_node("customer_service", lambda s: {"final_reply": "[客服] 功能开发中"})
    builder.add_node("trip_planner", lambda s: {"final_reply": "[定制] 功能开发中"})
    builder.add_node("human_handoff", lambda s: {"final_reply": "正在为您转接人工客服...", "need_human": True})

    # ---- 边 ----
    builder.add_edge(START, "input_guard")
    builder.add_edge("input_guard", "session_context")
    builder.add_edge("session_context", "intent_router")

    # 条件边：路由分发
    builder.add_conditional_edges(
        "intent_router",
        route_decision,
        {
            "customer_service": "customer_service",
            "trip_planner": "trip_planner",
            "human_handoff": "human_handoff",
        }
    )

    # 终端节点 → END
    builder.add_edge("customer_service", END)
    builder.add_edge("trip_planner", END)
    builder.add_edge("human_handoff", END)

    # 编译（开发期用内存 checkpoint）
    memory = MemorySaver()
    return builder.compile(checkpointer=memory)
```

### 6.9 Phase 1 验证

更新 `main.py` 增加快速测试：

```python
"""本地快速调试入口"""

import uvicorn
import sys


def test_graph():
    """命令行快速测试图"""
    from graph.builder import build_graph

    graph = build_graph()

    # 测试用例
    result = graph.invoke(
        {"messages": [{"role": "user", "content": "我想去西安玩3天"}],
         "session_id": "test-001",
         "customer_id": "cust-001",
         "channel": "web",
         "language": "zh",
        },
        config={"configurable": {"thread_id": "test-001"}},
    )

    print("=== 路由结果 ===")
    print(f"意图分数: {result.get('intent_scores')}")
    print(f"目标分支: {result.get('current_branch')}")
    print(f"回复: {result.get('final_reply')}")
    print(f"转人工: {result.get('need_human')}")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "test":
        test_graph()
    else:
        uvicorn.run("api.main:app", host="0.0.0.0", port=8000, reload=True)
```

```bash
# 测试
python main.py test

# 期望输出：
# 意图分数: {'service': 0.1, 'sales': 0.05, 'operations': 0.05, 'planner': 0.8}
# 目标分支: planner
# 回复: [定制] 功能开发中
# 转人工: False
```

---

## 七、Phase 2：意图路由器完善

**目标**：把意图路由器的 LLM 结构化输出做稳定，改掉骨架版中的 `json.loads` 裸解析，改用 LangChain 的 `with_structured_output`。

### 7.1 修改 `graph/nodes/intent_router.py`

```python
"""意图路由器——使用 LangChain 结构化输出"""

from pydantic import BaseModel, Field
from langchain_core.messages import HumanMessage
from graph.state import AgentState
from services.llm import get_router_llm
from prompts import load_prompt


class IntentResult(BaseModel):
    """LLM 结构化输出 Schema"""
    service: float = Field(default=0.0, ge=0.0, le=1.0, description="客服意图概率")
    sales: float = Field(default=0.0, ge=0.0, le=1.0, description="销售意图概率")
    operations: float = Field(default=0.0, ge=0.0, le=1.0, description="运营意图概率")
    planner: float = Field(default=0.0, ge=0.0, le=1.0, description="定制意图概率")
    need_human: bool = Field(default=False, description="是否需要转人工")
    reasoning: str = Field(default="", description="判断依据")


def intent_router(state: AgentState) -> dict:
    """分析用户消息，输出意图分数"""
    messages = state.get("messages", [])
    if not messages:
        return {"current_branch": "service", "final_reply": "请发送消息"}

    last_msg = messages[-1]
    user_text = last_msg.content if hasattr(last_msg, "content") else str(last_msg)

    llm = get_router_llm()
    structured_llm = llm.with_structured_output(IntentResult)
    system_prompt = load_prompt("intent_router.txt")

    try:
        result: IntentResult = structured_llm.invoke([
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_text},
        ])
    except Exception:
        # LLM 调用失败，默认进客服
        result = IntentResult(service=1.0, need_human=False, reasoning="llm error")

    return {
        "intent_scores": {
            "service": result.service,
            "sales": result.sales,
            "operations": result.operations,
            "planner": result.planner,
        },
        "need_human": result.need_human,
    }
```

### 7.2 Phase 2 验证

```bash
python main.py test

# 多种测试输入：
# "你好"              → service 高分
# "我要定制西安行程"    → planner 高分
# "我要投诉你们"       → need_human=True
# "这个多少钱"         → sales 高分
```

---

## 八、Phase 3：客服 Agent + 人工接管

**目标**：实现完整的客服分支，包括 FAQ 检索、转人工判断、条件边流转。

### 8.1 新增/修改文件

```
tools/
├── mock_faq.py        ← 新增
├── mock_handoff.py    ← 新增
agents/
├── base.py            ← 新增：Agent 基类
├── customer_service.py ← 新增
graph/nodes/
├── customer_service.py ← 重写（不再用占位 lambda）
├── human_handoff.py    ← 重写（生成交接摘要）
graph/conditions/
├── after_service.py    ← 新增
prompts/
├── customer_service.txt ← 新增
```

### 8.2 `agents/base.py`——Agent 基类

```python
"""Agent 基类——统一 LLM + Tools 的调用模式"""

from abc import ABC, abstractmethod
from langchain_openai import ChatOpenAI
from graph.state import AgentState


class BaseAgent(ABC):
    """所有业务 Agent 的基类"""

    def __init__(self, llm: ChatOpenAI, tools: list, system_prompt: str):
        self.llm = llm
        self.tools = tools
        self.system_prompt = system_prompt

    @abstractmethod
    def run(self, state: AgentState) -> dict:
        """执行 Agent 逻辑，返回要合并到 State 的 dict"""
        ...

    def _get_user_message(self, state: AgentState) -> str:
        """提取最后一条用户消息"""
        messages = state.get("messages", [])
        if not messages:
            return ""
        last = messages[-1]
        return last.content if hasattr(last, "content") else str(last)
```

### 8.3 `agents/customer_service.py`——客服 Agent

```python
"""客服 Agent——FAQ 答疑 + 转人工判断"""

from agents.base import BaseAgent
from graph.state import AgentState
from tools.mock_faq import search_faq
from tools.mock_handoff import check_handoff


class CustomerServiceAgent(BaseAgent):

    def run(self, state: AgentState) -> dict:
        user_msg = self._get_user_message(state)

        # Step 1: 先用 LLM 判断是否需要查 FAQ
        llm_with_tools = self.llm.bind_tools(self.tools)

        response = llm_with_tools.invoke([
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": user_msg},
        ])

        # Step 2: 处理 Tool 调用
        need_human = False
        faq_result = ""

        # LangChain 的 tool_calls 会自动出现在 AIMessage 中
        if hasattr(response, "tool_calls") and response.tool_calls:
            for tc in response.tool_calls:
                if tc["name"] == "check_handoff":
                    result = check_handoff.invoke(tc["args"])
                    if "需要转人工" in str(result):
                        need_human = True
                elif tc["name"] == "search_faq":
                    faq_result = search_faq.invoke(tc["args"])

        # Step 3: 如果调了 FAQ，把结果回传给 LLM 生成最终回复
        if faq_result:
            final = self.llm.invoke([
                {"role": "system", "content": self.system_prompt},
                {"role": "user", "content": user_msg},
                {"role": "assistant", "content": None, "tool_calls": response.tool_calls},
                {"role": "tool", "content": str(faq_result)},
            ])
            return {"final_reply": final.content, "need_human": need_human}

        return {
            "final_reply": response.content,
            "need_human": need_human,
        }
```

### 8.4 `prompts/customer_service.txt`

```
你是入境定制游平台的中文客服助手。

## 你的职责
1. 回答 FAQ 问题（签证、支付、退改政策、天气等）
2. 查询订单状态
3. 识别需要转人工的情况（投诉、多次无法解决、签证复杂问题）

## 工作流程
- 简单问题：直接回复
- 需要查资料：调用 search_faq 工具
- 投诉/退款/签证复杂问题：调用 check_handoff 工具评估

## 风格要求
- 礼貌、专业、简洁
- 如果用户问题超出能力范围，主动建议转人工
```

### 8.5 `tools/mock_faq.py`

```python
"""Mock FAQ 检索工具"""

from langchain.tools import tool


@tool
def search_faq(query: str) -> str:
    """搜索 FAQ 知识库。输入用户问题，返回匹配的答案。"""
    faq_db = {
        "签证": "中国对部分国家实行 144 小时过境免签政策。日本、新加坡、文莱公民可享受 15 天免签。入境时需出示有效的返程机票和酒店预订。具体请查阅中国驻当地使领馆最新公告。",
        "支付": "支持微信支付（WeChat Pay）、支付宝（Alipay）以及 Visa/Mastercard 信用卡。建议提前绑定银行卡到微信或支付宝以获得最佳体验。",
        "退改": "出发前 7 天以上取消：全额退款。出发前 3-7 天取消：收取 50% 费用。出发前 3 天内取消：收取 100% 费用。修改行程不收取手续费，但差价需补足。",
        "天气": "中国地域辽阔，各地气候差异大。北京夏季 25-35°C，冬季 -10-5°C。西安夏季 25-38°C。上海夏季 25-35°C，潮湿。建议出发前查询目的地具体天气。",
    }

    query_lower = query.lower()
    for key, answer in faq_db.items():
        if key.lower() in query_lower:
            return answer

    return "您的问题已记录，如需详细解答请转人工客服。常见问题包括：签证政策、支付方式、退改规则、天气查询等。"
```

### 8.6 `tools/mock_handoff.py`

```python
"""Mock 转人工评估工具"""

from langchain.tools import tool


@tool
def check_handoff(message: str) -> str:
    """评估是否需要转人工客服。根据关键词和复杂度判断。"""
    keywords = ["投诉", "退款", "差评", "人工", "真人", "我要投诉"]

    if any(kw in message for kw in keywords):
        return "需要转人工：检测到投诉/退款类关键词，建议立即转接人工客服处理"

    if len(message) > 500:
        return "需要转人工：消息过长，可能包含复杂诉求，建议人工跟进"

    return "无需转人工：当前问题可由 AI 客服处理"
```

### 8.7 `graph/conditions/after_service.py`

```python
"""客服后置条件：判断下一步走向"""

from graph.state import AgentState


def after_service(state: AgentState) -> str:
    """
    客服节点出口条件：
    - need_human → human_handoff
    - 有 final_reply → END
    - 其他 → intent_router（重新分类）
    """
    if state.get("need_human"):
        return "human_handoff"
    if state.get("final_reply"):
        return "end"
    return "intent_router"
```

### 8.8 `graph/nodes/human_handoff.py`——人工接管节点

```python
"""人工接管——生成交接摘要"""

from graph.state import AgentState


def human_handoff(state: AgentState) -> dict:
    """生成转人工交接摘要"""
    summary_parts = [
        "📋 **转人工交接单**",
        "",
        f"- **客户 ID**：{state.get('customer_id', 'N/A')}",
        f"- **来源渠道**：{state.get('channel', 'N/A')}",
        f"- **当前分支**：{state.get('current_branch', 'N/A')}",
        f"- **语言**：{state.get('language', 'zh')}",
        "",
        "**需求画像**：",
    ]

    need = state.get("need", {})
    if need:
        summary_parts.append(f"  - 目的地：{need.get('destination', '未指定')}")
        summary_parts.append(f"  - 天数：{need.get('days', '未指定')}")
        summary_parts.append(f"  - 日期：{need.get('arrival_date', '未指定')}")
        summary_parts.append(f"  - 人数：{need.get('pax', '未指定')}")
        summary_parts.append(f"  - 预算：{need.get('budget', '未指定')}")

    draft = state.get("draft", {})
    if draft:
        summary_parts.append(f"\n- **草案版本**：v{draft.get('version', 0)}")
        summary_parts.append(f"- **修订次数**：{state.get('revision_count', 0)}")

    summary_parts.append(f"\n- **意向等级**：{state.get('intent_level', '未评估')}")

    messages = state.get("messages", [])
    if messages:
        last = messages[-1]
        last_text = last.content if hasattr(last, "content") else str(last)
        summary_parts.append(f"\n**最后消息**：{last_text[:200]}")

    return {
        "final_reply": "\n".join(summary_parts),
        "need_human": True,
    }
```

### 8.9 更新 `graph/builder.py`

把占位节点替换为真实实现：

```python
# 替换原来的 lambda
from graph.nodes.customer_service import customer_service as cs_node
from graph.nodes.human_handoff import human_handoff as hh_node
from graph.conditions.after_service import after_service

builder.add_node("customer_service", cs_node)
builder.add_node("human_handoff", hh_node)

# 客服节点改为条件边
builder.add_conditional_edges(
    "customer_service",
    after_service,
    {
        "human_handoff": "human_handoff",
        "intent_router": "intent_router",
        "end": END,
    }
)
```

---

## 九、Phase 4：定制 Agent + 修订循环

**目标**：实现最复杂的分支——需求采集 → 必填项检查 → Tool 调用 → 草案生成 → 意向评分 → 修订决策。

这是整个系统的核心。

### 9.1 新增/修改文件

```
agents/
└── trip_planner.py              ← 新增
tools/
├── mock_weather.py              ← 新增
├── mock_calendar.py             ← 新增
├── mock_inventory.py            ← 新增
graph/nodes/
├── trip_planner.py              ← 新增
├── intent_scorer.py             ← 新增
├── revision_loop.py             ← 新增
graph/conditions/
├── requirements_complete.py     ← 新增
├── revision_decision.py         ← 新增
prompts/
├── trip_planner.txt             ← 新增
```

### 9.2 `agents/trip_planner.py`——定制 Agent

```python
"""定制 Agent——需求采集 + 行程生成"""

from agents.base import BaseAgent
from graph.state import AgentState
from tools.mock_weather import get_weather
from tools.mock_calendar import query_calendar
from tools.mock_inventory import query_inventory


REQUIRED_FIELDS = ["destination", "days", "arrival_date", "pax", "budget"]


class TripPlannerAgent(BaseAgent):

    def run(self, state: AgentState) -> dict:
        user_msg = self._get_user_message(state)
        need = state.get("need", {})

        # ====== Step 1: 提取需求字段 ======
        extracted = self._extract_fields(user_msg, need)
        merged_need = {**need, **extracted}

        # ====== Step 2: 检查必填项 ======
        missing = [f for f in REQUIRED_FIELDS if f not in merged_need or not merged_need[f]]

        if missing:
            return self._ask_missing_fields(missing, merged_need)

        # ====== Step 3: 必填项齐全 → 调 Tools ======
        weather = get_weather.invoke({
            "city": merged_need["destination"],
            "date": merged_need["arrival_date"],
        })

        calendar = query_calendar.invoke({
            "date": merged_need["arrival_date"],
        })

        inventory = query_inventory.invoke({
            "city": merged_need["destination"],
            "date": merged_need["arrival_date"],
            "pax": merged_need["pax"],
        })

        # ====== Step 4: LLM 生成行程草案 ======
        revision_count = state.get("revision_count", 0)
        revision_note = ""
        if revision_count > 0:
            revision_note = f"\n这是第 {revision_count} 次修订。请根据用户反馈调整行程：{user_msg}"

        prompt = f"""
客户需求：
- 目的地：{merged_need['destination']}
- 天数：{merged_need['days']} 天
- 抵达日期：{merged_need['arrival_date']}
- 人数：{merged_need['pax']} 人
- 预算：{merged_need['budget']}
- 偏好主题：{merged_need.get('theme', '经典必游')}
- 节奏偏好：{merged_need.get('pace', '适中')}
- 特殊需求：{merged_need.get('special_requests', '无')}

天气信息：{weather}
日期信息：{calendar}
库存信息：{inventory}
{revision_note}

请生成详细的行程草案。
"""

        response = self.llm.invoke([
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": prompt},
        ])

        draft_version = state.get("draft", {}).get("version", 0) + 1

        return {
            "need": merged_need,
            "draft": {
                "version": draft_version,
                "itinerary_md": response.content,
                "weather_summary": str(weather),
            },
            "final_reply": response.content,
        }

    def _extract_fields(self, user_msg: str, existing_need: dict) -> dict:
        """用 LLM 从用户消息中提取需求字段"""
        llm_with_structure = self.llm.with_structured_output(
            type("NeedExtract", (), {
                "__annotations__": {
                    "destination": "str | None",
                    "days": "int | None",
                    "arrival_date": "str | None",
                    "pax": "int | None",
                    "budget": "str | None",
                    "theme": "str | None",
                    "pace": "str | None",
                    "special_requests": "str | None",
                }
            })
        )

        try:
            result = llm_with_structure.invoke([
                {"role": "system", "content": "从用户消息中提取旅行需求字段。只提取用户明确提到的信息，不要猜测。字段值为 null 表示未提及。"},
                {"role": "user", "content": f"已收集的需求：{existing_need}\n\n用户消息：{user_msg}"},
            ])
            return {k: v for k, v in result.dict().items() if v is not None}
        except Exception:
            return {}

    def _ask_missing_fields(self, missing: list, need: dict) -> dict:
        """生成追问消息"""
        field_names = {
            "destination": "目的地城市",
            "days": "行程天数",
            "arrival_date": "抵达日期",
            "pax": "出行人数",
            "budget": "预算范围",
        }
        missing_cn = [field_names.get(f, f) for f in missing]

        reply = f"好的，还需要确认以下信息：\n\n"
        for i, field in enumerate(missing_cn, 1):
            reply += f"{i}. **{field}**\n"
        reply += "\n请告诉我这些信息，我就能为您生成专属行程 ✨"

        return {
            "need": need,
            "final_reply": reply,
        }
```

### 9.3 `prompts/trip_planner.txt`

```
你是入境定制游平台的行程规划专家。

## 核心职责
根据客户需求（目的地、天数、日期、人数、预算等），结合天气、节假日、库存情况，
生成一份可执行的详细行程草案。

## 生成约束
1. 调用天气工具后，避开极端天气日安排户外活动
2. 每天景点间交通时间不超过 2.5 小时
3. 优先推荐库存充足且评分高的景点/酒店
4. 行程包含：每日时间线、景点介绍、餐饮推荐、交通方式、预估费用

## 输出格式
请使用 Markdown 格式输出：
- # 行程总览
- ## Day 1, Day 2, ...
- ### 预估费用明细
- 每天结束后标注 💡 小贴士

## 风格
- 热情、专业、有当地感
- 用 emoji 增加可读性（但不过多）
- 如果检测到客户已有多轮修订，在生成时主动说明"已根据您的反馈调整了...的行程"
```

### 9.4 Mock Tools

#### `tools/mock_weather.py`

```python
from langchain.tools import tool

@tool
def get_weather(city: str, date: str) -> str:
    """查询指定城市和日期的天气。输入 city: 城市名, date: 日期 YYYY-MM-DD"""
    return f"""
{city} {date} 天气：
☀️ 晴转多云
🌡️ 温度：22°C ~ 28°C
🌧️ 降水概率：15%
🍃 风力：微风 2-3 级
✅ 适合出行指数：优秀
"""
```

#### `tools/mock_calendar.py`

```python
from langchain.tools import tool

@tool
def query_calendar(date: str) -> str:
    """查询指定日期是否为节假日。输入 date: 日期 YYYY-MM-DD"""
    return f"""
📅 {date} 是周一（工作日）
🎌 非中国法定节假日
👥 景点预计人流量：中等偏低
⏰ 建议游览时间：全天均可
"""
```

#### `tools/mock_inventory.py`

```python
from langchain.tools import tool

@tool
def query_inventory(city: str, date: str, pax: int) -> str:
    """查询酒店、门票、车辆库存。输入 city, date, pax"""
    return f"""
{city} {date} 库存（{pax}人）：
🏨 酒店：市中心四星可选，约 $80/间/晚，可订
🎫 门票：主要景点均可预约
🚗 车辆：7 座商务车可用，约 $120/天含司机
📊 整体可用率：95%
"""
```

### 9.5 条件边

#### `graph/conditions/requirements_complete.py`

```python
from graph.state import AgentState

REQUIRED_FIELDS = ["destination", "days", "arrival_date", "pax", "budget"]


def requirements_complete(state: AgentState) -> str:
    """检查必填项是否齐全 + 行程是否已生成"""
    need = state.get("need", {})
    draft = state.get("draft", {})

    all_filled = all(
        field in need and need[field] is not None
        for field in REQUIRED_FIELDS
    )
    has_itinerary = bool(draft.get("itinerary_md"))

    if all_filled and has_itinerary:
        return "intent_scorer"
    return "trip_planner"
```

#### `graph/conditions/revision_decision.py`

```python
from graph.state import AgentState


def revision_decision(state: AgentState) -> str:
    """根据意向和修订次数决定下一步"""
    intent = state.get("intent_level", "low")
    action = state.get("next_action", "accept")
    count = state.get("revision_count", 0)

    if intent == "high" or action == "accept":
        return "end"
    elif action == "revise" and count < 3:
        return "revision_loop"
    else:
        return "human_handoff"
```

### 9.6 辅助节点

#### `graph/nodes/intent_scorer.py`

```python
"""意向评分——评估用户对草案的反馈"""

from pydantic import BaseModel, Field
from graph.state import AgentState
from services.llm import get_router_llm


class ScorerResult(BaseModel):
    intent_level: str = Field(description="high / mid / low")
    next_action: str = Field(description="revise / accept / give_up")
    reasoning: str = Field(default="")


def intent_scorer(state: AgentState) -> dict:
    """根据用户最新反馈和草案，评估意向等级"""
    messages = state.get("messages", [])
    user_feedback = ""
    if messages:
        last = messages[-1]
        user_feedback = last.content if hasattr(last, "content") else str(last)

    draft = state.get("draft", {})
    revision_count = state.get("revision_count", 0)

    llm = get_router_llm()
    structured_llm = llm.with_structured_output(ScorerResult)

    try:
        result = structured_llm.invoke([
            {"role": "system", "content": f"""
分析客户对行程草案的反馈。
- 客户满意/要求签约 → high + accept
- 客户要求小改动 → mid + revise（注意修订次数已达 {revision_count}/3）
- 客户不满意/放弃 → low + give_up

关键词参考：
- high: 很好/可以/签约/支付/预订/不错/满意
- mid: 改一下/加一个/换一个/调整/能不能
- low: 算了/不要了/太贵/取消/放弃
"""},
            {"role": "user", "content": f"草案：{draft.get('itinerary_md', '')[:500]}\n\n用户反馈：{user_feedback}"},
        ])
        return {
            "intent_level": result.intent_level,
            "next_action": result.next_action,
        }
    except Exception:
        return {"intent_level": "mid", "next_action": "accept"}
```

#### `graph/nodes/revision_loop.py`

```python
"""修订计数器"""

from graph.state import AgentState


def revision_loop(state: AgentState) -> dict:
    """revision_count +1，然后回到 trip_planner 重新生成"""
    return {"revision_count": state.get("revision_count", 0) + 1}
```

### 9.7 更新 `graph/builder.py`（完整版）

```python
"""LangGraph 图构建——Phase 4 完整版"""

from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver

from graph.state import AgentState

# Nodes
from graph.nodes.input_guard import input_guard
from graph.nodes.session_context import session_context
from graph.nodes.intent_router import intent_router
from graph.nodes.customer_service import customer_service
from graph.nodes.trip_planner import trip_planner
from graph.nodes.intent_scorer import intent_scorer
from graph.nodes.revision_loop import revision_loop
from graph.nodes.human_handoff import human_handoff

# Conditions
from graph.conditions.route_decision import route_decision
from graph.conditions.after_service import after_service
from graph.conditions.requirements_complete import requirements_complete
from graph.conditions.revision_decision import revision_decision


def build_graph():
    builder = StateGraph(AgentState)

    # ====== 注册节点 ======
    builder.add_node("input_guard", input_guard)
    builder.add_node("session_context", session_context)
    builder.add_node("intent_router", intent_router)
    builder.add_node("customer_service", customer_service)
    builder.add_node("trip_planner", trip_planner)
    builder.add_node("intent_scorer", intent_scorer)
    builder.add_node("revision_loop", revision_loop)
    builder.add_node("human_handoff", human_handoff)

    # ====== 边 ======

    # 主干线
    builder.add_edge(START, "input_guard")
    builder.add_edge("input_guard", "session_context")
    builder.add_edge("session_context", "intent_router")

    # 路由分发
    builder.add_conditional_edges(
        "intent_router",
        route_decision,
        {
            "customer_service": "customer_service",
            "trip_planner": "trip_planner",
            "human_handoff": "human_handoff",
        }
    )

    # 客服分支
    builder.add_conditional_edges(
        "customer_service",
        after_service,
        {
            "human_handoff": "human_handoff",
            "intent_router": "intent_router",
            "end": END,
        }
    )

    # 定制分支：必填项检查
    builder.add_conditional_edges(
        "trip_planner",
        requirements_complete,
        {
            "trip_planner": "trip_planner",   # 回去继续追问
            "intent_scorer": "intent_scorer",  # 齐全 → 评分
        }
    )

    # 定制分支：修订决策
    builder.add_conditional_edges(
        "intent_scorer",
        revision_decision,
        {
            "end": END,
            "revision_loop": "revision_loop",
            "human_handoff": "human_handoff",
        }
    )

    # 修订循环回到定制
    builder.add_edge("revision_loop", "trip_planner")

    # 人工接管 → END
    builder.add_edge("human_handoff", END)

    # 编译
    memory = MemorySaver()
    return builder.compile(checkpointer=memory)
```

### 9.8 Phase 4 验证

更新 `main.py` 的 test 函数进行端到端测试：

```python
def test_graph():
    from graph.builder import build_graph
    graph = build_graph()

    # 测试 1：定制流程——首次问询
    print("=== 测试 1：首次定制问询 ===")
    result = graph.invoke(
        {
            "messages": [{"role": "user", "content": "我想去西安玩3天，7月30号到，2个人，预算2000美元"}],
            "session_id": "t1", "customer_id": "c1",
            "channel": "web", "language": "zh",
        },
        config={"configurable": {"thread_id": "t1"}},
    )
    print(f"回复: {result.get('final_reply', '')[:300]}...")
    print(f"Draft version: {result.get('draft', {}).get('version')}")
    print(f"Need: {result.get('need')}")

    # 测试 2：同一会话修订
    print("\n=== 测试 2：修订请求 ===")
    result2 = graph.invoke(
        {
            "messages": [{"role": "user", "content": "能否加一些美食推荐？"}],
        },
        config={"configurable": {"thread_id": "t1"}},  # 相同 thread_id
    )
    print(f"回复: {result2.get('final_reply', '')[:300]}...")
    print(f"Draft version: {result2.get('draft', {}).get('version')}")
    print(f"Revision count: {result2.get('revision_count')}")

    # 测试 3：客服流程
    print("\n=== 测试 3：客服问询 ===")
    result3 = graph.invoke(
        {
            "messages": [{"role": "user", "content": "签证需要什么材料？"}],
            "session_id": "t3", "customer_id": "c3",
            "channel": "web", "language": "zh",
        },
        config={"configurable": {"thread_id": "t3"}},
    )
    print(f"回复: {result3.get('final_reply', '')[:300]}...")
    print(f"转人工: {result3.get('need_human')}")
```

---

## 十、Phase 5：终态写入 + API 联调

**目标**：补上 `operations_sync` 节点，打通 `/chat` 接口，完整联调。

### 10.1 新增/修改

```
graph/nodes/
└── operations_sync.py    ← 新增
api/
└── main.py               ← 重写（启用 /chat）
```

#### `graph/nodes/operations_sync.py`

```python
"""终态数据写入节点"""

from graph.state import AgentState
from tools.mock_crm import update_crm
from tools.mock_capi import send_capi


def operations_sync(state: AgentState) -> dict:
    """会话终态——写 CRM + 发 CAPI 事件"""
    customer_id = state.get("customer_id", "unknown")

    # Mock CRM 写入
    crm_result = update_crm.invoke({
        "customer_id": customer_id,
        "session_data": str({
            "branch": state.get("current_branch"),
            "intent_level": state.get("intent_level"),
            "revision_count": state.get("revision_count"),
            "need": state.get("need"),
        }),
    })

    # Mock CAPI 事件
    capi_result = send_capi.invoke({
        "event_type": "session_completed",
        "event_data": str({"customer_id": customer_id}),
    })

    return {
        "final_reply": state.get("final_reply", ""),
    }
```

更新 builder.py，在 `end` 分支加上 `operations_sync`：

```python
# 替换 builder.add_edge("human_handoff", END)
# 和 intent_scorer 的 end 分支

builder.add_node("operations_sync", operations_sync)

# human_handoff → operations_sync → END
builder.add_edge("human_handoff", "operations_sync")
builder.add_edge("operations_sync", END)

# intent_scorer end 分支改为 operations_sync
# 修改 revision_decision 返回：
# "accept/high" → "operations_sync"
# "give_up/超限" → "human_handoff"（human_handoff 会接到 operations_sync）
```

#### `api/main.py`——完整版

```python
"""FastAPI 入口"""

from fastapi import FastAPI, HTTPException
from dotenv import load_dotenv
from langchain_core.messages import HumanMessage

load_dotenv()

from api.schemas import ChatRequest, ChatResponse, TripDraftResponse
from graph.builder import build_graph

app = FastAPI(
    title="入境定制游 AI Agent",
    description="基于 LangGraph 的多 Agent 旅游规划系统",
    version="0.1.0",
)

# 全局图实例（单例）
graph = build_graph()


@app.get("/health")
async def health_check():
    return {"status": "ok", "version": "0.1.0"}


@app.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest):
    """核心接口：接收用户消息，返回 AI 回复"""
    try:
        initial_state = {
            "messages": [HumanMessage(content=req.message)],
            "session_id": req.session_id,
            "customer_id": req.customer_id,
            "channel": req.channel,
            "language": req.language,
        }

        result = await graph.ainvoke(
            initial_state,
            config={"configurable": {"thread_id": req.session_id}},
        )

        draft = result.get("draft", {})
        draft_response = None
        if draft and draft.get("itinerary_md"):
            draft_response = TripDraftResponse(
                version=draft.get("version", 0),
                itinerary_md=draft["itinerary_md"],
                estimated_cost=draft.get("estimated_cost"),
                weather_summary=draft.get("weather_summary"),
            )

        return ChatResponse(
            reply=result.get("final_reply", "抱歉，处理您的请求时出现了问题。"),
            current_branch=result.get("current_branch"),
            draft=draft_response,
            need_human=result.get("need_human", False),
            intent_scores=result.get("intent_scores"),
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
```

---

## 十一、Phase 6：销售 Agent + 运营 Agent ⏳ MVP 后补齐

> ⚠️ **MVP 阶段不实现，Phase 5 完成后单独排期。以下为预留设计，届时细化。**

### 11.1 销售 Agent 要点

```
sales_agent 节点：
  - 工具：quote_price, query_inventory
  - 意向评分（内部简单评分）
  - 流转：
    high → quote_agent → operations_sync
    mid/low → operations_agent 培育
    触发关键词 → human_handoff
```

### 11.2 运营 Agent 要点

```
operations_agent 节点：
  - 工具：update_crm, send_capi
  - 处理：商家入驻、订单履约、售后工单
  - 完成后强制 update_crm → operations_sync
```

### 11.3 新增文件

```
agents/
├── sales_agent.py        ← 新增
├── operations_agent.py   ← 新增
graph/nodes/
├── sales_agent.py        ← 新增
├── operations_agent.py   ← 新增
graph/conditions/
├── intent_score.py       ← 新增（销售出口条件）
prompts/
├── sales_agent.txt       ← 新增
├── operations_agent.txt  ← 新增
tools/
├── mock_quote.py         ← 新增
```

**【待决策】Phase 6 是否在本次开发范围内？还是等 MVP（Phase 0-5）跑通后再做？**

---

## 十二、Phase 7：RAG 增强 ⏳ 后续补齐

> ⚠️ **MVP 阶段不实现。当前客服 FAQ 使用 `tools/mock_faq.py` 硬编码回答，Phase 7 替换为真实向量检索。**

### 12.1 改造点

| 现有 | 改造为 |
|------|--------|
| `tools/mock_faq.py`（关键词匹配） | `tools/rag_faq.py`（向量检索） |
| 固定 FAQ 字典 | 向量数据库（Chroma / Milvus / pgvector） |
| 无知识更新机制 | 知识库管理后台 + 向量化脚本 |

改造后的架构：

```
用户消息 → intent_router
              ↓ (service)
         customer_service
              ↓
         search_faq (RAG 版)
              ↓
    ┌────────┴────────┐
    │ 向量化用户问题    │
    │ 检索 top-K 文档   │
    │ LLM 基于文档回答  │
    └─────────────────┘
```

---

## 十三、Phase 8：生产化

在 MVP 全部跑通后，进入生产化改造。

### 13.1 改造清单

| 改造项 | 当前（MVP） | 生产 |
|--------|-----------|------|
| Checkpoint | MemorySaver | PostgresSaver |
| 会话缓存 | 无 | Redis |
| LLM 观测 | 无 | Langfuse / LangSmith |
| 路由模型 | qwen-turbo | qwen-turbo（或本地 7B LoRA 微调） |
| Tools | 全部 Mock | 对接真实 API |
| 日志 | print | structlog + ELK |
| 监控 | 无 | Prometheus + Grafana |
| 审计 | 无 | 等保三级日志 |

### 13.2 `docker-compose.yml`（生产版）

```yaml
services:
  app:
    build: .
    ports:
      - "8000:8000"
    depends_on:
      - redis
      - postgres
    env_file: .env

  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"

  postgres:
    image: pgvector/pgvector:pg16
    ports:
      - "5432:5432"
    environment:
      POSTGRES_USER: travel
      POSTGRES_PASSWORD: ${DB_PASSWORD}
      POSTGRES_DB: travel_agent
    volumes:
      - pgdata:/var/lib/postgresql/data

volumes:
  pgdata:
```

---

## 十四、决策确认记录

以下为 2026-07-28 确认的全部决策：

| # | 决策项 | 结论 | 备注 |
|---|--------|------|------|
| 1 | **LLM Provider** | 阿里百炼（qwen-turbo + qwen-plus） | API key 后续提供 |
| 2 | **MVP Agent 范围** | 客服 + 定制 | 销售、运营 Phase 6 补齐 |
| 3 | **RAG 知识库** | MVP 不做，Mock 替代 | Phase 7 接真实向量库 |
| 4 | **离线批处理** | 不做 | 与业务场景不符 |
| 5 | **语言支持** | 仅中文 | — |
| 6 | **前端** | 简单测试页面 | 方便调试验证 |
| 7 | **API 鉴权** | MVP 不加 | — |

---

## 附录 A：Phase 进度一览

```
Phase 0  ▓▓▓▓▓▓▓▓▓▓  项目骨架 + Docker           预计 0.5 天
Phase 1  ▓▓▓▓▓▓▓▓▓▓  State + 最简图               预计 1 天
Phase 2  ▓▓▓▓▓▓▓▓▓▓  意图路由器完善                预计 0.5 天
Phase 3  ▓▓▓▓▓▓▓▓▓▓  客服 Agent + 人工接管         预计 1.5 天
Phase 4  ▓▓▓▓▓▓▓▓▓▓  定制 Agent + 修订循环         预计 2.5 天
Phase 5  ▓▓▓▓▓▓▓▓▓▓  终态写入 + /chat 联调         预计 0.5 天
────────── MVP 完成线 ──────────────────────────
Phase 6  ░░░░░░░░░░  销售 + 运营 Agent             预计 2 天
Phase 7  ░░░░░░░░░░  RAG 增强（真实向量检索）        预计 2 天
Phase 8  ░░░░░░░░░░  生产化                        按需
```

---

## 附录 B：关键概念速查

| 概念 | 一句话解释 |
|------|----------|
| **State** | 全局共享的字典，所有节点都能读写，LangGraph 自动持久化 |
| **Node** | 图中的一个执行单元，输入 State → 输出 State 的增量 dict |
| **Conditional Edge** | 条件边，根据 State 的值决定下一步走哪个节点 |
| **Checkpoint** | State 的快照，每次节点执行后自动保存，用于恢复和回放 |
| **Agent** | 包含 LLM + Tools 的业务逻辑单元，由 Node 调用 |
| **Tool** | 外部能力（查天气、查库存等），用 @tool 装饰器封装 |
| **Mock** | 假数据替代品，函数签名和真实版一致，方便后续替换 |
| **thread_id** | LangGraph 的会话标识，对应 session_id |
