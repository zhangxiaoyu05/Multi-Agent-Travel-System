# 基于 LangGraph 的入境定制游 AI Agent 实现方案

## 一、整体定位

基于 LangGraph 构建入境定制游平台的智能 Agent，由「意图路由器」统一分发到四类业务分支：

- **智能客服（customer_service）**：负责 FAQ 答疑、政策解释、订单查询、投诉识别与转人工
- **销售 Agent（sales_agent）**：负责产品推介、报价、签约引导，把高意向客户推给销售
- **运营 Agent（operations_agent）**：负责商家入驻、订单履约、售后工单、平台规则
- **旅游定制 Agent（trip_planner）**：根据人数、预算、天气、时间等定制具体行程

四个 Agent 共享同一份 State（会话上下文），由 `operations_sync` 节点统一负责终态数据写入。

---

## 二、目录结构

代码分六层：

- `graph/`：LangGraph 编排层，含 State、Builder、节点、路由函数
- `agents/`：业务 Agent 抽象与具体实现
- `tools/`：LangChain Tools 封装（天气、库存、日历、报价、CRM、CAPI、FAQ）
- `services/`：外部依赖（数据库、LLM 网关、缓存、消息队列）
- `prompts/`：各 Agent 的 system prompt
- `tests/`：单元测试与端到端测试

各 Agent 的业务实现放在 `agents/` 下，节点实现放在 `graph/nodes/`，节点只负责「调用 Agent + 写 State」，Agent 负责「业务逻辑」，Tool 负责「外部能力」，三者解耦。

---

## 三、State 设计

State 沿用 LangGraph 的 `MessagesState` 作为基类，扩展出以下字段：

### 渠道与会话字段

- `session_id`：会话唯一标识，用于 checkpoint
- `customer_id`：客户唯一标识，用于跨会话记忆
- `channel`：渠道枚举（whatsapp / wechat / web / messenger / tiktok）
- `language`：默认 zh，可被 input_guard 自动识别覆盖

### 路由字段

- `current_branch`：当前所在分支（service / sales / operations / planner）
- `intent_scores`：四类意图的概率字典

### 业务数据字段

- `need`（TripNeed）：必填项（目的地、天数、抵达日期、人数、预算）、偏好项（主题、节奏）、特殊需求
- `draft`（TripDraft）：版本号、Markdown 行程、预估费用、天气摘要
- `revision_count`：草案修订次数，硬上限 3 次
- `intent_level`：高 / 中 / 低三档意向

### 控制字段

- `need_human`：是否触发转人工
- `next_action`：revise / accept / give_up
- `collected_fields`：已采集字段列表

### 输出字段

- `final_reply`：最终结构化回复
- `quote`：报价单

State 由 LangGraph 自动持久化到 Checkpoint（开发期 MemorySaver，生产期切 PostgresSaver），保证人工接管后可恢复会话。

---

## 四、意图路由器

**作用**：把用户消息分发到四类业务分支或人工接管。

**实现**：用 GPT-4o-mini（或本地 7B 轻量模型）做结构化输出，输出每个分支 0-1 的概率和 `need_human` 布尔值。

**触发转人工的关键词**：投诉、退款、差评、人工、真人、complaint、refund。任一命中即跳过正常路由直接进入 `human_handoff`。

**路由逻辑**：取概率最高的分支作为目标；若概率全部低于 0.3，默认进入客服。

**性能优化建议**：意图识别独立部署 7B 小模型，复杂场景再升级 GPT-4o，避免每次都打主模型。

---

## 五、四类 Agent 节点

### 1. 智能客服 Agent

**Prompt 定位**：入境定制游平台的多语言客服，专注订单查询、退改政策、签证须知、FAQ。

**必备 Tool**：`search_faq`（FAQ 检索）、`check_handoff`（评估是否转人工）。

**流转逻辑**：

- 简单问答直接返回 `final_reply`，会话结束
- 复杂问题（投诉 / 签证 / 多次未解决）调用 `check_handoff`，把 `need_human` 置 True
- 返回后由 `after_service` 条件边判断走向：`need_human=True` 转 `human_handoff`；有 `final_reply` 进 END；否则回到路由器重新分类

### 2. 销售 Agent

**Prompt 定位**：主动引导客户完成产品销售，确认预算与决策人，高意向推送签约链接，中低意向推送案例与优惠。

**必备 Tool**：`quote_price`（生成报价单）、`query_inventory`（查资源可售）。

**意向评分**：Agent 内部简单评分，若回复含「签约 / 支付 / 定金 / sign」判 high；含「考虑 / 再看看 / 优惠」判 mid；否则 low。

**流转逻辑**：

- high → `quote_agent` 生成报价 → `operations_sync` 终态
- mid / low → `operations_agent` 进入培育流程
- 触发关键词 → `human_handoff`

### 3. 运营 Agent

**Prompt 定位**：处理商家入驻、订单履约、平台规则、售后工单。

**必备 Tool**：`update_crm`（写入工单）、`send_capi`（回传事件）。

**流转逻辑**：

- 完成运营任务后强制调用 `update_crm`，写完后跳到 `operations_sync`
- 投诉类工单同样允许进入 `human_handoff`

### 4. 旅游定制 Agent

**Prompt 定位**：根据客户需求生成可执行的行程草案。

**必备 Tool**：

- `get_weather(city, date)`：查目的地天气
- `query_calendar(date)`：查节假日 / 周末
- `query_inventory(city, date, pax)`：查酒店、门票、车辆库存

**生成约束**：

- 调用天气与日历工具后再生成，避免与极端天气冲突
- 每天景点间交通 ≤2.5 小时
- 输出 Markdown 行程 + 预估人均费用
- 第一次生成时设置 `draft.version += 1` 并写入 `itinerary_md`

**流转逻辑**：由 `after_planner_draft` 判断必填项（目的地、天数、抵达日期、人数、预算）是否齐全；未补齐则继续追问，已补齐则进入 `intent_scorer`。

---

## 六、定制主线的 LangGraph 编排

定制主线是整个图最复杂的部分，包含三个关键条件边：

### 条件边 1：`requirements_complete?`

- **触发位置**：`trip_planner` 出口
- **判断逻辑**：必填五字段是否齐全，且 `draft.itinerary_md` 是否非空
- **去向**：
  - 必填未补齐 → 回到 `trip_planner` 继续追问
  - 已补齐 → 进入 `intent_scorer` 评分

### 条件边 2：`revision_decision`

- **触发位置**：`intent_scorer` 出口
- **判断逻辑**：根据评分结果与 `next_action`
- **去向**：
  - `revise` 且 `revision_count < 3` → `revision_loop` → `trip_planner` 重新生成
  - `accept` → `quote_agent` 生成报价
  - `give_up` 或修订超过 3 次 → `operations_agent` 培育 / `human_handoff`

### 条件边 3：`intent_score`

- **触发位置**：销售 Agent 出口
- **判断逻辑**：`intent_level`
- **去向**：
  - high → `quote_agent` → `operations_sync`
  - mid / low → `operations_agent` 培育
  - `need_human=True` → `human_handoff`

---

## 七、辅助节点

### `input_guard`

入参保护，做长度截断（4000 字上限）、PII 脱敏、敏感诉求识别。

### `session_context`

会话初始化，从 Redis 读取历史画像、跨会话记忆、修订次数。

### `intent_router`

四类意图概率分发 + 转人工判断。

### `intent_scorer`

独立评分节点，专门评估客户对草案的反馈，输出 `intent_level` 和 `next_action`。

### `revision_loop`

修订计数器，`revision_count += 1`。

### `quote_agent`

调用 `quote_price` Tool 生成结构化报价单（机票、酒店、交通、门票、餐饮、导游分项）。

### `human_handoff`

转人工兜底节点，自动生成交接摘要：

- 客户 ID、来源渠道、当前分支、最后消息
- 完整需求画像、草案版本、修订次数、意向等级
- 销售跟进建议

### `operations_sync`

终态数据汇聚节点，强制执行两件事：

- 调用 `update_crm` 写入客户画像与会话结果
- 调用 `send_capi` 回传 `session_completed` 事件到广告平台

---

## 八、Tools 实现要点

| Tool | 职责 | 备注 |
|---|---|---|
| `search_faq` | FAQ 知识库检索 | 接 Milvus / pgvector |
| `check_handoff` | 转人工评估 | 关键词 + 复杂度评分 |
| `get_weather` | 城市天气查询 | 第三方 API |
| `query_calendar` | 节假日 / 周末判断 | 内置节假日库 |
| `query_inventory` | 酒店 / 门票 / 车辆库存 | 接 PMS 或供应商 API |
| `quote_price` | 报价计算 | 基于 draft 与 need 生成 |
| `update_crm` | CRM 写入 | 同步客户画像 |
| `send_capi` | CAPI 事件回传 | Meta / Google / TikTok |

所有 Tool 用 LangChain `@tool` 装饰器封装，方便后续切到 MCP 协议。

---

## 九、API 入口

FastAPI 提供 `/chat` 接口，接收：

- `session_id`（必填）
- `customer_id`（必填）
- `channel`（必填）
- `message`（必填）
- `language`（可选）

调用 `graph.invoke(state, config={"configurable": {"thread_id": session_id}})`，返回结构化响应：

- `reply`：最终回复
- `draft`：行程草案（Markdown + 预估费用）
- `quote`：报价单（如已生成）

`thread_id` 复用 `session_id`，让 LangGraph Checkpoint 自动关联历史会话。

---

## 十、落地路径建议

### 第一阶段 MVP

- 单图编排，仅客服 + 定制两个分支
- 意图识别用 GPT-4o-mini，Draft 生成用 GPT-4o
- 内存版 Checkpoint
- 目标：60% 咨询能生成完整草案，满意度 ≥3.5/5

### 第二阶段 RAG 增强
- 接入真实库存 API 与天气 API
- 跨会话记忆
- 销售 Agent 与报价 Agent 拆开
- 知识库覆盖 Top 30 入境城市

### 第三阶段 多 Agent 规模化

- 加入运营 Agent 独立分支
- 本地 7B 轻量路由模型
- PostgresSaver 替换 MemorySaver
- 接入 Langfuse 做 trace、token 成本、节点耗时观测
- 等保三级审计日志

---

## 十一、关键设计原则

1. **客服、定制、运营、销售四类能力由意图路由器统一分发**，共享同一份 State，避免画像割裂
2. **草案修订设硬上限 3 次**，超出即转人工，保护客户体验
3. **意向评分决定下游编排**：high 走报价签约，mid/low 走培育
4. **人工接管是兜底节点**：任意分支都可进入，进入后跳过自动报价
5. **`operations_agent` 与 `operations_sync` 分离**：前者处理对话中运营诉求，后者负责终态数据写入，职责清晰
6. **意图识别轻量化**：复杂分支再升级主模型，节省算力
7. **Checkpoint 必开**：支撑跨会话记忆与人工接管恢复

---

## 十二、后续可继续扩展方向

- 把 MemorySaver 改成 PostgresSaver 并提供 Redis 会话缓存接入
- 输出每个 Agent 的评测集与回归脚本
- 给出基于 LoRA 微调本地 7B 路由模型的训练方案
