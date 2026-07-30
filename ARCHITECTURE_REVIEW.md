# 架构审查报告

> 自动生成于 2026-07-30 · 基于代码实际状态

---

## 一、整体架构图

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                          前端层                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │  static/index.html  (单页 HTML, ~670 行)                             │    │
│  │  原生 JS + CSS · 无框架 · 无 TypeScript · 无构建工具                  │    │
│  │  fetch('/chat') → 渲染气泡/意图环/行程卡片                            │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
└────────────────────────────────┬────────────────────────────────────────────┘
                                 │ HTTP POST /chat
                                 ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                     FastAPI 层  (api/main.py, ~120 行)                       │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │  CORS: * (全开)                                                      │   │
│  │  GET  /        → static/index.html                                   │   │
│  │  GET  /health   → {"status":"ok"}                                    │   │
│  │  POST /chat     → 构建 State → graph.ainvoke() → ChatResponse        │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
│  启动: uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload             │
└────────────────────────────────┬────────────────────────────────────────────┘
                                 │ graph.ainvoke(initial_state, config)
                                 ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                  LangGraph 编排层  (graph/builder.py, ~230 行)               │
│                                                                             │
│  START → input_guard → session_context → intent_router                      │
│                                              │                              │
│         ┌─────────────┬───────────┬──────────┼───────────┐                  │
│         ▼             ▼           ▼          ▼           ▼                  │
│   customer_service  sales    operations  trip_planner  human_handoff       │
│   (FAQ/投诉转人工)   (报价)   (入驻/履约)  (需求采集/草案)   │                  │
│         │             │           │          │           │                  │
│    after_service  after_sales     │   requirements_       │                  │
│    ├→handoff       ├→ops_sync     │   complete            │                  │
│    ├→router        ├→handoff      │   ├→intent_scorer    │                  │
│    └→END           └→END          │   │  ├→ops_sync       │                  │
│                                   │   │  ├→revision_loop ─┘                 │
│         ┌─────────────────────────┘   │  └→handoff                          │
│         │                             │                                     │
│         │              ┌──────────────┘                                     │
│         ▼              ▼                                                    │
│    operations_sync  (终态: CRM + CAPI, 透传)                                │
│         │                                                                    │
│         ▼                                                                    │
│        END                                                                   │
│                                                                             │
│  Checkpoint: MemorySaver (进程内, 重启丢失)                                  │
└─────────────────────────────────────────────────────────────────────────────┘
                                 │
                                 ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                     Agent 业务层  (agents/*.py, 4个 Agent)                    │
│                                                                             │
│  BaseAgent (ABC)                                                            │
│  ├── CustomerServiceAgent  (FAQ + 转人工)     Tools: search_faq, check_handoff│
│  ├── SalesAgent            (报价 + 意向评分)   Tools: quote_price, query_inventory│
│  ├── OperationsAgent       (入驻/履约/工单)    Tools: update_crm, send_capi │
│  └── TripPlannerAgent      (需求提取/草案/修订) Tools: get_weather, query_calendar, query_inventory│
│                                                                             │
│  每个 Agent:                                                                │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │  1. bind_tools(tools)                                                │    │
│  │  2. llm.invoke(system_prompt + user_msg)                             │    │
│  │  3. for tool_call in response.tool_calls: invoke tool                │    │
│  │  4. llm.invoke(system + user + ai_msg + tool_results) → final_reply  │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
│  ⚠️ 问题: 4 个 Agent 各自重复了相同的 tool-calling 循环代码                  │
└────────────────────────────────┬────────────────────────────────────────────┘
                                 │
                                 ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                      基础设施层                                              │
│                                                                             │
│  services/llm.py          → ChatOpenAI(langchain_openai) 调用百炼            │
│                             Router: qwen-turbo  ·  Agent: qwen-plus          │
│  services/embeddings.py   → httpx 直连 DashScope 原生 API                    │
│                             模型: text-embedding-v2                          │
│  services/vector_store.py → 纯 Python JSON 持久化 + 手写余弦相似度            │
│                             零额外依赖 (仅 stdlib math + json)               │
│  prompts/*.txt            → 5个 System Prompt 模板 (纯文本)                   │
└────────────────────────────────┬────────────────────────────────────────────┘
                                 │
                                 ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                      工具层 (9 个 Mock Tool)                                 │
│                                                                             │
│  已使用:                                                                     │
│  ├── search_faq / rag_faq     → RAG 向量检索 + 关键词兜底 (Phase 7)         │
│  ├── check_handoff            → 关键词检测投诉转人工                           │
│  ├── get_weather              → 12 城市硬编码天气数据                          │
│  ├── query_calendar           → 硬编码节假日                                  │
│  ├── query_inventory          → 硬编码酒店/门票/车辆库存                       │
│  ├── quote_price              → 32 城市基准价 + 公式计算 (Phase 6)            │
│  ├── update_crm               → print() 模拟 CRM 写入                         │
│  └── send_capi                → print() 模拟转化事件                           │
│  未使用:                                                                     │
│  └── mock_faq.py              → 旧版关键词 FAQ (被 rag_faq 替代)              │
│                                                                             │
│  ⚠️ 全是 Mock，无真实外部集成                                                │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 二、技术栈清单 (实际使用)

| 类别 | 组件 | 版本要求 | 用途 | 选型评价 |
|------|------|----------|------|:--------:|
| **编排引擎** | LangGraph | ≥0.2.0 | Agent 状态图、条件路由、Checkpoint | ✅ 合适 |
| **Agent 框架** | LangChain | ≥0.3.0 | BaseMessage、bind_tools、with_structured_output | ⚠️ 偏重 |
| **LLM 桥梁** | langchain-openai (ChatOpenAI) | ≥0.2.0 | 调用百炼 OpenAI 兼容端点 | ⚠️ 依赖税 |
| **路由模型** | 百炼 qwen-turbo | — | 意图识别、结构化提取 | ✅ 合适 |
| **生成模型** | 百炼 qwen-plus | — | 行程生成、客服回复、报价 | ✅ 合适 |
| **Embedding** | 百炼 text-embedding-v2 | — | RAG 向量检索 | ✅ 合适 |
| **Embedding 调用** | httpx (直连 DashScope 原生 API) | ≥0.27 | POST dashscope.aliyuncs.com | ✅ 正确绕过兼容层 |
| **Web 框架** | FastAPI | ≥0.115.0 | HTTP API + 静态文件服务 | ✅ 合适 |
| **ASGI 服务器** | uvicorn | ≥0.30.0 | 进程启动 | ✅ 合适 |
| **数据校验** | Pydantic | ≥2.0 | ChatRequest/ChatResponse 模型 | ✅ 合适 |
| **环境配置** | python-dotenv | ≥1.0 | .env 加载 | ✅ 合适 |
| **向量存储** | 纯 Python (json + math) | — | JSON 持久化 + 余弦相似度 | ⚠️ 玩具级 |
| **Checkpoint** | MemorySaver | LangGraph 内置 | 会话上下文持久化 | ❌ 进程内 |
| **前端** | 原生 HTML/CSS/JS | — | 静态页面，无框架 | ⚠️ 原型级 |
| **容器化** | Docker + docker-compose | — | 已配置但**未使用** | ❌ 未启用 |
| **测试** | pytest + pytest-asyncio | ≥8.0 | 测试框架 | ✅ 合适 |

---

## 三、问题分析

### 🔴 严重问题

#### 1. Docker 配置存在但从未使用
- `Dockerfile` 和 `docker-compose.yml` 已写好
- 实际运行方式是 `python main.py`（裸 uvicorn）
- Docker 宿主机上运行着 Dify 全家桶，但 **travel-agent 容器从未启动过**
- 影响：生产环境零准备

#### 2. Checkpoint 用 MemorySaver——重启全部会话丢失
- `graph/builder.py:200`: `MemorySaver()`
- 注释写 "生产环境切 PostgresSaver"，但没有实现
- `.env.example` 中 `DATABASE_URL` 注释掉了
- 影响：服务重启 → 所有进行中的会话（多轮需求收集、修订循环）全部丢失

#### 3. Agent 同步阻塞在 async 上下文中
- 4 个 Agent 的 `.run()` 都是同步方法
- `api/main.py:92`: `await _graph.ainvoke()` 是 async
- LangGraph 内部会在线程池中执行同步节点，但 Agent 内部 `llm.invoke()` 是同步 HTTP 调用
- 影响：高并发下阻塞 event loop

### 🟡 中等问题

#### 4. Tool-calling 样板代码重复 4 次
- `customer_service.py`、`sales_agent.py`、`operations_agent.py` 三处几乎一样的模式：
  ```python
  llm.bind_tools(tools) → invoke → for tool_calls → invoke tool → llm.invoke again
  ```
- 应该在 `BaseAgent` 中统一实现，子类只提供 tools 列表和结果处理逻辑
- TripPlanner 更特殊——它完全绕过了 tool-calling 模式，直接手动调用工具

#### 5. langchain-openai 依赖过重
- `services/llm.py` 用 `langchain_openai.ChatOpenAI` 仅作为 HTTP 桥梁
- 实际只是向 `https://dashscope.aliyuncs.com/compatible-mode/v1` 发 POST 请求
- 可以改用轻量 httpx + 百炼官方 SDK (`dashscope`)，减少依赖链
- 对比：`embeddings.py` 已经直接用了 httpx，但 LLM 调用还在用 LangChain 包装

#### 6. RAG 向量存储非常脆弱
- `services/vector_store.py`：JSON 文件 + 全量余弦相似度遍历
- 30 个文档 OK，3000 个文档就会线性退化
- 没有索引结构 (HNSW/IVF)，没有增量更新，没有并发安全
- `.env.example` 写 `VECTOR_DB_TYPE=chroma` 但实际代码完全没用到

#### 7. 前端只是原型水平
- 单文件 ~670 行，HTML/CSS/JS 全混在一起
- 无组件化、无状态管理、无路由
- 无错误重试、无流式输出 (SSE/WebSocket)
- 移动端未适配 (虽然 flex 布局可凑合用)

### 🟢 轻微问题

#### 8. 关键词匹配过度使用
- `SalesAgent._score_intent()`: 纯关键词匹配判断购买意向
- `OperationsAgent.run()`: 关键词匹配判断是否需要转人工
- `_extract_fields_regex()`: 硬编码 32 城市列表
- 扩容/国际化时需要改代码

#### 9. 异常处理体面但不够
- intent_router 有兜底 → service(1.0)
- 各 Agent 无重试逻辑
- API 层只有一个宽泛的 try/except

#### 10. .env.example 与代码不一致
- `VECTOR_DB_TYPE=chroma` 但实际用的是纯 Python JSON
- 已注释的 `DATABASE_URL` / `REDIS_URL` 从未被代码引用

---

## 四、推荐改进优先级

| 优先级 | 改进项 | 工作量 | 影响 |
|:---:|------|:---:|------|
| **P0** | 提取 tool-calling 循环到 BaseAgent | 2h | 消除 3 处重复代码 |
| **P0** | PostgresSaver 替代 MemorySaver | 4h | 会话持久化 |
| **P1** | Docker 化部署跑通 | 1h | 环境一致性 |
| **P1** | 前端加入 SSE 流式输出 | 3h | 体验从 30s 白屏 → 逐字输出 |
| **P1** | Agent 异步化 (llm.ainvoke) | 2h | 并发能力 |
| **P2** | 去 langchain-openai，改用 httpx 直连 | 3h | 减少依赖 |
| **P2** | 向量存储升级 (ChromaDB / Qdrant) | 4h | RAG 可扩展 |
| **P3** | 前端框架化 (React/Vue) | 1-2d | 可维护性 |

---

## 五、文件统计

| 目录 | 文件数 | 代码行数 | 说明 |
|------|:---:|:---:|------|
| `agents/` | 5 | ~550 | 4 个业务 Agent + 基类 |
| `api/` | 2 | ~140 | FastAPI 入口 + Schema |
| `graph/` | 13 | ~560 | State(1) + Builder(1) + Nodes(9) + Conditions(5) |
| `tools/` | 10 | ~650 | 9 Mock 工具 + RAG FAQ |
| `services/` | 3 | ~260 | LLM 工厂 + Embedding + Vector Store |
| `prompts/` | 6 | ~220 | 5 个 Prompt 模板 + loader |
| `scripts/` | 2 | ~300 | 知识库定义 + 摄入脚本 |
| `static/` | 1 | ~670 | 前端页面 |
| 根目录 | 5 | ~200 | main.py, Dockerfile, compose, requirements, .env |
| **总计** | **~47** | **~3,550** | |
