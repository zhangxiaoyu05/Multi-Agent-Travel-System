# 项目进度日志

> 入境定制游多 Agent 系统——基于 LangGraph + FastAPI + 阿里百炼
>
> 最后更新：2026-07-30

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
Phase 7  ░░░░░░░░░░  RAG 增强（真实向量检索）           后续
Phase 8  ░░░░░░░░░░  生产化（按需）                     后续
```

### 下一步：Phase 6 ✅ 已完成

**完成时间**：2026-07-30

### 创建/更新的文件

```
prompts/
├── sales_agent.txt                          ← 新增：销售 Agent Prompt 模板
└── operations_agent.txt                     ← 新增：运营 Agent Prompt 模板
tools/
└── mock_quote.py                            ← 新增：Mock 报价工具（32 城市基准价）
agents/
├── sales_agent.py                           ← 新增：销售 Agent（报价+库存+意向评分）
└── operations_agent.py                      ← 新增：运营 Agent（CRM+CAPI+工单升级）
graph/nodes/
├── sales_agent.py                           ← 新增：销售节点（薄层包装）
└── operations_agent.py                      ← 新增：运营节点（薄层包装）
graph/conditions/
└── after_sales.py                           ← 新增：销售后置条件边
graph/builder.py                             ← 更新：注册 sales/operations 节点和边
graph/conditions/route_decision.py           ← 更新：sales/operations 指向真实 Agent
prompts/intent_router.txt                    ← 更新：完善销售/运营意图区分规则
main.py                                      ← 更新：12 组测试（含 Phase 6 销售+运营）
```

### 关键实现

- **SalesAgent**：绑定 `quote_price` + `query_inventory` 两个工具，LLM 自主决策调用工具或直接回复。内置关键词意向评分（"预订/购买"→high，"考虑/优惠"→mid，"太贵/算了"→low），高意向接受 → operations_sync 终态写入（成交！）。检测投诉关键词自动转人工
- **OperationsAgent**：绑定 `update_crm` + `send_capi` 两个工具，处理商家入驻、订单履约、售后工单、平台规则咨询。所有操作强制写入 CRM 记录（LLM 未调用时兜底补充写入），严重投诉（安全事故/媒体曝光等）升级转人工
- **Mock Quote**：32 个城市基准价（人均/天），支持主题因子（美食+15%/自然-5%）、节奏因子（轻松+30%/紧凑-15%）、双币种（¥/$）自动换算，输出含住宿/交通/门票/餐饮/导游 5 项明细的结构化报价单
- **销售分支流转**：sales_agent → after_sales → {high/accept→operations_sync, need_human→human_handoff, 其他→END}
- **运营分支流转**：operations_agent → {need_human→human_handoff, 其他→operations_sync} → END
- **图结构更新**：四分支完整版（customer_service / sales_agent / operations_agent / trip_planner），所有终态路径汇聚到 operations_sync

### 验证结果

- `python main.py test --quick` → 8 组快速测试全部通过
- `python main.py test` → 12 组全量测试全部通过
- 测试 1-8：Phase 3-5 回归正常
- 测试 9：销售询价（三亚 5 天 $2000/人）→ 正确路由 sales (0.9)，生成报价单，intent=high
- 测试 10：同 session 高意向购买（"我要预订"）→ intent=high+accept，路由到 operations_sync
- 测试 11：商家入驻咨询 → 正确路由 operations (1.0)，CRM 写入正常
- 测试 12：订单履约查询 → 正确路由 operations，CRM 写入+履约状态回复完整

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
| 2026-07-29 | Phase 1：创建 AgentState、LLM 工厂、3 个图节点、路由条件 | ✅ |
| 2026-07-29 | Phase 2：意图路由器改用 with_structured_output | ✅ |
| 2026-07-29 | 更新 main.py 添加 test 模式，4 组测试用例 | ✅ |
| 2026-07-29 | Phase 3：客服 Agent（LLM+Tools）+ 人工接管（交接单）+ after_service 条件边 | ✅ |
| 2026-07-29 | Phase 4：定制 Agent（需求提取+草案生成）+ 修订循环 + 意向评分 | ✅ |
| 2026-07-29 | Phase 5：终态写入（operations_sync + CRM/CAPI）+ /chat API 联调，MVP 完成 | ✅ |
| 2026-07-30 | Phase 6：销售 Agent（报价+意向评分）+ 运营 Agent（入驻+履约+工单），四分支完整版 | ✅ |
