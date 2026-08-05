# 入境定制游 AI 多 Agent 系统——架构文档

> **一句话**：基于 LangGraph 的旅程驱动多 Agent 协作系统，4 个 AI Agent 按用户旅程阶段自动接力（发现→定制→销售→售后），前端单页即时通讯，后端 FastAPI + 阿里百炼 + MySQL/Redis/Milvus。

## 技术栈

| 层 | 选型 |
|---|---|
| Agent 框架 | LangGraph（状态图 + Checkpoint 持久化） |
| LLM | 阿里百炼（qwen3-max / qwen-plus），httpx 直连 |
| Embedding | text-embedding-v4（百炼） |
| Web 框架 | FastAPI + SSE 流式输出 |
| 数据库 | MySQL 8.0（业务 + Checkpoint）+ Redis 7（缓存） |
| 向量库 | Milvus 单机（RAG 语义检索） |
| 前端 | 单页 HTML（原生 JS，零框架依赖） |
| MCP | 自研轻量 JSON-RPC 2.0 over stdio，6 个独立 Server 子进程 |
| 部署 | Docker Compose 全容器化 |

## 项目结构

```
├── api/                  FastAPI 入口 + 鉴权 + Schema
│   ├── main.py           应用入口，/chat/stream SSE 端点
│   ├── auth.py           JWT 鉴权
│   └── schemas.py        Pydantic 请求/响应模型
├── graph/                LangGraph 状态图
│   ├── state.py          AgentState 全局数据契约（~30 字段）
│   ├── builder.py        图结构定义（13 节点 + 条件边）
│   ├── nodes/            13 个节点函数（Agent/路由/守卫/同步）
│   └── conditions/       7 个条件边（路由/修订/出口）
├── agents/               4 个业务 Agent
│   ├── base.py           BaseAgent 基类（tool-calling 循环）
│   ├── trip_planner.py   行程定制——需求采集 + 草案生成
│   ├── sales_agent.py    销售顾问——5 阶段 Pipeline
│   ├── operations_agent.py 运营专员——订单管理 + 工单
│   └── customer_service.py 智能客服——RAG 检索 + FAQ
├── tools/                工具层（MCP → Mock 三层降级）
│   ├── mcp_tools.py      20+ LangChain @tool 包装器
│   ├── mock_*.py         9 个 Mock 实现（无网络可用）
│   ├── rag_faq.py        双路 RAG 检索（BM25 + 向量 → RRF）
│   └── bm25_retriever.py 纯 Python BM25 全文检索
├── mcp/                  自研 MCP 协议
│   ├── server.py         JSON-RPC 2.0 stdio Server 基类
│   ├── client.py         MCP Client 连接池 + 子进程管理
│   └── servers/          6 个 Server：天气/日历/库存/报价/CRM/CAPI
├── services/             基础服务层
│   ├── llm.py            LLM 工厂（3 层模型：agent/router/light）
│   ├── memory.py         记忆管理器（短/中/长期三层记忆）
│   ├── mysql.py          SQLAlchemy 异步引擎
│   ├── redis.py          Redis 缓存
│   ├── vector_store.py   Milvus REST 向量操作
│   ├── stream_bridge.py  SSE 令牌桥接
│   └── checkpoint.py     MySQL Checkpoint Saver
├── prompts/              11 个 LLM 提示词模板
├── frontend/             前端（index.html + profile.html）
└── tests/                20+ 测试文件，255 个用例
```

## 核心设计一：旅程驱动的多 Agent 协作

### Journey Stage 状态机

系统用 `journey_stage` 字段表达用户在旅行消费旅程中的位置，这是路由决策的核心依据：

```
discovery ──→ planning ──→ sales ──→ post_purchase
   ↑              ↑           ↑            │
   └──────────────┴───────────┴────────────┘  (LOST/回流转)
```

| Stage | 含义 | 主导 Agent | 典型用户行为 |
|-------|------|-----------|-------------|
| `discovery` | 探索阶段 | 意图路由分发 | "你能干什么" / "我想去拉萨" |
| `planning` | 行程定制 | trip_planner | 确认需求→生成草案→修订→接受 |
| `sales` | 销售转化 | sales_agent | 报价→议价→优惠→下单→支付 |
| `post_purchase` | 售后运营 | operations_agent | 查订单→改签→工单→投诉 |

### Agent 接力协议

Agent 间的交接通过三个字段实现：

```
trip_planner 确认行程后返回：
  journey_stage = "sales"
  next_agent = "sales_agent"
  handoff_context = {reason: "draft_confirmed", draft_id, pipeline_stage: "qualified", ...}

sales_agent 支付成功后返回：
  journey_stage = "post_purchase"
  next_agent = "operations_agent"
  handoff_context = {reason: "payment_completed", order_id, ...}

operations_agent 检测回流转后返回：
  next_agent = "trip_planner" / "sales_agent"
  handoff_context = {reason: "trip_modify_requested" / "re_purchase_request", ...}
```

**同轮自动接管**：`intent_scorer` 判定 accept → 不走 END，直接回到 `route_decision` 节点，下一轮就切换到新 Agent。

### 统一出口条件

所有 Agent 共用 `_agent_exit` 条件边：

1. `need_human=True` → `human_handoff`（转人工）
2. `next_agent ≠ current_branch` → `route_decision`（Agent 接力）
3. 默认 → `operations_sync`（同步数据，结束本轮）

## 核心设计二：多层路由系统

路由采用 **预检 → LLM → 阶段驱动** 三层管道：

```
用户消息
  │
  ├─ ① 预过滤器（regex，零 LLM 成本）
  │   ├─ 能力询问 → service=0.95（永不转人工）
  │   ├─ 寒暄 → service=0.90
  │   └─ 行程信号 → planner=0.85 + journey_stage=planning
  │       （8 正向模式 + 4 FAQ 排除模式，防止"我想去拉萨"误判为客服）
  │
  ├─ ② journey_stage ≠ discovery → 打断检测
  │   ├─ 投诉/退款 → need_human
  │   ├─ 定制/销售阶段提订单 → post_purchase 打断
  │   └─ 运营阶段提新行程/加购 → planning/sales 打断
  │
  └─ ③ discovery 阶段 → LLM 意图分类（qwen-plus）
      ├─ max_score < 0.3 → customer_service 兜底
      ├─ gap ≤ 0.25 + 同分支 → 惯性保持
      └─ 有未转化行程/活跃订单 → 加权调整
```

## 四个 Agent

### 1. TripPlanner（行程定制）🗺️

- **模型**：qwen3-max（复杂长文本生成）
- **流程**：需求采集（regex + LLM 双通道）→ 并行 MCP 工具查询（天气/日历/库存）→ 动态 Prompt 生成行程草案 → 修订循环（上限3次）
- **特性**：`_is_confirm_signal()` 16 个确认模式快速检测，确认时跳过不必要的重生成
- **工具**：get_weather / query_calendar / query_inventory

### 2. SalesAgent（销售顾问）💰

- **模型**：qwen-plus（中等推理 + 多工具调用）
- **Pipeline**：LEAD → QUALIFIED → NEGOTIATION → CLOSING → WON/LOST
- **分阶段 Prompt**：4 个 Prompt 动态加载（lead/qualified/negotiation/closing）
- **Handoff 感知**：收到 `draft_confirmed` 交接时跳过 LEAD，直接从 QUALIFIED 阶段开始
- **WON 检测**：仅 `process_payment` 工具成功/"支付成功"文字才触发 WON（`create_order` 不误判）
- **工具**：load_trip_draft / quote_price / create_order / get_payment_url / apply_coupon / check_order_status / process_payment

### 3. OperationsAgent（运营专员）📋

- **模型**：qwen-plus
- **职责**：WON 接管消息生成 + 订单查询/取消/修改 + 工单创建/查询 + 回流转检测
- **回流转**：检测"改行程"→`next_agent=trip_planner`，检测"加购"→`next_agent=sales_agent`
- **紧急升级**：投诉/退款关键词 → `need_human=True`
- **工具**：12 个（search_hotels/flights/tickets/guides + get_order/list_orders/cancel_order/modify_order + create_ticket/check_ticket + update_crm/send_capi）

### 4. CustomerServiceAgent（智能客服）🤖

- **模型**：qwen-plus
- **检索流程**：用户问题 → `search_faq`（BM25 + Milvus 向量 → RRF 融合 → Top-K）→ 注入 Prompt → LLM 生成回答
- **多语言**：zh/en/es/ja/ko/hi/ar 7 语言感知
- **转人工**：检索无结果 + 投诉关键词 → check_handoff
- **工具**：check_handoff

## MCP 工具系统

自研轻量 MCP 协议（JSON-RPC 2.0 over stdio），6 个独立 Server 子进程：

| Server | 数据源 | 功能 |
|--------|--------|------|
| weather_server | Open-Meteo 免费 API | 48 城市实时天气 |
| calendar_server | chinese-calendar | 中国节假日判断 |
| inventory_server | 48 城市×3 档×季节性波动引擎 | 酒店库存查询 |
| quote_server | 城市日均价×主题溢价×节奏因子引擎 | 行程报价 |
| crm_server | MySQL | CRM 记录写入 |
| capi_server | Meta/Google/TikTok | 转化事件上报 |

**三层降级**：MCP Server → Mock 实现 → 错误提示。Agent 零感知切换。

## 记忆系统（三层）

| 层级 | 存储 | TTL | 用途 |
|------|------|-----|------|
| 短期 | Redis 缓存 + MySQL chat_messages | 7天 | 对话上下文窗口 |
| 中期 | MySQL user_preferences | 30-90天 | LLM 提取旅行偏好快照 |
| 长期 | MySQL user_profiles | 永久 | 用户画像（国籍/预算/兴趣/偏好等） |

**Agent 注入**：`session_context` 节点在每轮开始前从 DB 加载用户画像和偏好，注入 State 供所有 Agent 读取，减少重复追问。

## 图结构（完整流程）

```
START → input_guard → session_context → query_rewrite → intent_router
                                                              │
      ┌─────────────┳──────────────┳──────────────────────────┼──────────────────────┐
      ▼             ▼              ▼                          ▼                      ▼
 customer_service  sales      operations               trip_planner            human_handoff
      │    │         │    │       │    │                      │                      │
      │    └──→ _agent_exit ←──┘   │    │         requirements_complete              │
      │         ├→ human_handoff    │    │            ├→ intent_scorer                │
      │         ├→ route_decision   │    │            │   ├→ operations_sync           │
      │         └→ operations_sync  │    │            │   ├→ revision_loop → back     │
      │                             │    │            │   ├→ human_handoff             │
      │                             │    │            │   └→ route_decision (同轮交接) │
      │                             │    │            └→ END (需求不全)               │
      └─────────────────────────────╋────╋────────────────────────────────────────────│
                                    │    └────────────────────────────────────────────│
                                    └──────────→ operations_sync → END ←──────────────┘
```

## 前端

单页 HTML（`frontend/index.html`），零框架依赖：

- **左侧栏**：对话列表（按更新时间倒序，悬停删除确认）+ 模式切换（默认/定制/客服/销售/运营）+ 语言切换（7 种）
- **主区域**：消息气泡（用户蓝底 + Agent 白底带分支色条）+ Markdown 渲染 + 行程卡片/报价单
- **流式输出**：SSE 打字机效果（`node_start` 进度标签 → `token` 逐字追加 → `done` 最终渲染）
- **用户可打断**：红色停止按钮 → `AbortController` 中断 SSE → 保留已生成内容 + 中断标记
- **画像编辑**：`frontend/profile.html` 独立页面，手动编辑旅行偏好

## API

| 端点 | 方法 | 说明 |
|------|------|------|
| `/chat/stream` | POST | SSE 流式对话（主入口） |
| `/conversations` | GET/POST | 对话列表/创建 |
| `/conversations/{id}` | DELETE | 删除对话 |
| `/conversations/{id}/messages` | GET | 消息历史 + 摘要 |
| `/auth/login` | POST | JWT 登录 |
| `/auth/register` | POST | 注册 |
| `/api/profile` | GET/PUT | 用户画像读写 |
| `/api/profile/suggestions` | GET | LLM 画像建议 |
| `/profile` | GET | 画像编辑页面 |
| `/health` | GET | 健康检查 |

## 模型分层策略

```
qwen3-max    → trip_planner（复杂长文本行程生成，最强模型）
qwen-plus    → sales_agent / operations_agent / customer_service / intent_router / query_rewrite
               （需多工具 function calling 支持，中等推理能力）
```

所有模型通过 `services/llm.py` 的 `BailianLLM` 统一封装，httpx 直连百炼兼容 OpenAI API，零 langchain-openai 依赖。

## 数据流（完整一轮对话）

```
1. 用户消息 → POST /chat/stream
2. input_guard        → 空消息/超长拦截
3. session_context    → 加载 user_profile + user_preferences + 未转化行程 + 活跃订单
4. query_rewrite      → 拼音→中文 / 中英混杂→中文 / 规范中文免调用
5. intent_router      → 预检 → 打断检测 → LLM 分类 → intent_scores + journey_stage
6. route_decision     → 五路分发（客服/销售/运营/定制/人工）
7. Agent.run()        → tool-calling 循环 → final_reply
8. _agent_exit        → need_human / 交接 / 同步
9. operations_sync    → MemoryManager 批量持久化（消息 + CRM + CAPI）
10. SSE 流式返回       → node_start → token... → done
```

## 测试

- **255 个测试用例**，覆盖所有条件边、Agent、工具、State、图结构、API、E2E
- `TestTripPlanningPrefilter`：10 个行程预检专项测试
- `TestSalesPipeline`：Pipeline 阶段判定 + WON/LOST 逻辑
- `TestAfterSales`：after_sales 条件边四路分发

## 项目演进

系统从最初的"带路由的聊天机器人"（Phase 1-5，每轮重新 LLM 猜测意图）逐步演进为旅程驱动的多 Agent 协作系统（Phase 22），核心里程碑：

- **Phase 1-9**：MVP——四分支图 + 工具 + RAG + 流式输出
- **Phase 18**：MCP 标准化 + 真实数据源接入
- **Phase 20**：销售 Pipeline 五阶段重设计
- **Phase 21**：运营 Agent 重设计（12 工具平台层）
- **Phase 22**：**Journey Stage 驱动架构**——Agent 接力协议 + 统一出口 + 同轮交接 + 打断检测

详细演进记录见 [`progress.md`](progress.md)。
