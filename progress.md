# 项目进度日志

> 入境定制游多 Agent 系统——基于 LangGraph + FastAPI + 阿里百炼
>
> 最后更新：2026-08-05（Phase 22 旅程驱动的多 Agent 协作——journey_stage + handoff 全链路打通）

---

## 一、项目概述

基于 LangGraph 构建入境定制游平台的智能 Agent，由意图路由器统一分发到业务分支。Python 3.12 + FastAPI + Docker，LLM 使用阿里百炼平台。

### 技术栈速览

| 层级 | 技术 | 说明 |
|------|------|------|
| 编排引擎 | LangGraph ≥ 0.2 | 图结构、State 管理、Checkpoint |
| Agent 框架 | LangChain ≥ 0.3 | Agent 抽象、Tool 封装 |
| Web 框架 | FastAPI ≥ 0.115 | /chat 接口 |
| LLM 路由 | 百炼 qwen-plus | 意图识别（平衡速度与质量） |
| LLM 生成 | 百炼 qwen3-max | 行程生成、客服回复（强推理） |
| Embedding | 百炼 text-embedding-v4 | 1024 维向量 |
| 向量数据库 | Milvus 2.4 单机 | HNSW 索引 + COSINE 相似度 |
| 关系数据库 | MySQL 8.0 | 会话存储 + LangGraph Checkpoint |
| 缓存 | Redis 7 | 会话历史 + 摘要缓存 |
| 容器化 | Docker + docker-compose | 6 个服务一键部署 |
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

## 三-续、Phase 1 完成——State 定义 + 最简图 ✅

**完成时间**：2026-07-29

### 创建/更新的文件

```
graph/
├── state.py                     ← 新增：AgentState 定义
│   ├── TripNeed (TypedDict)     # 出行需求字段
│   ├── TripDraft (TypedDict)    # 行程草案字段
│   └── AgentState (MessagesState) # 全局 State
├── builder.py                   ← 新增：build_graph() 最简图
├── nodes/
│   ├── input_guard.py           ← 新增：入参保护
│   ├── session_context.py       ← 新增：会话初始化
│   └── intent_router.py         ← 新增：意图路由（Phase 2 版）
├── conditions/
│   └── route_decision.py        ← 新增：路由分发条件
services/
└── llm.py                       ← 新增：LLM 工厂（百炼）
prompts/
├── __init__.py                  ← 重写：load_prompt() 加载工具
└── intent_router.txt            ← 新增：路由 Prompt 模板
main.py                          ← 更新：添加 test 模式
```

### 关键实现

- **AgentState**：继承 MessagesState，包含渠道/路由/业务/控制/输出五大类字段
- **LLM 工厂**：`get_router_llm()` (qwen-turbo) 和 `get_agent_llm()` (qwen-plus)，均从环境变量读取
- **图结构**：START → input_guard → session_context → intent_router → 条件分发 → END
- **占位节点**：customer_service / trip_planner / human_handoff 均为占位，Phase 3-5 逐步替换

## 三-续2、Phase 2 完成——意图路由器完善 ✅

**完成时间**：2026-07-29

### 改进内容

- **结构化输出**：定义 `IntentResult` Pydantic 模型，使用 `llm.with_structured_output()` 替代裸 `json.loads`
- **异常兜底**：LLM 调用失败时默认进客服分支，不会崩溃
- **空消息保护**：无消息或空消息时返回默认分类
- **路由逻辑**：need_human 优先 → 最高分意图 → 低置信度兜底

### 验证结果

- `python main.py test` → 4 组测试用例全部通过
- 图结构正确编译，checkpoint 正常持久化
- 意图路由能够正确区分定制/客服/投诉类消息

## 三-续3、Phase 3 完成——客服 Agent + 人工接管 ✅

**完成时间**：2026-07-29

### 创建/更新的文件

```
agents/
├── base.py                              ← 新增：BaseAgent 抽象基类
└── customer_service.py                  ← 新增：客服 Agent（LLM + Tools）
tools/
├── mock_faq.py                          ← 新增：Mock FAQ 检索（10 个常见类别）
└── mock_handoff.py                      ← 新增：转人工评估工具
prompts/
└── customer_service.txt                 ← 新增：客服 Prompt 模板
graph/nodes/
├── customer_service.py                  ← 新增：客服节点（替换占位）
└── human_handoff.py                     ← 新增：人工接管节点（生成交接单）
graph/conditions/
└── after_service.py                     ← 新增：客服后置条件边
graph/builder.py                         ← 更新：替换客服+接管占位节点
main.py                                  ← 更新：扩展为 6 组测试
```

### 关键实现

- **BaseAgent**：抽象基类，统一 `llm + tools + system_prompt` 的 Agent 模式，提供 `_get_user_message()` 和 `_get_message_history()` 工具方法
- **CustomerServiceAgent**：使用 `llm.bind_tools()` 绑定 `search_faq` 和 `check_handoff` 两个工具，LLM 自主决策是否调用工具，支持多轮 tool calling
- **Mock FAQ 知识库**：覆盖签证、支付、退改、天气、小费、网络、交通、安全、美食、语言 10 大类，支持中英文关键词匹配
- **Mock Handoff**：基于关键词（投诉、退款、差评等）判断是否需要转人工，含强信号检测
- **after_service 条件边**：need_human → human_handoff / 有回复 → END / 无回复 → intent_router（支持重新路由）
- **人工接管节点**：生成结构化交接单（客户 ID、渠道、意图分数、出行需求、草案摘要、最后消息）
- **图结构更新**：客服分支改为条件边（3 路分发），human_handoff 直连 END

### 验证结果

- `python main.py test` → 6 组测试用例全部通过
- 测试 1-2：FAQ 查询（签证/支付）→ 正确调用 search_faq 并生成自然语言回复
- 测试 3-4：投诉/退款 → 正确触发 need_human=True，生成交接单
- 测试 5：定制意图 → 正确路由到 trip_planner（占位）
- 测试 6：同 thread 追问 → checkpoint 持久化正常（message history: 2）

## 三-续4、Phase 4 完成——定制 Agent + 修订循环 ✅

**完成时间**：2026-07-29

### 创建/更新的文件

```
tools/
├── mock_weather.py                      ← 新增：Mock 天气工具（12个城市）
├── mock_calendar.py                     ← 新增：Mock 节假日/人流量工具
└── mock_inventory.py                    ← 新增：Mock 库存工具（酒店/门票/车辆）
prompts/
└── trip_planner.txt                     ← 新增：定制 Prompt 模板
agents/
└── trip_planner.py                      ← 新增：TripPlannerAgent（需求提取+草案生成）
graph/nodes/
├── trip_planner.py                      ← 新增：定制节点（替换占位）
├── intent_scorer.py                     ← 新增：意向评分节点
└── revision_loop.py                     ← 新增：修订计数器
graph/conditions/
├── requirements_complete.py             ← 新增：必填项检查条件边
└── revision_decision.py                 ← 新增：修订决策条件边
graph/builder.py                         ← 更新：完整定制分支链
main.py                                  ← 更新：6 组测试（含定制+修订）
```

### 关键实现

- **TripPlannerAgent**：最复杂的 Agent，分四步走——① LLM 结构化提取需求字段（NeedExtract）；② 合并 checkpoint 已有 need，检查必填项（destination/days/date/pax/budget）；③ 缺失则友好追问（展示已确认信息+缺失项）；④ 齐全则调用 weather/calendar/inventory 三个工具获取实时数据，传给 LLM 生成 Markdown 行程草案
- **需求字段提取**：使用轻量 router_llm + `with_structured_output(NeedExtract)`，只提取用户明确提到的信息，不猜测
- **Mock 工具组**：weather（12个城市模拟天气）、calendar（节假日+工作日+人流量预测）、inventory（酒店/门票/车辆库存），Phase 8 替换为真实 API
- **意向评分**：使用 `Literal['high','mid','low']` + `Literal['accept','revise','give_up']` 严格约束输出，含一致性后处理（修订>=3次强制 accept/give_up）
- **修订决策**：accept→END，revise+cnt<3→revision_loop→trip_planner，give_up/超限→human_handoff
- **图结构**：定制分支完整链路 trip_planner → requirements_complete → intent_scorer → revision_decision → {END / revision_loop / human_handoff}

### 验证结果

- `python main.py test` → 6 组测试用例全部通过
- 测试 1：信息不全 → 正确追问缺失的 4 个必填项
- 测试 2：完整信息 → 生成 v1 草案，intent=high，action=accept
- 测试 3：多轮收集 → checkpoint 正确跨轮传递 need，第二轮合并后生成完整行程
- 测试 4：修订循环 → revision_loop 触发重新生成，v1→v4 迭代，最终 accept 退出
- 测试 5-6：客服 FAQ 和投诉转人工 Phase 3 回归正常

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
Phase 1  ██████████  ✅ State 定义 + 最简图             2026-07-29 完成
Phase 2  ██████████  ✅ 意图路由器完善                  2026-07-29 完成
Phase 3  ██████████  ✅ 客服 Agent + 人工接管             2026-07-29 完成
Phase 4  ██████████  ✅ 定制 Agent + 修订循环             2026-07-29 完成
Phase 5  ██████████  ✅ 终态写入 + /chat API 联调         2026-07-29 完成
────────── MVP 完成线 ─────────────────────────────────────
Phase 6  ██████████  ✅ 销售 Agent + 运营 Agent         2026-07-30 完成
Phase 7  ██████████  ✅ RAG 增强（真实向量检索）         2026-07-30 完成
Phase 8  ██████████  ✅ 基础设施升级（Milvus+MySQL+Redis）  2026-07-30 完成
Phase 9  ██████████  ✅ SSE 流式输出（进度推送 + 降级兼容）   2026-07-30 完成
Phase 10 ██████████  ✅ 意图预过滤 + Markdown 渲染 + 格式美化 + 对齐修复 2026-07-31 完成
Phase 11 ██████████  ✅ 短/中/长期记忆系统（Redis 缓存 + MySQL 持久化 + 上下文窗口管理 + LLM 偏好提取 + 用户画像）   2026-08-01 完成
```

---

### Phase 11 ✅ 短/中/长期记忆系统（2026-08-01）

解决用户切换对话窗口后消息丢失、无上下文窗口管理、无用户偏好记忆等问题。

#### 三层记忆架构

| 层级 | 存储 | TTL | 核心功能 |
|------|------|-----|----------|
| **短期记忆** | Redis + MySQL | 24h / 7天 | 对话消息缓存、切换窗口恢复、上下文窗口管理（qwen3-max 32K tokens，>70% 触发 LLM 摘要） |
| **中期记忆** | MySQL | 60天 | LLM 自动提取旅行偏好（目的地/预算/节奏/兴趣/同行人/特殊需求/季节），每 5 轮触发一次 |
| **长期记忆** | MySQL | 永久 | 用户画像（基础信息 + 旅行偏好 + LLM 建议→用户确认），新增 /profile 页面可编辑 |

#### 新增文件

```
services/memory.py                  ← 记忆管理器核心（~550 行）
  ├── MemoryManager 类
  │   ├── save_message / get_messages / get_message_count
  │   ├── save_summary / get_summary
  │   ├── estimate_tokens / should_summarize / generate_summary / trim_context
  │   ├── extract_preferences / save_preferences / get_active_preferences
  │   └── get_profile / ensure_profile / update_profile / merge_suggestions / reject_suggestions
prompts/summary.txt                 ← LLM 对话摘要 Prompt
prompts/preference_extract.txt      ← LLM 偏好提取 Prompt
frontend/profile.html               ← 用户画像页面（编辑 + AI 建议采纳/忽略）
tests/test_memory.py                ← 记忆系统测试（16 用例）
```

#### 修改文件

```
scripts/migrate_mysql.sql           ← 新增 4 张表（chat_messages / chat_summaries / user_preferences / user_profiles）
api/schemas.py                      ← 新增 8 个 Pydantic 模型
api/main.py                         ← +10 个端点：画像 CRUD、偏好查询、消息增强、对话后处理、定期清理
services/redis.py                   ← 新增 5 个缓存函数（chat_messages / chat_summary / user_profile / invalidate）
.env.example                        ← 新增 6 个环境变量（CONTEXT_WINDOW_TOKENS 等）
frontend/index.html                 ← 侧边栏→画像页入口 + 消息加载增强（元数据+摘要横幅）
```

#### 关键设计

- **对话消息持久化**：`/chat` 完成后异步保存到 MySQL `chat_messages` 表 + Redis 缓存（`chat:{conv_id}:messages`）
- **消息加载优先级**：Redis → MySQL → LangGraph checkpoint（三级回退）
- **上下文窗口管理**：Token 估算（中文 ~1.5 字/token）+ 超过 70% 阈值时 LLM 摘要 + 保留最近 10 轮
- **偏好提取**：qwen-plus + structured output → Pydantic model → MySQL `user_preferences`（60 天 TTL）
- **用户画像**：LLM 建议写入 `suggested_fields` → 用户画像页展示 → 用户手动采纳/忽略
- **定期清理**：后台每小时清理过期消息（7 天）+ 过期偏好（60 天）

#### 验证结果

- `python -m pytest tests/ -v` → **193 个测试全部通过**（177 原有 + 16 新增，6.9s）
- 根节点零改动（graph/ + agents/ + tools/ + prompts/ 原有文件不变）
- ⚠️ **发现：AI Agent 未读取记忆**——消息和画像数据仅用于前端展示，Agent prompt 未注入（详见 Phase 11-续）

---

### Phase 11-续 ✅ AI 记忆注入——Agent 读取短/中/长期记忆（2026-08-01）

Phase 11 实现了记忆的存储和前端展示，但 **AI Agent 在对话时完全没有读取这些数据**：
- `chat_messages` 表的消息未被加载到 graph state（仅依赖 checkpoint）
- `user_profiles` 表的画像未被注入 Agent prompt
- `user_preferences` 表的偏好未被任何 Agent 使用

本次修复将三层记忆完整接入 AI 对话流程。

#### 核心改动

| 文件 | 改动 | 说明 |
|------|------|------|
| `graph/state.py` | +2 字段 | 新增 `user_profile: dict` + `user_preferences: dict` |
| `graph/nodes/session_context.py` | 重写 | 异步节点，从 `MemoryManager` 加载画像和偏好到 State |
| `agents/trip_planner.py` | +~80 行 | `_enrich_from_memory()` 自动补全缺失字段，`_build_profile_context()` 构建 Prompt 上下文，追问跳过已知偏好 |
| `agents/customer_service.py` | +~40 行 | `_build_context()` 从 State 提取画像注入 `extra_context` |
| `agents/sales_agent.py` | +~30 行 | 同上，注入国籍/预算/目的地到 tool-calling 循环 |
| `api/main.py` | +~35 行 | `_load_chat_history()` 从 MySQL 加载历史消息；`/chat` `/chat/stream` 调用前合并历史 |
| `tests/test_trip_planner.py` | 2 行 | `session_context` 测试从同步改为 async |

#### 数据流（修复后）

```
用户消息 → _load_chat_history(conv_id)  ← 🧠 MySQL chat_messages
              │
              ▼
          State{messages: [历史+当前], user_profile: {...}, user_preferences: {...}}
              │                                    │
              │                          session_context 异步加载
              │                          ← 🧠 MySQL user_profiles / user_preferences
              ▼
          AI Agent
              │
              ├─ trip_planner:  画像→自动补全 theme/pace/special_requests
              │                  Prompt 新增「客户画像」区块
              │                  追问跳过已知偏好 + 「💡 根据您的历史偏好...」提示
              ├─ customer_service: extra_context→国籍/兴趣/语言
              └─ sales_agent:     extra_context→预算/目的地/国籍
```

#### Chrome DevTools E2E 验证

测试用户画像：Japan / Tokyo,Kyoto / Food,Onsen,Temples / relaxed / family / Vegetarian

- ✅ 用户说 "Plan a trip for me" → AI 不再追问 theme/pace/special_requests（画像已覆盖）
- ✅ 回复显示 "💡 根据您的历史偏好，已了解：偏好节奏：relaxed | 兴趣：Food, Onsen, Temples | 同行人：family"
- ✅ 用户补充基本信息（天数/日期/人数/预算）后生成完整行程
- ✅ 行程标题 "京都 3 日深度游行程（素食·温泉·古寺主题）"，餐饮推荐包含 "怀石素食、汤豆腐、精进料理"

#### 同时修复的 Bug（测试过程中发现）

| Bug | 修复 | 文件 |
|-----|------|------|
| Docker 内网 MySQL 端口 3307→3306 | `docker-compose.yml` 加 `MYSQL_PORT=3306` | docker-compose.yml |
| `/profile` 页面路由遮蔽 API 路由 | 删除冗余 HTML 路由（StaticFiles 已提供） | api/main.py |
| `budget_range` dict 未序列化传 SQL | 加入 JSON 序列化字段列表 | services/memory.py |

#### 测试结果

- `pytest tests/test_memory.py tests/test_graph.py tests/test_trip_planner.py tests/test_state.py -v` → **77 个测试全部通过**

---

### Phase 12 ✅ 用户可打断功能——SSE 流式中断 + 补充纠正（2026-08-01）

用户可在 AI 生成过程中随时中断，补充或纠正需求后继续对话，避免等待完整生成或在错误方向浪费 token。

#### 核心改动

| 文件 | 改动 | 说明 |
|------|------|------|
| `frontend/index.html` | +~90 行 | 停止按钮 CSS（脉冲动画）+ HTML + AbortController 中断逻辑 + 中断气泡渲染 |
| `api/main.py` | +5 行 | `_event_stream()` 捕获 `GeneratorExit`/`CancelledError`，优雅处理客户端断开 |

#### 用户操作流程

```
用户发消息 → (▶ 变 ■ 红色脉冲) → AI 开始生成 → SSE 进度事件到达
   ↓
用户发现需要补充/纠正 → 点击 ■
   ↓
fetch AbortController.abort() → SSE 流断开
   ↓
气泡显示「在「正在生成行程…」阶段被中断」+ ⚠ 已中断 badge
输入框恢复可用 + toast "已停止生成，你可以补充或修正后重新发送"
   ↓
用户输入补充/纠正 → 发送 → 新请求包含完整对话上下文 → AI 重新生成
```

#### 技术细节

- **前端**：`AbortController.signal` 绑定到 `fetch()`，点击停止调用 `abort()` → fetch 抛出 `AbortError` → 触发 `_finalizeInterruptedBubble()`
- **中断气泡**：保留已接收的进度标签（如「在「正在生成行程…」阶段被中断」），橙色 badge 标记中断状态
- **后端**：`except (GeneratorExit, asyncio.CancelledError)` 捕获客户端断开，记录日志，让 LangGraph `astream` 随 asyncio 任务取消自然中断
- **上下文保持**：下一轮请求正常加载 MySQL 历史消息 + LangGraph checkpoint，AI 能感知中断前对话

#### 测试结果

- `pytest tests/ -v` → **193 个测试全部通过**，零回归

---

### Phase 12-续 ✅ 打断后上下文丢失修复（2026-08-01）

Chrome DevTools E2E 测试发现打断功能存在上下文丢失：

- 用户发送完整信息（date + pax + budget）→ 打断 → 下一轮 AI 又从头问，不知道已有信息
- **根因 1**：SSE 流被打断后用户消息未保存到 MySQL，下一轮 `_load_chat_history` 读不到
- **根因 2**：`trip_planner._extract_fields()` 只从当前消息 regex 提取，不回溯历史消息

#### 核心改动

| 文件 | 改动 | 说明 |
|------|------|------|
| `api/main.py` | +15 行 | 流开始时预存用户消息到 MySQL（`_event_stream` 开头 `await mm.save_message`）；`_post_chat_save` 新增 `skip_user_message` 参数防止重复保存 |
| `agents/trip_planner.py` | +28 行 | 新增 `_extract_from_history()`——从最近 5 条历史 HumanMessage 中 regex 提取，合并到 `merged_need`（当前消息优先级更高） |

#### 修复后数据流（打断场景）

```
用户: "10月5日，2人，1500美元每人" → 预存到 MySQL ✅
  → AI 开始处理... → 用户打断 🛑

用户: "帮我把重点放在中山陵和总统府"
  → _load_chat_history() 读到上一条消息 ✅
  → _extract_from_history() 提取: arrival_date=10月5日, pax=2, budget=$1500 ✅
  → _extract_fields() 从当前消息提取: special_requests=中山陵/总统府
  → merged_need 完整 → 生成行程 ✅
```

#### E2E 验证

- ✅ 打断后用户消息持久化到 MySQL（Chrome DevTools 确认）
- ✅ 下一轮无需重复提供 date/pax/budget，AI 自动从历史提取
- ✅ 行程生成正确引用所有字段（日期、人数、预算、景点重点）

---

### Phase 13 ✅ 智能客服功能——模式选择器 + FAQ 检索 + 在线/离线流程（2026-08-01）

#### 背景

用户需要切换"行程定制"和"智能客服"两种模式。智能客服走在线/离线流程：在线用知识库 QA 对自动回复，离线走人工工单。

#### 设计思路

**零冗余**——系统已有完整的客服基础设施（`customer_service` agent + `search_faq` RAG + `check_handoff` + `human_handoff`），只需：
1. 新增 `force_branch` 机制跳过意图路由
2. 新增 `mode` 参数控制路由行为
3. 前端添加模式选择器 + 智能客服专用 UI

#### 数据流

```
用户选择"智能客服"模式
  → 前端切换 UI（header / placeholder / 快捷 FAQ）
  → Chat.send() 传 mode: "support"
  → 后端 initial_state.force_branch = "customer_service"
  → route_decision_node 优先检查 force_branch → 直接返回
  → route_condition 跳过意图路由 → customer_service
  → CustomerServiceAgent.run()
      ├── search_faq (Milvus → 关键词 → 英文模糊) → 在线自动回复
      └── check_handoff → need_human → human_handoff → 离线工单
```

#### 改动清单

| 文件 | 改动 | 说明 |
|------|:---:|------|
| `api/schemas.py` | +3 | `ChatRequest` 新增 `mode` 字段（planner/support） |
| `graph/state.py` | +2 | `AgentState` 新增 `force_branch` 字段 |
| `graph/conditions/route_decision.py` | +8 | `route_decision_node` 和 `route_condition` 顶部优先检查 `force_branch` |
| `api/main.py` | +2 | `/chat` 和 `/chat/stream` initial_state 传 `force_branch` |
| `frontend/index.html` | +100 | CSS 模式选择器+快捷 FAQ 标签，HTML 下拉框，JS App 模块+空状态+sendQuick |

**不变文件**：`agents/customer_service.py`、`graph/nodes/customer_service.py`、`graph/nodes/human_handoff.py`、`tools/rag_faq.py`、`tools/mock_handoff.py`、`prompts/customer_service.txt`、`graph/builder.py` 全部零改动。

#### 在线/离线流程

| 阶段 | 机制 | 说明 |
|------|------|------|
| **在线** | `search_faq` → Milvus 向量检索命中 | AI 从知识库检索答案并格式化回复，即时响应 |
| **在线兜底** | Milvus 不可用 → 关键词匹配 `_FALLBACK_FAQ` | 11 类 FAQ 关键词（签证/支付/退改/天气/小费/网络/交通/安全/美食/语言/健康） |
| **离线** | FAQ 无匹配 + 投诉关键词 → `check_handoff` | human_handoff 生成结构化交接单（紧急/普通），用户收到"专员稍后联系"通知 |

#### 前端 UI 细节

- **模式下拉框**：sidebar footer 上方，暗色主题适配，两选项（🗺️ 行程定制 / 🤖 智能客服）
- **智能客服空状态**：🤖 图标 + 说明文字 + 6 个快捷 FAQ 标签（签证材料/支付方式/退改政策/天气查询/交通出行/安全须知）
- **快捷 FAQ**：点击标签 → 自动填入消息并发送
- **模式切换**：header 标题变化 + placeholder 变化 + 空状态变化

#### Chrome DevTools E2E 验证

- ✅ 页面左下角模式下拉框正确渲染
- ✅ 切换到"智能客服"→ header 变为"🤖 智能客服"，placeholder 和空状态切换
- ✅ 点击"签证材料"快捷标签 → 走 `service` 分支 → FAQ 检索成功 → 回复签证信息
- ✅ 输入"我要投诉" → `customer_service` → `check_handoff` 触发 → human_handoff 生成紧急交接单（含客户ID/会话ID/意图分数/执行链审计）
- ✅ 切换回"行程定制"→ header + placeholder + 空状态恢复原状
- ✅ `python -m pytest tests/ -v` → 193 passed

#### 下一步待优化

- 支持 ticket 持久化存储（离线工单表）
- 智能客服多轮对话上下文（独立 conversation 类型）
- 客服满意度评分

---

### Phase 13-续 ✅ 语言选择器恢复 + 5 种语言完整支持（2026-08-01）

#### 背景

前端重构（7f1e3b6）时语言选择器被移除，`language` 硬编码为 `'zh'`。但后端一直保留完整的多语言链路——`ChatRequest.language` → `AgentState.language` → `get_language_instruction()` → Agent system prompt 注入。

现在恢复语言选择器，放在模式下拉框旁边并排显示，支持全球最常用的 5 种语言。

#### 改动清单

| 文件 | 改动 | 说明 |
|------|:---:|------|
| `frontend/index.html` | ~20 | CSS `.sidebar-selectors` flex 并排布局，HTML 语言 `<select>` 并列，JS `App._lang` + `switchLang()` |
| `prompts/__init__.py` | +3 | `_LANG_INSTRUCTIONS` 新增 `hi`（हिन्दी）/ `es`（Español）/ `ar`（العربية）指令 |
| `frontend/index.html` | -1+1 | `Chat.send()` 的 `language` 字段从 `'zh'` 改为 `App._lang` |

#### 语言支持清单

| 代码 | 语言 | 前端 | 系统指令 | 模型原生 |
|------|------|:---:|:---:|:---:|
| `zh` | 🇨🇳 中文 | ✅ | ✅（默认，无需指令） | ✅ qwen 母语 |
| `en` | 🇬🇧 English | ✅ | ✅ | ✅ |
| `hi` | 🇮🇳 हिन्दी | ✅ | ✅（🆕 补上） | ✅ |
| `es` | 🇪🇸 Español | ✅ | ✅（🆕 补上） | ✅ |
| `ar` | 🇸🇦 العربية | ✅ | ✅（🆕 补上） | ✅ |
| `ja` | 🇯🇵 日本語 | 前端未开放 | ✅ | ✅ |
| `ko` | 🇰🇷 한국어 | 前端未开放 | ✅ | ✅ |

#### 数据流

```
用户选择 🇪🇸 Español
  → App.switchLang("es")
  → Chat.send() body: { language: "es", mode: ... }
  → API initial_state["language"] = "es"
  → Agent._get_language(state) → "es"
  → get_language_instruction("es") → "\n[Language] DEBES responder únicamente en español..."
  → system_prompt + lang_instr → qwen 收到强制西班牙语指令
  → "¡Hola! ¿En qué puedo ayudarte con tu viaje?"
```

所有 4 个 Agent（customer_service / trip_planner / sales / operations）均经过 `BaseAgent._run_tool_calling_loop()` → 第 88 行统一注入语言指令，无需逐个修改。

---

### Phase 13-续-2 ✅ 模式视觉区分增强——Bug 修复 + 前端标签/色条/分隔线（2026-08-01）

#### 问题

用户反馈行程定制和智能客服共享对话窗口，消息难以区分归属。排查发现两个层面的问题：

1. **后端 Bug**：4 个 Agent 节点输出的 `current_branch` 使用意图 key（`"service"`）而非节点名（`"customer_service"`），导致前端标签映射失效——既不显示颜色也不显示中文标签
2. **前端欠区分**：仅有底部小字 meta badge，没有模式级别的视觉标记

#### 修复

**后端**（1 个 Bug，6 处修复）：

| 文件 | 改动 |
|------|------|
| `graph/nodes/customer_service.py` | `current_branch`: `"service"` → `"customer_service"` |
| `graph/nodes/trip_planner.py` | `current_branch`: 默认 `"planner"` → `"trip_planner"` |
| `graph/nodes/sales_agent.py` | `current_branch`: `"sales"` → `"sales_agent"` |
| `graph/nodes/operations_agent.py` | `current_branch`: `"operations"` → `"operations_agent"` |
| `agents/trip_planner.py` | 两处 `current_branch`: `"planner"` → `"trip_planner"` |

**前端**（三层视觉增强）：

| 层级 | 机制 | 效果 |
|------|------|------|
| 用户消息上方 | `.mode-badge` 标签 | `🗺️ 行程定制`（紫）/ `🤖 智能客服`（蓝）——标识消息发送时的模式 |
| Agent 气泡内顶部 | `.branch-tag` 标签（12px 加粗） | 替换原底部 11px 小 badge，标签文案与模式名对齐 |
| Agent 左侧 | `data-branch` + 3px 色条 | 紫=行程定制 / 蓝=智能客服 / 红=转人工 / 橙=销售 / 绿=运营 |
| 模式切换 | `.mode-divider` 分隔线 | `──── 🗺️ 行程定制 ────` 自动插入 |

标签文案统一更新：
- `customer_service`: `🤖 客服` → `🤖 智能客服`
- `trip_planner`: `🗺️ 定制` → `🗺️ 行程定制`
- `human_handoff`: `🙋 人工接管` → `🙋 转人工`

#### 验证

Chrome DevTools 实测确认：
- ✅ 用户消息模式标签正确显示（🗺️ 行程定制 / 🤖 智能客服）
- ✅ Agent 左侧色条生效（蓝 `#1890ff` / 紫 `#722ed1`）
- ✅ 气泡内分支标签正确翻译（不再显示原始 key `"service"`）
- ✅ 模式切换时自动插入分隔线

---

### Phase 13-续-3 ✅ 自定义确认对话框——替换浏览器 confirm()（2026-08-01）

#### 问题

删除对话使用浏览器原生 `confirm('确定删除这个对话？')`，系统弹窗风格割裂，体验低端。

#### 实现

新增 `showConfirm(title, message)` 函数，返回 `Promise<boolean>`：
- 半透明遮罩层 + 居中白底卡片
- 标题 + 描述文案
- 取消按钮（灰色）/ 删除按钮（红色）
- 动画：fadeIn 0.2s + slideUp 0.25s
- 交互：点击遮罩关闭 / ESC 键关闭 / 按钮关闭
- `async/await` 无缝替换 `confirm()`，仅改 1 行

改动：`frontend/index.html` 新增 CSS ~25 行 + JS `showConfirm()` ~20 行，`Conversations.remove()` 替换 1 行。

---

### Phase 14 ✅ UI 全局重设计——Skyline 天蓝旅行主题（2026-08-01）

#### 背景

用户要求去掉紫色、使用浅色系、简约风格、贴合旅行主题。

#### 配色方案：Skyline（天际线）

灵感：天空蓝 / 海洋 / 云白 / 轻灰。

| Token | 旧值（Indigo 紫） | 新值（Skyline 天蓝） |
|------|------|------|
| `--primary` | `#6366f1` 靛紫 | `#0ea5e9` 天蓝 |
| `--sidebar-bg` | `#1e1e2e` 暗紫 | `#ffffff` 白色（浅色侧边栏） |
| `--sidebar-text` | `#cdd6f4` 浅紫 | `#334155` 深灰蓝 |
| `--bg` | `#f5f5f5` | `#f1f5f9` 柔和灰蓝 |
| `--text` | `#303133` | `#1e293b` slate-800 |
| `--radius` | `12px` | `10px` 更精致 |
| `--shadow` | `0 1px 3px` | `0 1px 2px` 更轻柔 |
| 登录渐变 | `#667eea → #764ba2` 紫 | `#0ea5e9 → #38bdf8` 天蓝 |

#### 变更范围

| 文件 | 改动 | 说明 |
|------|:---:|------|
| `frontend/index.html` | ~35 处 | CSS 变量、登录渐变、侧边栏浅化（白底+border+浅hover/active）、按钮/标签/色条/下拉框/Toast/圆环色 |
| `frontend/profile.html` | ~6 处 | CSS 变量同步、Toast、按钮色 |

侧边栏专项改造：
- 变量：`#0f172a`→`#ffffff`，`#e2e8f0`→`#334155`，`#1e293b`→`#f1f5f9`
- 分隔线：`rgba(255,255,255,0.06)` → `var(--border)`
- 新对话按钮：半透明白 → 天蓝浅底+天蓝字
- 下拉框：半透明白 → `var(--bg)` 灰底+深色字
- 新增 `border-right: 1px solid var(--border)` 分割主区域

#### 验证

Chrome DevTools 确认所有 CSS 变量正确：
```
--primary: #0ea5e9 │ --sidebar-bg: #ffffff │ --sidebar-text: #334155 │ --bg: #f1f5f9
```

---

### Phase 15 ✅ Token 过期修复 + 环境变量补齐 + 启动流程文档（2026-08-02）

#### 问题

用户启动项目后登录成功，但点击"新对话"时报"令牌无效或已过期"。

**根因**：`Auth.init()` 只检查 localStorage 中是否存在 token，不验证是否过期。用户上次登录 token（24h 有效期）过期后，`Auth.init()` 直接显示主界面，`Conversations.load()` 因 401 静默失败（有 try/catch），用户点击"新对话"时才看到错误。

**附带问题**：`.env` 缺少 JWT_SECRET_KEY、记忆系统配置、TOOL_MODE 等 9 个配置项；启动流程文档不完整。

#### 修复

| 文件 | 改动 | 说明 |
|------|:---:|------|
| `frontend/index.html` | ~10 行 | `api()` 新增 401/403 全局拦截 → 自动清除过期 token 并跳转登录页；新增 `Auth._forceLogout()` 静默清理方法 |
| `.env` | +9 行 | 补齐 `JWT_SECRET_KEY`、`TOOL_MODE`、`CONTEXT_WINDOW_TOKENS`、`CONTEXT_SUMMARY_THRESHOLD`、`CONTEXT_KEEP_RECENT_ROUNDS`、`CHAT_MESSAGE_REDIS_TTL`、`CHAT_MESSAGE_MYSQL_TTL`、`PREFERENCE_EXPIRE_SECONDS` |
| `.env.example` | +1 行 | 补齐 `JWT_SECRET_KEY` |
| `progress.md` | 更新 | Phase 15 记录 + 操作记录追加 |
| `README.md` | 更新 | 启动流程补全 + 常见问题排查 |

#### 启动流程（完整版）

**前置条件**：
- Docker Desktop 已安装并运行
- Python 3.12（仅本地开发）
- 百炼 API Key（阿里云控制台获取）

**Docker 部署（推荐）**：

```bash
# 1. 配置环境
cp .env.example .env
vim .env  # 填入 LLM_API_KEY，其他配置保持默认

# 2. 启动全部 6 个服务
docker-compose up --build -d

# 3. 等待所有服务健康（约 60s）
docker-compose ps  # 确认各服务状态为 healthy

# 4. 导入知识库
docker-compose exec app python scripts/ingest_knowledge.py

# 5. 验证
curl http://localhost:8001/health
# → {"status":"ok","version":"0.3.0","components":{"mysql":"ok","redis":"ok","milvus":{"status":"ok",...}}}

# 6. 浏览器打开 http://localhost:8001
# 7. 注册账号 → 登录 → 新建对话 → 发送消息
```

**本地开发**：

```bash
# 1. 启动基础设施（不含 app）
docker-compose up -d mysql redis etcd minio milvus-standalone
# 等待各服务 healthy

# 2. 配置 .env 使用本地地址
# MYSQL_HOST=localhost, MYSQL_PORT=3307, REDIS_HOST=localhost, MILVUS_HOST=localhost

# 3. 安装依赖
pip install -r requirements.txt

# 4. 导入知识库
python scripts/ingest_knowledge.py

# 5. 启动应用
python -m api.main
# → http://localhost:8000

# 6. 运行测试确认
python -m pytest tests/ -v
```

**常见问题**：

| 现象 | 原因 | 解决 |
|------|------|------|
| "令牌无效或已过期" | Token 过期（>24h）或服务器重启后密钥变化 | 刷新页面自动跳转登录页（Phase 15 已修复） |
| "MySQL not initialized" | Docker MySQL 未启动 | `docker-compose up -d mysql` |
| 端口冲突 (8000/3306) | 宿主机端口占用 | 使用备选端口 8001/3307（docker-compose 已配置） |
| 前端无响应 | API 离线或 CORS 问题 | 检查 `docker-compose ps` 确认 app 容器状态 |
| 知识库检索失败 | Milvus 未就绪 | 等 60s 后重试 `ingest_knowledge.py` |
| 行程生成超时 | qwen3-max 推理慢 (30-120s) | 正常现象，SSE 流式进度会实时显示阶段 |

---

### Phase 16 ✅ 前端模式选择器补齐销售/运营 Agent（2026-08-02）

#### 背景

早期设计文档（`langgraph_agent实现方案.md`）规划了 4 个 Agent：客服、销售、运营、定制。后端 Phase 6 已完整实现了销售和运营 Agent，但它们只能通过意图路由器自动分发到达。前端模式下拉框只有"行程定制"和"智能客服"两个选项，销售和运营被遗漏。

#### 问题

| 维度 | 状态 |
|------|------|
| Agent 后端实现 | ✅ agents/sales_agent.py + agents/operations_agent.py 完整 |
| 图节点注册 | ✅ graph/builder.py 四分支全部接入 |
| 路由条件映射 | ✅ route_decision.py `_BRANCH_MAP` 含 sales/operations |
| **前端模式选择器** | ❌ 仅有 planner + support |
| **API force_branch 映射** | ❌ 仅 "support" → "customer_service"，其他走意图路由 |
| **前端 UI 状态** | ❌ 无 sales/operations 空状态页 |

#### 修复

**后端**（2 文件）：

| 文件 | 改动 |
|------|------|
| `api/schemas.py` | mode 字段描述扩展：`planner=行程定制, support=智能客服, sales=销售咨询, operations=运营处理` |
| `api/main.py` | force_branch 映射从二元改为字典：`{"support":"customer_service", "sales":"sales_agent", "operations":"operations_agent"}`，planner 显式映射到 `trip_planner` |

**前端**（`frontend/index.html`，~60 行）：

| 改动 | 说明 |
|------|------|
| 下拉框新增选项 | `💰 销售咨询` (sales) + `📋 运营处理` (operations) |
| `App.switchMode()` | switch/case 4 路分发，各模式独立 header + placeholder |
| `Chat._showSalesEmpty()` | 🆕 销售空状态：💰 图标 + 4 个快捷标签（报价/库存/签约/优惠） |
| `Chat._showOperationsEmpty()` | 🆕 运营空状态：📋 图标 + 4 个快捷标签（入驻/履约/工单/规则） |
| CSS mode badge | 🆕 `.mode-sales`（橙）+ `.mode-operations`（绿）徽章样式 |
| mode badge 映射 | 从 2 种扩展到 4 种 |
| mode divider 标签 | 从 2 种扩展到 4 种 |

#### 完整模式映射

| 模式 | 前端选项 | force_branch | 目标 Agent | 左侧色条 |
|------|------|------|------|:---:|
| planner | 🗺️ 行程定制 | trip_planner | TripPlannerAgent | 天蓝 `#0ea5e9` |
| support | 🤖 智能客服 | customer_service | CustomerServiceAgent | 蓝 `#2563eb` |
| sales | 💰 销售咨询 | sales_agent | SalesAgent | 橙 `#fa8c16` |
| operations | 📋 运营处理 | operations_agent | OperationsAgent | 绿 `#52c41a` |

#### 验证

- 下拉框 4 个选项正确渲染
- 切换到各模式 → header + placeholder + 空状态正确切换
- force_branch 映射：sales → sales_agent, operations → operations_agent
- 各 Agent 左侧色条颜色一致（已在 Phase 13-续-2 实现）

---

### Phase 17 ✅ 客服 RAG 管道重设计——双路检索 + RRF 融合（2026-08-03）

#### 背景

Phase 7 引入的客服 RAG 检索为单路 Milvus 向量检索，LLM 可选调用 `search_faq` 工具。检索质量依赖单一的余弦相似度排序，存在两个核心缺陷：

1. **缺召回路径**：仅有向量语义检索，缺少 BM25 关键词检索，精确关键词匹配被稀释
2. **无多路融合**：向量检索失败时的回退是简单的子串匹配（`if keyword in query`），粗糙且不稳定

#### 新设计（在线流程）

```
用户问题
  → 意图识别（intent_router → customer_service）
    → Agent 主动执行 search_faq(query)
      ├─ Path A: Milvus/JSON 向量检索（余弦相似度, top_k×2, score≥0.3）
      └─ Path B: BM25 关键词检索（中英文混合分词, top_k×2, per-token≥0.5）
    → RRF 倒数排名融合（k=60, top_k=5）
    → 检索结果注入提示词模板 + 用户原始问题
    → LLM 生成最终回答
```

> 离线入库流程不变：`scripts/ingest_knowledge.py` 仍将知识库摄入 Milvus/JSON。

#### 新建文件

| 文件 | 说明 |
|------|------|
| `tools/bm25_retriever.py` | 纯 Python BM25 实现（~200 行），零外部依赖。中英文混合分词：英文空格+小写，中文 bigram+unigram。IDF + BM25 公式完整实现，自适应 per-token 阈值过滤噪音。模块级单例从 `scripts/knowledge_base` 加载 30 篇文档构建索引 |
| `tools/rrf_fusion.py` | RRF 倒数排名融合（~110 行）。公式 `Σ 1/(k+rank_i)`，k=60。content SHA256 去重防止同一文档在两路获得双重权重，保留多源标记（vector/bm25/vector+bm25） |

#### 重写/修改文件

| 文件 | 改动 |
|------|------|
| `tools/rag_faq.py` | 完全重写。`search_faq(query)` 新流程：并行调用 `search_knowledge()` + `bm25.search()` → RRF 融合 → Markdown 格式化输出（参考资料 1..N + 分类标题 + 来源标记）。三层回退：双路+RRF（主）→ 关键词兜底 → 通用消息。新增 `_MIN_RRF_SCORE=0.015` 质量阈值 |
| `agents/customer_service.py` | 检索前置化重构。Agent 不再等 LLM 决策调用 search_faq，而是在 `run()` 中主动执行检索 → 注入 `{{RAG_CONTEXT}}` 占位符到 system prompt → 一并传入用户画像和原始问题 → LLM 生成回答。check_handoff 仍保留为 LLM 可选工具 |
| `prompts/customer_service.txt` | 新增 `{{RAG_CONTEXT}}` 占位符 + 「回答规范」章节：基于知识库回答、标注不确定性、整合多篇资料、引用来源。移除旧的 tool-calling 流程（search_faq 不再由 LLM 调用） |

#### 测试适配

| 文件 | 改动 |
|------|------|
| `tests/test_customer_service.py` | `test_no_match_fallback` 适配新管道——双路+RRF 检索更积极，未匹配查询也会返回最佳可用内容（验证非空 + 包含参考资料/兜底消息） |
| `tests/test_sales.py` | 已有 Bug 修复：`current_branch` 断言从 `"sales"` 更正为 `"sales_agent"`（2 处） |
| `tests/test_operations.py` | 已有 Bug 修复：`current_branch` 断言从 `"operations"` 更正为 `"operations_agent"`（1 处） |

#### 检索质量对比

| 查询 | Before（单路向量） | After（双路+RRF） |
|------|------|------|
| "签证需要什么材料？" | 1 条向量结果 + 回退 | 5 条融合结果（签证材料 #1 + 签证FAQ #2 + 过境免签 #5） |
| "北京有什么好玩的景点？" | 依赖 Milvus | 北京城市指南 #1（vector+bm25 双命中） |
| "怎么用微信支付？" | 依赖 Milvus | 微信绑定指南 #1 + 支付方式 #2（双路命中） |
| "如何制造一台量子计算机" | 返回通用兜底 | 返回低可信结果（被质量阈值过滤→兜底） |

#### 验证

- 193/193 测试全部通过，零回归
- `python scripts/ingest_knowledge.py --stats` → 30 篇文档，BM25 索引构建成功
- 客服模式 E2E：FAQ 问题返回含参考资料的结构化回答，无原始 `**`/`--` 符号

---

### Phase 18 ✅ MCP 标准化 + 全量真实 API 接入（2026-08-03）

#### 背景

项目此前所有工具（天气/日历/库存/报价/CRM/CAPI）均为 `tools/mock_*.py` 硬编码模拟数据，仅有天气对接了 Open-Meteo 但未标准化调用方式。存在三个核心问题：

1. **工具与 Agent 紧耦合**：Agent 直接 `import` 工具函数，工具崩溃 → Agent 崩溃
2. **无标准化接口**：每个工具的调用方式、参数格式、返回值不一致，加新工具需改 Agent 代码
3. **Mock 数据脱离现实**：天气是假的、报价是固定模板、库存无季节性波动

#### 新架构

```
Agent 调用 tools/mcp_tools.py（LangChain @tool 包装器）
  ↓
MCP Client（子进程管理 + 工具发现 + JSON-RPC 通信）
  │
  ├─ Weather MCP Server   → Open-Meteo 免费天气 API（48 城市实时预报）
  ├─ Calendar MCP Server  → chinese-calendar 中国节假日 + 星期 + 人流量
  ├─ Inventory MCP Server → 48城市×3档酒店×季节性波动系数
  ├─ Quote MCP Server     → 城市日均价×主题溢价×节奏因子×季节系数
  ├─ CRM MCP Server       → MySQL 持久化 CRM 记录
  └─ CAPI MCP Server      → Meta/Google/TikTok 转化事件上报
```

#### 核心设计

##### 1. 自研 MCP 协议——零外部依赖

- JSON-RPC 2.0 over stdio，150 行 Python 实现
- Windows UTF-8 编码兼容（`reconfigure(encoding="utf-8")`）
- 支持 `tools/list`（工具发现）+ `tools/call`（工具调用）

##### 2. 真实 API 数据源

| 工具 | 数据源 | 费用 | 说明 |
|------|--------|------|------|
| get_weather | Open-Meteo | 免费 10,000次/天 | 48城市实时预报，含天气代码→中文映射 |
| query_calendar | chinese-calendar | 免费 | 中国法定节假日/调休自动判断 |
| query_inventory | 本地计算引擎 | 免费 | 48城市×3档酒店基准价 + 季节波动系数(0.7x-1.7x) |
| quote_price | 本地计算引擎 | 免费 | 城市日均基准价 × 主题溢价(0-50%) × 节奏因子(0.8x-1.3x) × 季节系数 |
| update_crm | MySQL 持久化 | 本地 | INSERT ON DUPLICATE KEY UPDATE 幂等写入 |
| send_capi | 广告平台 API | 按需 | Meta CAPI / Google Ads / TikTok Events（未配置Token时仅本地日志） |

##### 3. 三层降级策略

```
MCP Server 在线 → 调用真实 API
  ↓ 离线/超时/崩溃
Mock 实现回退 → 返回模拟数据（功能不中断）
  ↓ mock 也失败
友好错误提示 → "服务暂时不可用，请稍后重试"
```

- 环境变量 `MCP_FORCE_MOCK=1` 强制使用 mock（测试/离线开发）
- 测试环境中 MCP Server 未启动，自动降级到 mock，测试无需修改

##### 4. TripPlanner 工具调用并行化

```
之前: get_weather → query_calendar → query_inventory（串行，3 次阻塞）
现在: asyncio.gather(get_weather, query_calendar, query_inventory)（并行，1 次网络往返）
```

预计响应时间节省 50%+。

#### 文件清单

| 文件 | 操作 | 说明 |
|------|------|------|
| `mcp/__init__.py` | 🆕 | MCP 包 |
| `mcp/server.py` | 🆕 | JSON-RPC 2.0 over stdio 基类（150行，含装饰器语法糖） |
| `mcp/servers/weather_server.py` | 🆕 | 天气 MCP Server（封装 weather_real.py） |
| `mcp/servers/calendar_server.py` | 🆕 | 日历 MCP Server（chinese-calendar + 旅行旺季标注） |
| `mcp/servers/inventory_server.py` | 🆕 | 库存 MCP Server（48城市×季节系数动态计算） |
| `mcp/servers/quote_server.py` | 🆕 | 报价 MCP Server（多因子动态定价引擎） |
| `mcp/servers/crm_server.py` | 🆕 | CRM MCP Server（MySQL 持久化写入） |
| `mcp/servers/capi_server.py` | 🆕 | CAPI MCP Server（Meta/Google/TikTok 多平台上报） |
| `services/mcp_client.py` | 🆕 | MCP Client（子进程管理 + 工具发现 + asyncio 通信） |
| `tools/mcp_tools.py` | 🆕 | MCP → LangChain @tool 包装器（6个工具 + mock 自动回退） |
| `agents/trip_planner.py` | ✏️ | 改用 MCP 工具 + `asyncio.gather` 并行调用 |
| `agents/sales_agent.py` | ✏️ | 改用 MCP 报价/库存工具 |
| `agents/operations_agent.py` | ✏️ | 改用 MCP CRM/CAPI 工具 |
| `api/main.py` | ✏️ | lifespan 中启停所有 MCP Servers |
| `tools/weather_real.py` | 🐛 | 修复 `forecast_days` 超 Open-Meteo 限制（max=16）导致 400 错误 |
| `mcp/server.py` | 🐛 | 修复 Windows 中文输出 GBK 编码乱码（stdout 强制 UTF-8） |

#### 验证

- `echo '{"jsonrpc":"2.0","id":1,"method":"tools/list",...}' | python mcp/servers/weather_server.py` → 返回工具列表正常
- `python -c "from mcp.servers.weather_server import get_weather; print(get_weather('三亚','2026-08-06'))"` → 返回 Open-Meteo 实时数据（雷暴/25.1°C/94%降水）
- `python -c "from mcp.servers.calendar_server import query_calendar; print(query_calendar('2026-10-01'))"` → 正确识别国庆节（National Day）
- `python -c "from mcp.servers.quote_server import quote_price; print(quote_price('北京',5,2,'历史文化','适中','¥'))"` → 返回完整报价单（人均¥4,200，总计¥8,400）
- 193/193 测试全部通过，零回归

---

### Phase 18-续-1 ⌨️ 流式输出打字机效果（2026-08-03）

#### 背景

此前 SSE 端点只发送节点级进度事件（`node_start`/`node_complete`），LLM 调用使用 `httpx.post()` 阻塞等待完整响应，前端虽然已有 `token` 事件处理器和 `_appendStreamingToken()`，但后端从未发送 `token` 事件——导致用户看到的是长时间"⏳ 正在生成行程..."后一次性显示全部文字，没有打字机效果。

#### 修改

| 文件 | 操作 | 说明 |
|------|------|------|
| `services/llm.py` | ✏️ +41行 | 新增 `BailianLLM.astream()`：使用 `httpx.stream()` + `stream: True` → 逐行解析 SSE → `yield` 文本块；同步在 `_ToolBoundLLM` 添加 `astream()` 透传 |
| `services/stream_bridge.py` | 🆕 115行 | `asyncio.Queue` 桥接模块：`push_token(session_id, chunk)` → Agent 推送 token → SSE 端点消费 → 前端渲染。避免 `api.main` ↔ `agents.*` 循环导入 |
| `api/main.py` | 🔄 重写 | SSE 端点重构：`asyncio.create_task(_run_graph())` 后台执行 LangGraph + 推送节点事件/结果到队列；主循环 `await queue.get()` 同时读取 node_start/node_complete/token/done/error 事件 |
| `agents/trip_planner.py` | ✏️ | Step 4 行程生成：`self.llm.astream()` → `push_token(session_id, chunk)` |
| `agents/base.py` | ✏️ +25行 | 新增 `_stream_final()` 方法；`_run_tool_calling_loop()` 接受 `session_id` 参数（为空则退化为普通 ainvoke） |
| `agents/customer_service.py` | ✏️ | `check_handoff` 后的二次 LLM 调用改为 `astream()` + `push_token()` |
| `agents/sales_agent.py` | ✏️ | 传入 `session_id` → 继承 BaseAgent 流式能力 |
| `agents/operations_agent.py` | ✏️ | 同上 |

#### 工作原理

```
Agent → self.llm.astream() → yield token chunk
  → push_token(session_id, chunk) → asyncio.Queue
  → SSE 主循环 await queue.get() → yield event: token → 前端 _appendStreamingToken()
```

Agent 在 LLM 的 `await` 点（网络 I/O）之间自然让出控制权，主循环唤醒并发送 token，实现逐字推送。

---

### Phase 18-续-2 🔄 默认智能路由模式（2026-08-03）

#### 背景

此前前端模式下拉框只有 4 个具体 Agent（planner/support/sales/operations），每个都通过 `force_branch` 强制跳过意图路由。缺少"让系统自动判断"的选项。

#### 修改

| 文件 | 操作 | 说明 |
|------|------|------|
| `frontend/index.html` | ✏️ | 新增 `<option value="auto">🔄 默认</option>` 置顶；`App._mode` 默认值 `'planner'` → `'auto'`；`switchMode()` 新增 `auto` case：显示"🔄 默认 · 智能路由"，引导语"系统会自动匹配最合适的业务专家" |
| `api/main.py` | ✏️ | `force_branch` 映射重构：新增 `"auto": ""`（空字符串触发意图路由）、`"planner": "trip_planner"` 显式写入，消除隐式三元表达式 |
| `api/schemas.py` | ✏️ | `mode` 字段默认值 `"planner"` → `"auto"`，描述更新 |

#### 路由逻辑

```
前端选 "默认" (auto) → force_branch = "" → route_decision_node 跳过 force 分支
                                              ↓
                              意图分数路由（惯性偏向 + 最高分 → 目标 Agent）

前端选具体 Agent       → force_branch = "xxx_agent" → 跳过意图识别，直接锁定该 Agent
```

`graph/conditions/route_decision.py` **零改动**——当 `force_branch` 为空时，已有的意图分数路由逻辑自动接管。

---

### Phase 18-续-3 🏷️ 进度标签中文化（2026-08-03）

#### 背景

SSE 进度推送中，`route_decision` 节点不在 `NODE_LABELS` 字典里，走 fallback `f"正在执行 {node_name}..."` 把英文内部名直接暴露给前端——用户看到"正在执行 route_decision..."。

#### 修改

| 位置 | 之前 | 之后 |
|------|------|------|
| `NODE_LABELS` 字典 | 缺 `route_decision` | 新增 `"route_decision": "正在匹配业务专家..."` |
| fallback 逻辑 | `f"正在执行 {node_name}..."` | `"正在处理..."` |

现在所有 12 个图节点都有中文标签，未来新增节点忘了加映射也只显示通用"正在处理..."，不再泄露英文内部名。


### Phase 19 🔍 查询改写节点（2026-08-04）

#### 背景

用户输入"bei jing 3天 2 person"、"我想去shanghai玩5days"等中英混杂/拼音/错别字，直接进入意图路由会导致分类偏差和后续字段提取不准确。在路由前加一层 LLM 纠错改写，能显著提升全链路准确率。

#### 图结构变更

```
之前: START → input_guard → session_context → intent_router → route_decision
现在: START → input_guard → session_context → query_rewrite → intent_router → route_decision
```

#### 新增文件

| 文件 | 说明 |
|---|---|
| `graph/nodes/query_rewrite.py` | 查询改写节点——提取最后一条用户消息 → LLM 纠错规范化 → 替换消息内容 |
| `prompts/query_rewrite.txt` | 改写 LLM 系统提示词——拼音转中文、中英混杂统一、错别字修正、省略语义补充 |

#### 修改文件

| 文件 | 变更 |
|---|---|
| `graph/state.py` | 新增 `original_query` 字段（改写前的原始输入，用于调试审计）+ 字段所有权表更新 |
| `graph/builder.py` | 注册 `query_rewrite` 节点 + 重连 `session_context → query_rewrite → intent_router` + ASCII 图更新 |
| `api/main.py` | 新增 `"query_rewrite": "正在理解需求..."` 中文进度标签 |
| `tests/test_graph.py` | REQUIRED_NODES 新增 query_rewrite、edge 测试更新链 |

#### 优化设计

- **快速跳过**：短确认（"好的"、"嗯"、"OK"）和已规范中文（无英文/拼音混杂）直接跳过，不消耗 LLM 调用
- **拼音检测**：`_has_rewrite_need()` 检查英文字母、中英混杂、拼音模式，仅在必要时调用 LLM
- **防御兜底**：LLM 调用失败时保留原文，不影响对话流程
- 使用 `get_light_llm()`（qwen-turbo），单次改写 ~200ms

#### 改写效果验证

| 原始输入 | 改写结果 |
|---|---|
| `bei jing 3天 2 person` | `北京3天2人行程` |
| `我想去shanghai玩5days，budget 2000 USD` | `我想去上海玩5天预算2000美元` |
| `我想去西安玩4天，8月15号到，2个人` | 不变（已规范，跳过 LLM） |


### Phase 19-续 💰 模型分层——成本优化（2026-08-04）

#### 背景

此前所有 4 个 Agent（客服、销售、运营、行程定制）全部使用 `qwen3-max`（最强、最贵模型）。客服 FAQ 检索回答、运营 CRM/CAPI 工具调用这类轻量任务完全不需要最强模型，造成大量不必要的 API 费用。

#### 三层模型架构

| 层级 | 工厂函数 | 模型 | 适用场景 | 百炼定价 |
|---|---|---|---|---|
| Light | `get_light_llm()` | qwen-plus | 客服、运营、查询改写（需多工具 function calling） | ¥0.8 入 / ¥2 出 |
| Mid | `get_router_llm()` | qwen-plus | 销售、路由、意图打分 | ¥0.8 入 / ¥2 出 |
| Heavy | `get_agent_llm()` | qwen3-max | 行程定制 | 贵 3-5× |

所有模型均支持 function calling，`_run_tool_calling_loop` 零改动。

> **⚠️ 2026-08-05 更新**：Light 层默认模型从 `qwen-turbo` 升级为 `qwen-plus`——因 qwen-turbo 仅支持单工具 function calling，销售 Agent（6 tools）和运营 Agent（12 tools）会触发 API 400 错误。详见操作记录 Phase 21-续-2。

#### 修改文件

| 文件 | 变更 |
|---|---|
| `services/llm.py` | 新增 `get_light_llm()` 工厂函数（默认 qwen-plus，后从 qwen-turbo 升级——因 qwen-turbo 不支持多工具 function calling）+ 模型分层文档 + 环境变量 `LIGHT_MODEL`/`LIGHT_TEMPERATURE`/`LIGHT_MAX_TOKENS` |
| `agents/customer_service.py` | `get_agent_llm` → `get_light_llm` |
| `agents/operations_agent.py` | `get_agent_llm` → `get_light_llm` |
| `agents/sales_agent.py` | `get_agent_llm` → `get_router_llm` |
| `graph/nodes/query_rewrite.py` | `get_router_llm` → `get_light_llm` |
| `tests/test_operations.py` | Patch 路径更新 `get_agent_llm` → `get_light_llm` |

#### 成本节约

客服、运营、销售三个 Agent 从 qwen3-max → qwen-plus，**每次对话成本降低约 85-90%**。

环境变量覆盖：
```bash
LIGHT_MODEL=qwen-plus   # 想把轻量级任务也升到中档模型
```

### Phase 20 🛒 销售 Agent 重设计——Pipeline 状态机 + 分阶段销售 + 跟进策略（2026-08-04）

#### 背景

旧销售 Agent 是一个带假报价工具的聊天机器人：LLM 可选调用 `quote_price`/`query_inventory`（mock），然后用关键词 if-else 打分判定意向等级。它完全不利用已有的行程方案数据（`draft`/`need`），没有销售 Pipeline 概念，没有跟进能力，没有下单支付链路。

#### 新设计

**Pipeline 五阶段模型**：

```
LEAD ──→ QUALIFIED ──→ NEGOTIATION ──→ CLOSING ──→ WON
  │         │   │          │              │           │
  │         │   └── 3d ──→ 优惠           │           │
  │         │   └── 7d ──→ LOST           │           │
  └─────────┴─────────────────────────────┴───────────┘
```

| 阶段 | 用户状态 | 销售策略 |
|---|---|---|
| LEAD | 有购买意向但无行程方案 | 引导先去 trip_planner 设计行程 |
| QUALIFIED | 已有行程方案，在考虑 | 回顾行程亮点 + 挖掘顾虑 |
| NEGOTIATION | 谈价格/调整内容 | 处理异议 + 分项优惠 |
| CLOSING | 明确要买 | 生成报价 + 创建订单 + 支付链接 |
| WON | 已支付 | 确认订单 + 后续流程 |
| LOST | 7 天未转化或明确拒绝 | 留台阶 |

**核心能力**：
- **分阶段 Prompt**：4 个阶段各自独立的销售话术策略（LEAD/QUALIFIED/NEGOTIATION/CLOSING），动态加载
- **行程回顾**：SalesAgent 加载 `draft` + `need` → 注入 Prompt，销售能精准引用行程内容
- **行程修改检测**：用户说"改一下行程"→ `goto_planner=true` → after_sales 路由到 trip_planner → 改完回来继续销售
- **跟进策略**：24h 温和追问 → 3d 小额优惠（机票/酒店/门票选 1-2 项）→ 7d 自动放弃
- **激进但不冒犯**：每次回复末尾给提示/选项，主动追问顾虑，但等用户回复

**5 个新销售工具**（Mock）：

| 工具 | 用途 |
|---|---|
| `load_trip_draft` | 跨会话加载查看行程方案 |
| `create_order` | 创建订单记录 |
| `get_payment_url` | 生成 Mock 支付链接 |
| `apply_coupon` | 分项优惠券（酒店/机票/门票选 1-2 项） |
| `check_order_status` | 查询用户订单状态 |

#### 新建文件

| 文件 | 说明 |
|---|---|
| `tools/mock_sales.py` | 5 个销售 Mock 工具（~180 行） |
| `prompts/sales_lead.txt` | LEAD 阶段 Prompt——引导去定制行程 |
| `prompts/sales_qualified.txt` | QUALIFIED 阶段 Prompt——回顾行程 + 挖掘顾虑 |
| `prompts/sales_negotiation.txt` | NEGOTIATION 阶段 Prompt——异议处理 + 优惠策略 |
| `prompts/sales_closing.txt` | CLOSING 阶段 Prompt——报价 + 下单 + 支付 |

#### 修改/重写文件

| 文件 | 变更 |
|---|---|
| `agents/sales_agent.py` | **完全重写**（~300 行）。Pipeline 状态机 + 分阶段 Prompt 动态加载 + 跟进消息生成 + 行程修改检测 + 阶段转换判定。删除旧 `_score_intent()` 关键词打分 |
| `graph/state.py` | 新增 5 个字段：`sales_pipeline_stage`、`sales_context`、`has_unconverted_trip`、`previous_draft_id`、`goto_planner` + 字段所有权表更新 |
| `graph/conditions/after_sales.py` | 重写。新增 trip_planner 路由：`need_human > goto_planner > won > lost > end` |
| `graph/nodes/session_context.py` | 新增销售跟进检测：查询 `sales_pipeline` 表 → 24h 未活动设 `has_unconverted_trip=true` → 7d 自动标记 LOST |
| `graph/nodes/intent_router.py` | `has_unconverted_trip=true` 时给 sales 分数 ×1.5 加权 |
| `graph/nodes/sales_agent.py` | 适配新返回结构（pipeline_stage + goto_planner + agent_traces） |
| `graph/builder.py` | after_sales 条件边新增 trip_planner 路由 |
| `tools/mcp_tools.py` | 注册 5 个新工具（MCP→Mock 降级模式） |
| `services/memory.py` | 新增 5 个 Pipeline CRUD 方法 + `_row_to_pipeline()` 解析辅助 |
| `scripts/migrate_mysql.sql` | 新增 `sales_pipeline` 表（跟踪用户购买漏斗阶段） |
| `tests/test_sales.py` | **完全重写**（43 测试）。工具/Pipeline/跟进/条件边/节点 全覆盖 |
| `tests/conftest.py` | 新增 `sales_qualified_state` fixture（带 draft 的销售状态） |
| `prompts/sales_agent.txt` | **删除**——被 4 个分阶段 Prompt 替代 |

#### 图结构变更

```
after_sales 路由（旧）: human_handoff / operations_sync / end
after_sales 路由（新）: human_handoff / trip_planner / operations_sync / end

新增路径: sales_agent → trip_planner（用户要修改行程）
         → trip_planner 改完 → intent_scorer → revision_decision → 可回到 sales
```

#### 验证

- 215/215 测试全部通过，零回归
- 43 个销售专项测试：工具（11）+ MCP 注册（5）+ Pipeline 阶段判定（7）+ 行程修改检测（2）+ 跟进策略（4）+ 条件边（8）+ 节点（6）


### Phase 21-续-3 🌐 E2E 测试 3 项修复（2026-08-05）

Chrome DevTools E2E 全功能测试发现 3 个问题，均已修复。

#### 修复 1: P0 西班牙语回复中文——多语言指令增强

**问题**：选择 Español 语言后，AI 收到西班牙语用户消息但用中文回复。

**根因**：
1. `customer_service.py` 最终回答指令（"请基于以上知识库检索结果和用户画像…"）始终为中文，会覆盖前面的语言指令
2. 投诉关键词仅支持中文（"投诉/退款/骗人"），非中文用户投诉无法触发转人工

**修复**（`agents/customer_service.py`）：
- 最终回答指令改为 7 语言映射表（`_lang_instructions` dict），根据 `language` 参数注入对应语言
- 投诉关键词扩展为 7 语言：中文/English/Español/日本語/한국어/हिन्दी/العربية

#### 修复 2: P1 Profile 页面路由冲突

**问题**：`GET /profile` 返回 JSON（API 端点），用户无法通过 `/profile` URL 访问画像页面。

**根因**：API 端点 `/profile`（需认证返回 JSON）与前端页面 `/profile`（应返回 HTML）路由冲突。Phase 11 的修复删除了 HTML 路由（误以为 StaticFiles 会处理），但 StaticFiles 不自动追加 `.html` 后缀。

**修复**（3 文件）：
- `api/main.py`：API 端点路径 `GET/PUT /profile*` → `GET/PUT /api/profile*`；新增 `GET /profile` 返回 `profile.html` 页面（无需认证）
- `frontend/profile.html`：所有 API 调用路径 `/profile*` → `/api/profile*`
- `frontend/index.html`：侧边栏画像链接 `/static/profile.html` → `/profile`

#### 修复 3: P1 ROUTER_MODEL 不一致

**问题**：`.env.example` 文档建议 `ROUTER_MODEL=qwen-plus`，但 `.env` 实际值为 `qwen-turbo`，且销售 Agent 实际使用 `get_light_llm()`（受 LIGHT_MODEL 控制）。

**修复**（2 文件）：
- `.env`：`ROUTER_MODEL` 从 `qwen-turbo` 修正为 `qwen-plus`
- `services/llm.py`：新增 `reset_all_singletons()` 函数（免重启切换模型单例）+ `_build_body()` 调试日志（记录 model + tool_count）
- `api/main.py`：启动日志新增 LLM Light 行

#### 验证

- 243/243 测试全部通过，零回归
- 5 文件修改：`agents/customer_service.py`、`api/main.py`、`frontend/profile.html`、`frontend/index.html`、`services/llm.py`


### Phase 21-续-4 🔧 E2E 全功能测试——4 个 Bug 修复（2026-08-05）

Chrome DevTools 全功能 E2E 测试（行程定制/智能客服/销售/多语言/画像/打断/模式切换/语言切换），发现并修复 4 个问题。

#### 修复 1: P0 MCP Server 死锁——应用无法启动

**问题**：Docker 容器中应用启动后，`/health` 端点始终返回空响应，浏览器无法访问。

**根因**：`MCPServerConnection.start()` 持有 `self._lock`（asyncio.Lock，非可重入）后调用 `self._send_request("initialize", ...)`，后者也尝试获取同一个锁 → 死锁。全部 6 个 MCP Server 启动全部卡死，阻塞 FastAPI lifespan（`yield` 前的 `await mcp.start_all()` 永远不返回），导致 uvicorn 无法开始处理 HTTP 请求。

**修复**（`services/mcp_client.py`）：
- `self._lock` 拆分为 `self._lifecycle_lock`（保护 start/stop）和 `self._request_lock`（保护 stdin/stdout 请求通信）
- `start()` 和 `stop()` 使用 `_lifecycle_lock`
- `_send_request()` 使用 `_request_lock`

**验证**：修复后所有 6 个 MCP Server 在 1 秒内全部初始化成功，health 返回 200 OK。

#### 修复 2: P1 Profile 页面 Pydantic 验证错误

**问题**：`GET /profile` 页面显示 "加载失败: 获取画像失败: budget_range Input should be a valid dictionary or instance of BudgetRange, input_value='$1500/人'"。

**根因**：`_row_to_profile()` 虽有 JSON 解析容错（`json.loads` 失败→None），但 Redis 缓存中存储了历史脏数据（`budget_range` 为纯字符串 `"$1500/人"` 而非 JSON dict），`get_cached_user_profile` 直接返回缓存数据不经过 `_row_to_profile` 的解析。

**修复**（`api/main.py`）：
- `/api/profile` 端点新增 sanitization 步骤：缓存/MySQL 加载后，检查 `budget_range` 是否为合法 dict，非 dict 则尝试 `json.loads` 解析，失败则置 None
- 清除 Redis 脏缓存 `DEL profile:user-8ac39be47478`

#### 修复 3: P1 销售/运营 Agent 调用百炼 API 400 错误

**问题**：销售 Agent（6 tools）和运营 Agent（12 tools）调用百炼 API 返回 400 错误：`"human is not one of ['system', 'assistant', 'user', 'tool', 'function']"`。

**根因**：`_langchain_role()` 函数中，当 LangChain 消息对象有 `type` 属性时直接返回该值（如 `"human"`、`"ai"`），未映射到 OpenAI 兼容格式（`"user"`、`"assistant"`）。之前客服/行程定制 Agent 不受影响是因为它们使用 `_get_user_message()` 提取纯文本后构建新消息（dict 格式），不会携带 LangChain 消息的 `type` 属性；而销售/运营 Agent 通过 `_get_message_history()` 直接传递 State 中的 LangChain 消息对象，触发此 Bug。

**修复**（`services/llm.py`）：
- `_langchain_role()` 在 `msg.type` 路径中新增 type 映射表：`{"human": "user", "ai": "assistant", "system": "system", "tool": "tool", "function": "function"}`

#### 修复 4: P2 缺少 3 张数据库表

**问题**：销售 Pipeline 保存时报 `Table 'travel_agent.sales_pipeline' doesn't exist`；运营订单/工单表同理。

**根因**：Phase 20-21 新增的 `sales_pipeline`、`orders`、`tickets` 三张表的 DDL 存在 `scripts/migrate_mysql.sql` 中，但该脚本仅在 MySQL 容器**首次初始化**（volume 为空）时执行。已有 volume 的数据库不会自动创建新表。

**修复**：手动执行 DDL 创建三张表（已包含在 `migrate_mysql.sql` 中，后续重建容器时会自动创建）。

#### 测试覆盖

Chrome DevTools E2E 测试通过：
- ✅ 模式切换（5 种：默认/行程定制/智能客服/销售咨询/运营处理）
- ✅ 语言切换（中文 → Español，AI 完整西班牙语回复）
- ✅ 智能客服 FAQ（双路 RAG 检索 + 签证材料详细回答）
- ✅ 投诉转人工（结构化紧急交接单 + Agent 执行链）
- ✅ 行程定制 SSE（逐 token 流式 + 精美 Markdown 渲染）
- ✅ 打断功能（停止按钮 + ⚠已中断标签 + 输入框恢复）
- ✅ 销售 Pipeline（QUALIFIED 阶段话术 + 用户画像引用）
- ✅ 用户画像页面（基础信息 + 旅行偏好完整展示）

#### 验证

- 243/243 测试全部通过，零回归
- 3 文件修改：`services/mcp_client.py`、`services/llm.py`、`api/main.py`
- 手动操作：Redis 缓存清理 `DEL profile:*` + MySQL DDL 建表


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
| 2026-07-29 | Phase 1：创建 AgentState、LLM 工厂、3 个图节点、路由条件 | ✅ |
| 2026-07-29 | Phase 2：意图路由器改用 with_structured_output | ✅ |
| 2026-07-29 | 更新 main.py 添加 test 模式，4 组测试用例 | ✅ |
| 2026-07-29 | Phase 3：客服 Agent（LLM+Tools）+ 人工接管（交接单）+ after_service 条件边 | ✅ |
| 2026-07-29 | Phase 4：定制 Agent（需求提取+草案生成）+ 修订循环 + 意向评分 | ✅ |
| 2026-07-29 | Phase 5：终态写入（operations_sync + CRM/CAPI）+ /chat API 联调，MVP 完成 | ✅ |
| 2026-07-30 | Phase 6：销售 Agent（报价+意向评分）+ 运营 Agent（入驻+履约+工单），四分支完整版 | ✅ |
| 2026-07-30 | Phase 7：RAG 增强——百炼 Embedding + 纯 Python 向量存储 + 30 篇知识库文档 | ✅ |
| 2026-07-30 | Phase 8：基础设施升级——模型升级 qwen3-max + embedding-v4，Milvus 向量库，MySQL 8.0 + Redis 7，Docker 全容器化（6 服务），MySQL Checkpoint Saver，static→frontend 重命名 | ✅ |
| 2026-07-30 | Phase 8 调试：Docker 启动修复（MinIO 健康检查、端口冲突、MySQL DDL 主键长度），向量存储改为 Milvus REST + JSON 双模式，移除 pymilvus 依赖，全链路验证通过 | ✅ |
| 2026-07-30 | Phase 9：SSE 流式输出——新增 `/chat/stream` 端点 + LangGraph astream(updates) + 前端 SSE reader + 进度 UI + `/chat` 降级回退，零 Agent 侵入 | ✅ |
| 2026-07-31 | 工程优化：合并 main.py → api/main.py（统一入口，保留 test 模式）；.env 同步 .env.example（补齐 18 个缺失配置项，AGENT_MODEL 更新为 qwen3-max） | ✅ |
| 2026-07-31 | 测试补齐：新增 6 个测试文件（conftest + state + graph + router + customer_service + trip_planner），107 个用例全部通过，覆盖条件边/工具/节点/State/图结构 | ✅ |
| 2026-07-31 | 架构优化：① 去 langchain-openai 依赖，改用 httpx 直连百炼（BailianLLM，~350 行）；② Agent 全异步化（async run + llm.ainvoke）；③ Tool-calling 样板代码提取到 BaseAgent._run_tool_calling_loop()，3 个 Agent 从 ~90 行缩减到 ~30 行；④ 多语言支持（zh/en/ja/ko），语言指令注入 + 前端语言选择器 | ✅ |
| 2026-07-31 | 测试补全：新增 test_sales.py（21 用例）+ test_operations.py（14 用例），总测试数 142 个全部通过（~6s）。AsyncMock 适配异步节点 | ✅ |
| 2026-07-31 | 前端重构 + 登录 + 模型升级：① 前端仿 DeepSeek 布局（侧边栏对话列表 + 多对话窗口 + 注册/登录/退出），丢弃快速测试面板；② 新增认证系统（JWT + bcrypt，3 个新文件：api/auth.py、api/dependencies.py、services/user_store.py）；③ 新增对话管理 API（CRUD + 历史消息）；④ 意图路由模型 qwen-turbo → qwen-plus；⑤ api/schemas.py session_id → conversation_id；⑥ 版本号 0.2.0 → 0.3.0 | ✅ |
| 2026-07-31 | Chrome DevTools E2E 测试 + Bug 修复：① passlib 与新版 bcrypt 不兼容 → 改用 bcrypt 直接调用；② Python getattr 急切求值导致 StructuredTool.__name__ 崩溃 → 改用 hasattr 判断；③ 前端 API_BASE 改为相对路径适配同源部署。全链路验证：登录/注册/多对话/SSE 流式/行程定制/删除对话/退出 均通过 | ✅ |
| 2026-07-31 | 三项优化：① Milvus REST API v1→v2 路径修复（/api/v1/ → /v2/vectordb/），新增 dbName 参数 + 3 次重试 + 增强日志，彻底解决回退到 JSON 问题；② Mock 工具升级：新增 Open-Meteo 真实天气 API（45 城、零 API Key）、TOOL_MODE 双模式切换、日历扩展节假日到 2027 年、5 个真实接口骨架文件（inventory/quote/crm/capi）；③ 测试补齐：新增 test_auth.py（17 用例）、test_conversations.py（9 用例）、test_api.py（9 用例），总测试数 142 → 177 | ✅ |
| 2026-07-31 | 共享黑板 v2 重构：① AgentState 新增 HandoffContext + AgentTrace 类型 + 3 个字段（handoff / agent_traces / branch_history），用结构化上下文替代裸 need_human 判断；② 字段所有权契约——每个字段明确 owner 节点，追加型字段使用 _append_list reducer；③ route_decision 拆为节点+条件（解决条件边不能写 State 的 LangGraph 限制），分支切换时自动重置 intent_level/next_action 防止跨分支污染；④ 7 个节点写入 agent_traces 审计日志，4 个节点写入 handoff 上下文（含 from_agent + reason + priority + summary），human_handoff 交接单包含优先级标签+报价单+Agent 执行链；⑤ 12 个文件改动，177 测试全部通过 | ✅ |
| 2026-07-31 | 意图路由修复 + AI 格式美化：① 新增预过滤器 _prefilter_user_message()——12 种能力询问 + 6 种寒暄正则匹配后跳过 LLM，直接返回 service=0.95 / need_human=false，解决"你能干什么"等被误判转人工；② Prompt 增强：intent_router.txt 新增能力询问/寒暄/道谢规则，收紧 need_human 触发条件，防止历史上下文污染；customer_service.txt 新增平台 5 大能力介绍，客服可直接介绍系统功能；③ 投诉优先级判断从 LLM service>0.7 改为 _has_complaint_intent() 关键词匹配，区分"我要投诉"（urgent）vs"投诉流程"（FAQ）；④ human_handoff.py 用 Markdown 标题+`---` 分隔线替代 ASCII `====`/`----` 符号，意图分数格式化为 'service=90%' 可读格式；⑤ 前端 simpleMarkdown 增强——代码块/分隔线/列表包裹/粗体/标题 h1-h3；CSS 新增 agent 气泡内 Markdown 样式（h1/h2/h3/hr/ul/li/code/pre/strong/p） | ✅ |
| 2026-08-01 | Phase 11：短/中/长期记忆系统——① 对话消息 Redis+MySQL 双写，切换窗口不丢失；② 上下文窗口管理（qwen3-max 32K tokens，超 70% 触发 LLM 摘要）；③ 中期偏好提取（LLM structured output，每 5 轮触发，60 天 TTL）；④ 长期用户画像（永久保存 + /profile 页面 + LLM 建议→用户确认）；⑤ 新增 5 个文件/修改 7 个文件，graph/agents/tools 零改动；⑥ 193 测试全部通过 | ✅ |
| 2026-08-01 | Chrome DevTools E2E 测试 + Bug 修复：① Docker 内网 MYSQL_PORT=3307 导致 MySQL 连接失败 → docker-compose.yml 覆盖为 3306；② `/profile` 页面路由遮蔽 API 端点（`GET /profile` 同时有 HTML 页面和 API 两个 handler）→ 删除冗余 HTML 路由（StaticFiles 已提供）；③ `budget_range`（Pydantic BudgetRange 对象）model_dump 后为 dict 未序列化直接传 SQL → memory.py 加入 JSON 序列化字段；④ 全链路验证：注册/登录/消息发送/对话切换/画像编辑 均通过 | ✅ |
| 2026-08-01 | Phase 11-续：AI 记忆注入——① AgentState 新增 user_profile/user_preferences 字段；② session_context 改为异步节点，从 MemoryManager 加载记忆；③ trip_planner：画像自动补全 theme/pace/special_requests → 减少追问 + 「💡 根据您的历史偏好...」提示 + Prompt 新增「客户画像」区块；④ customer_service/sales_agent：extra_context 注入国籍/兴趣/预算；⑤ `/chat` `/chat/stream` 端点从 MySQL 加载历史消息回退（checkpoint 空时）；⑥ Chrome DevTools E2E 验证：AI 生成行程引用画像数据（素食·温泉·古寺主题）；⑦ 7 个文件改动，77 个测试通过 | ✅ |
| 2026-07-31 | CSS flexbox 修复 + Markdown 块解析重写：① 用户消息框跑左边 Bug——width:100%+row-reverse+justify-content:flex-end 在反转轴上指向左侧，回退 max-width:80%+align-self:flex-end 方案；② --- 和 ### 显示为原始文本——后端所有 --- 与 ### 之间补空行（标准 Markdown 块分隔），前端重写为按 \n\n+ 分块解析（h1/h2/h3/hr/ul/pre/p 独立判断），块首遇 --- 自动拆分；③ Markdown 间距收紧：p { margin:0 }、p+p { margin-top:6px }，h1/h2/h3/hr/ul 间距收紧，首尾元素 margin 归零 | ✅ |
| 2026-08-01 | Phase 12：用户可打断功能——① 前端新增停止按钮（红色脉冲动画），AbortController 中断 SSE 流，中断气泡保留进度阶段 + ⚠ 已中断 badge；② 后端 `_event_stream()` 捕获 GeneratorExit/CancelledError 优雅处理客户端断开；③ 用户可随时中断 AI 生成、补充纠正后继续对话，上下文不丢失；④ 2 个文件改动，193 测试全部通过 | ✅ |
| 2026-08-01 | Phase 12-续：打断后上下文丢失修复——① SSE 流开始时预存用户消息到 MySQL（防止打断后历史缺失）；② `_post_chat_save` 新增 `skip_user_message` 防止重复保存；③ trip_planner 新增 `_extract_from_history()` 从历史消息 regex 提取需求字段（date/pax/budget），打断后无需重复提供；④ Chrome DevTools E2E 验证通过；⑤ 2 文件改动，193 测试全部通过 | ✅ |
| 2026-08-01 | Phase 13：智能客服功能——① 前端左下角模式切换下拉框（🗺️ 行程定制 / 🤖 智能客服），智能客服空状态含 6 个快捷 FAQ 标签；② 后端 `force_branch` 跳过意图路由直连 customer_service；③ 在线：search_faq (Milvus→关键词→英文模糊) 自动回复；④ 离线：check_handoff→human_handoff 生成紧急交接单；⑤ 5 个文件改动，agents/tools/prompts/graph/builder 零改动，193 测试全部通过；⑥ Chrome DevTools E2E 验证通过 | ✅ |
| 2026-08-02 | Phase 15：Token 过期修复——① 前端 api() 全局拦截 401/403 → 自动清除过期 token + 跳转登录页（Auth._forceLogout()），解决 Auth.init() 不验证 token 有效性导致主界面看到但操作失败的 Bug；② .env / .env.example 补齐 JWT_SECRET_KEY 和记忆系统 9 个缺失配置项；③ progress.md + README.md 补全完整启动流程（Docker/本地开发）+ 8 个常见问题排查 | ✅ |
| 2026-08-02 | Phase 16：前端模式选择器补齐销售/运营 Agent——① 后端 api/schemas.py mode 字段文档 + api/main.py force_branch 映射扩展至全部 4 种模式；② 前端下拉框新增 💰 销售咨询 + 📋 运营处理；③ 各模式独立空状态页 + 快捷标签；④ CSS 新增 mode-sales/mode-operations 徽章样式；⑤ **Bug 修复**：SSE 流式端点 `stream_mode="updates"` 只返回最后节点部分输出导致 `current_branch` 为 null → 改用 `aget_state()` 从 checkpoint 拉取完整 State；⑥ **Markdown 渲染重构**：从块级分类改为逐行扫描引擎——修复列表内 `**粗体**` 不渲染、标题与列表同块时列表被跳过、单换行列表项无法识别三个核心 Bug，新增有序列表 + 引用块支持 | ✅ |
| 2026-08-03 | Phase 17：客服 RAG 管道重设计——① 新建 `tools/bm25_retriever.py`（纯 Python BM25，中英文混合分词，30 篇文档索引）；② 新建 `tools/rrf_fusion.py`（RRF 倒数排名融合 k=60，content hash 去重）；③ 重写 `tools/rag_faq.py`（双路并行检索→RRF→Top-K→Markdown 格式化）；④ 重写 `agents/customer_service.py`（检索前置化——Agent 主动执行 RAG→注入 prompt→LLM 回答）；⑤ 更新 `prompts/customer_service.txt`（RAG_CONTEXT 占位符+回答规范）；⑥ 测试适配 3 文件（test_customer_service/test_sales/test_operations），193 测试全部通过 | ✅ |
| 2026-08-03 | Phase 18：MCP 标准化 + 全量真实 API 接入——① 自研轻量 MCP 协议（JSON-RPC 2.0 over stdio，Windows UTF-8 兼容），6 个独立 MCP Server 子进程（weather/calendar/inventory/quote/crm/capi）；② 真实 API 数据源：Open-Meteo 免费天气（48城市）、chinese-calendar 中国节假日、48城市×3档酒店×季节性波动库存引擎、城市日均价×主题溢价×节奏因子报价引擎、MySQL CRM 记录写入、Meta/Google/TikTok CAPI 转化事件上报；③ MCP Client 子进程管理（自动启动/崩溃重启/工具发现/三层降级：MCP→mock→错误提示）；④ `tools/mcp_tools.py`：MCP → LangChain @tool 透明包装器，Agent 零感知切换；⑤ TripPlanner 工具调用从串行改为 `asyncio.gather` 并行（3→1 个网络往返）；⑥ 4 个 Agent 全部改用 MCP 工具（trip_planner/sales_agent/operations_agent/customer_service 不变）；⑦ lifespan 中启停 MCP Servers；⑧ 修复 weather_real.py forecast_days 超限 400 错误；⑨ 修复 mcp/server.py Windows GBK 编码兼容 | ✅ |
| 2026-08-03 | Phase 18-续-1：流式输出打字机效果——① 新增 `BailianLLM.astream()`（httpx.stream + stream:True）；② 新建 `services/stream_bridge.py`（asyncio.Queue 桥接 Agent↔SSE）；③ SSE 端点重构（后台图任务 + 主循环读队列→发送 token 事件）；④ 4 个 Agent 全部支持流式（TripPlanner itinerary/CustomerService check_handoff/Sales+Operations BaseAgent）；⑤ 前端已有 token 处理器直接生效 | ✅ |
| 2026-08-03 | Phase 18-续-2：默认智能路由模式——① 前端新增"🔄 默认"选项置顶（App._mode 默认 auto）；② force_branch 映射重构（auto→""、planner→trip_planner 显式）；③ schema 默认值 planner→auto；④ route_decision 零改动——空 force_branch 自动走意图分发 | ✅ |
| 2026-08-03 | Phase 18-续-3：进度标签中文化——① NODE_LABELS 补全 route_decision="正在匹配业务专家..."；② fallback 从 `f"正在执行 {node_name}..."` 改为通用"正在处理..."，不再泄露英文内部名 | ✅ |
| 2026-08-04 | Phase 19：查询改写节点——① 新建 `graph/nodes/query_rewrite.py` + `prompts/query_rewrite.txt`；② 主干链路插入 `session_context → query_rewrite → intent_router`；③ AgentState 新增 `original_query` 字段；④ 快速跳过机制（短确认+已规范中文免 LLM 调用）；⑤ 验证：拼音"bei jing 3天 2 person" → "北京3天2人行程"，中英混杂 → 中文统一，规范中文不变 | ✅ |
| 2026-08-04 | Phase 19-续：模型分层成本优化——① 新增 `get_light_llm()` 工厂（qwen-turbo）；② 客服/运营 → qwen-turbo（↓~90%费用）；③ 销售 → qwen-plus；④ 查询改写 → qwen-turbo；⑤ 行程定制保持 qwen3-max；⑥ 所有模型均支持 function calling，Agent 代码零改动；⑦ 193 测试全部通过 | ✅ |
| 2026-08-04 | Phase 20：销售 Agent 重设计——① Pipeline 五阶段模型（LEAD→QUALIFIED→NEGOTIATION→CLOSING→WON/LOST）；② 4 个分阶段 Prompt 动态加载；③ 5 个新 Mock 销售工具（load_trip_draft/create_order/get_payment_url/apply_coupon/check_order_status）；④ 跟进策略（24h 温和→3d 优惠→7d 放弃）；⑤ 行程修改检测（goto_planner→trip_planner→回销售）；⑥ 新建 5 文件/重写 2 文件/修改 10 文件/删除 1 文件；⑦ 215 测试全部通过 | ✅ |
| 2026-08-05 | Phase 21-续：E2E 测试 Bug 修复——① P0 天数误提取：`_extract_fields_regex` 正则把"9月20日"的"20"误判为天数→清洗日期模式后再提取+合理性检查(>30拒绝)；② P1 模板变量：3个销售Prompt中`{目的地}`/`{某项目}`被LLM原样输出→改为具体示例(如"北京")；③ P1 上下文丢失：`_run_tool_calling_loop`只传当前消息→新增`history`参数传入最近5轮对话；④ P2 Pipeline卡LEAD：`_build_draft_context`仅从state提取→新增对话历史正则fallback；⑤ 8文件修改+5个回归测试，243测试通过 | ✅ |
| 2026-08-05 | Phase 21：运营 Agent 重设计——用户与产品的桥梁：① 数据库新建 orders + tickets 表；② 10 个运营工具（产品查询×4 search_hotels/flights/tickets/guides + 订单管理×4 get_order/list_orders/cancel_order/modify_order + 工单×2 create_ticket/check_ticket）；③ 运营工具作为平台共享能力层（MCP→Mock 降级）；④ Agent 重写：12 工具 + WON 接管 + 紧急升级 + CRM 强制写入；⑤ 新建 operations_handoff 节点（销售成交后运营自动接管）；⑥ after_sales 路由新增 won→operations_handoff→operations_sync；⑦ session_context 检测 has_active_order → intent_router 加权 operations ×1.5；⑧ State 新增 has_active_order/active_order_id/order_context 字段；⑨ MemoryManager 新增 7 个 order/ticket CRUD 方法；⑩ 新建 2 文件/重写 3 文件/修改 10 文件；⑪ 243 测试全部通过（+28 运营专项测试） | ✅ |
| 2026-08-05 | Phase 21-续-2：LIGHT_MODEL 修复——① 销售 Agent（6 tools）和运营 Agent（12 tools）调用 qwen-turbo 时 API 返回 400 → 根因是 qwen-turbo 不支持多工具 function calling；② `get_light_llm()` 默认模型从 `qwen-turbo` 改为 `qwen-plus`（代码默认 + `.env` 显式配置）；③ `.env.example` 补全 LIGHT_MODEL/LIGHT_TEMPERATURE/LIGHT_MAX_TOKENS 文档；④ `ainvoke()` 新增详细错误日志（记录 API 响应体便于排查）；⑤ ⚠️ 需重启后端使配置生效 | ✅ |
| 2026-08-05 | Phase 21-续-3：E2E 测试 3 项修复——① P0 西班牙语回复中文：`customer_service.py` 最终回答指令改为 7 语言感知（zh/en/es/ja/ko/hi/ar）+ 投诉关键词扩展为 7 语言；② P1 Profile 页面路由冲突：API 端点 `/profile*` → `/api/profile*`（GET/PUT/suggestions），新增 `GET /profile` 返回 HTML 页面，`profile.html` API 路径同步，`index.html` 侧边栏画像链接更新；③ P1 ROUTER_MODEL 不一致：`.env` 中 `ROUTER_MODEL` 从 `qwen-turbo` 修正为 `qwen-plus`（与 `.env.example` 对齐）；④ `services/llm.py` 新增 `reset_all_singletons()` 免重启切换 + `_build_body()` 调试日志；⑤ `api/main.py` 启动日志新增 LIGHT_MODEL 行；⑥ 5 文件修改，243 测试通过 | ✅ |
| 2026-08-05 | Phase 21-续-4：Chrome DevTools E2E 全功能测试 + 4 个 Bug 修复——① P0 MCP Server 死锁：`MCPServerConnection` 的 `start()` 和 `_send_request()` 共用一个非可重入 asyncio.Lock → 拆分为 `_lifecycle_lock` + `_request_lock`；② P1 Profile Pydantic 验证错误：Redis 缓存中 `budget_range` 为脏字符串 → API 端点加 sanitization + 清除 Redis 缓存；③ P1 销售/运营 Agent 400 错误：`_langchain_role()` 中 `msg.type="human"` 未映射为 `"user"` → 添加 type 映射表；④ P2 数据库缺表：已有 volume 缺少 Phase 20-21 新增的 `sales_pipeline`/`orders`/`tickets` 表 → 手动执行 DDL 创建；⑤ 测试覆盖：模式切换/语言切换/智能客服FAQ/投诉转人工/西班牙语/行程定制SSE/打断/销售Pipeline/用户画像 全部通过；⑥ 3 文件修改 + 2 项手动操作，243 测试通过 | ✅ |
| 2026-08-05 | Phase 21-续-5：E2E 续测——11 项功能全覆盖 + Bug #5 修复——① P1 budget_range 列过短：`user_profiles.budget_range` VARCHAR(32) 存不下 JSON `{"min":1000,"max":3000,"currency":"USD"}`（45字符）→ ALTER TABLE 扩至 VARCHAR(128) + 同步更新 `migrate_mysql.sql` 两处定义；② 测试全部通过：默认自动路由→行程定制(95%)、运营处理→转人工交接单(85%)、对话删除（悬停✕→确认弹窗→取消/删除）、用户画像编辑（修复后保存成功）、English 语言切换（Agent 英文回复上海行程）、模式视觉区分（5 模式独立 emoji/标题/placeholder）、销售 Pipeline 流程（桂林4天→DRAFT加载→报价→NEGOTIATION跟进）、西班牙语支持（es→zh查询改写+RAG+完整西语签证材料回复）、空消息处理（前端拦截不发送）、客服FAQ（支付方式→微信/支付宝TourPass/信用卡/现金个性化推荐）、退出登录（返回登录页+重新登录正常）；③ 1 文件修改 + 1 项手动 DB 操作 + 243 测试通过 | ✅ |
| 2026-08-05 | **Phase 22：旅程驱动的多 Agent 协作**——核心架构升级：① 新增 `journey_stage`/`next_agent`/`handoff_context` 三字段（粗粒度 4 阶段：discovery→planning→sales→post_purchase）+ `AgentHandoff` TypedDict；② 路由重构（`route_decision.py`）：journey_stage 优先驱动，intent_scores 仅在 discovery 阶段兜底，非 discovery 阶段直接跳过意图分类；③ 意图路由降级为打断检测（`intent_router.py`）：非 discovery 阶段不走 LLM，regex 检测投诉/运营打断/回流转；④ 统一 Agent 出口条件（`builder.py`：`_agent_exit`）：替代 after_service/after_sales/_after_operations 三个硬编码条件边，仅当 next_agent ≠ current_branch 时才重路由；⑤ 移除 `operations_handoff` 节点——交接逻辑由 Agent 通过 `next_agent` 声明驱动 + `_agent_exit` 处理；⑥ Agent 交接协议：trip_planner 确认→`journey_stage=sales`+`next_agent=sales_agent`（`intent_scorer` 写入）；sales_agent WON→`journey_stage=post_purchase`+`next_agent=operations_agent`；operations_agent 回流转→`next_agent=trip_planner/sales_agent`；⑦ 新增 `BaseAgent._build_response()` 标准化返回方法 + `_get_handoff_context()` 读取交接上下文；⑧ sales_agent 新增 `_load_draft_from_handoff()` 跨会话加载行程 + handoff 感知跳过 LEAD 阶段；⑨ operations_agent 新增 `_detect_reroute()` 回流转检测；⑩ Prompt 更新 4 文件（sales_lead/closing + operations_agent + trip_planner）；⑪ **Bug 修复**：`_agent_exit` 缺少 same-agent 检查导致 sales→sales 无限循环 → 加 `next_branch != current_branch` 守卫；⑫ E2E 验证：trip_planner("🗺️ 行程定制")→ 确认→sales_agent("💰 销售咨询"，销售 intent 85%) 全链路通过；⑬ 14 文件修改 | ✅ |

