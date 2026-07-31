# 项目进度日志

> 入境定制游多 Agent 系统——基于 LangGraph + FastAPI + 阿里百炼
>
> 最后更新：2026-07-31

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
```

### 下一步：持续优化

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

### 下一步：Phase 7 ✅ 已完成

**完成时间**：2026-07-30

### 创建/更新的文件

```
services/
├── embeddings.py                            ← 新增：百炼 Embedding 工厂（DashScope 原生 API）
└── vector_store.py                          ← 新增：纯 Python 向量存储（JSON + 余弦相似度）
scripts/
├── knowledge_base.py                        ← 新增：知识库文档定义（FAQ 18 篇 + 城市指南 12 篇）
└── ingest_knowledge.py                      ← 新增：知识库摄入脚本
tools/
└── rag_faq.py                               ← 新增：RAG 向量检索 FAQ 工具（语义搜索 + 关键词兜底）
agents/
└── customer_service.py                      ← 更新：从 mock_faq 切换到 rag_faq
.gitignore                                   ← 更新：忽略 data/ 目录
requirements.txt                             ← 更新：移除 chromadb（零额外依赖）
.env.example                                 ← 更新：添加 EMBEDDING_MODEL + VECTOR_DB 配置
```

### 关键实现

- **零额外依赖**：纯 Python 实现向量存储，使用 Python 标准库 + 已有的 httpx。JSON 文件持久化 + 手动余弦相似度计算，无需 numpy/chromadb 等重型依赖
- **百炼 Embedding API**：直接调用 DashScope 原生 text-embedding API（`text-embedding-v2`），避免 OpenAI 兼容模式的不兼容问题。支持单条和批量向量化
- **轻量向量存储**：JSON 文件中存储文档内容和预计算的 Embedding 向量。查询时计算余弦相似度排序，相似度阈值 0.3 过滤不相关结果
- **知识库内容**：30 篇高质量文档——FAQ 18 篇（签证/支付/退改/天气/小费/网络/交通/安全/美食/语言/健康）+ 城市指南 10 篇（北京/西安/上海/成都/桂林/杭州/广州/三亚/重庆/云南）+ 行程规划 1 篇 + 文化礼仪 1 篇
- **RAG FAQ 工具**：三级查找策略——① RAG 向量语义搜索；② 关键词精确匹配兜底（中英文）；③ 最终兜底提示。向量库未初始化时自动回退到关键词
- **摄入脚本**：`python scripts/ingest_knowledge.py` 全量导入，`--force` 覆盖已有数据，`--stats` 查看统计+测试检索，支持批量向量化（减少 API 调用）

### 验证结果

- 知识库摄入：30 篇文档在 2.9s 内完成向量化
- 向量检索测试：签证查询（0.542）、北京景点（0.698）、微信支付（0.571）——语义匹配准确
- 测试 5（FAQ 查询）：RAG 返回的答案比关键词匹配更详细（含签证材料清单）
- `python main.py test --quick` → 8 组测试全部通过，Phase 3-6 回归正常

---

### Phase 8 ✅ 基础设施升级（2026-07-30）

模型升级 + 真实基础设施 + Docker 全容器化。

#### 变更摘要

1. **LLM 升级**：生成模型 qwen-plus → **qwen3-max**，Embedding v2 → **text-embedding-v4**（1024 维）
2. **向量数据库**：纯 Python JSON+余弦相似度 → **Milvus 2.4 单机**（HNSW 索引）
3. **关系数据库**：引入 **MySQL 8.0**（SQLAlchemy async + aiomysql），用于会话存储 + 自定义 LangGraph Checkpoint Saver
4. **缓存**：引入 **Redis 7**（会话历史 + 摘要缓存）
5. **Docker 全容器化**：docker-compose 从 1 个服务扩展到 **6 个服务**（app + mysql + redis + etcd + minio + milvus）
6. **前端目录**：`static/` → `frontend/`
7. **依赖清理**：删除未使用的依赖，添加 pymilvus / sqlalchemy / aiomysql / redis

#### 新增文件

```
services/
├── mysql.py                  ← SQLAlchemy async 连接池 + session 管理
├── redis.py                  ← Redis 异步客户端 + 缓存工具（session history / summary）
├── checkpoint.py             ← MySQL Checkpoint Saver（LangGraph 持久化，替代 MemorySaver）
scripts/
└── migrate_mysql.sql         ← MySQL 初始化 DDL（checkpoints + checkpoint_writes + sessions）
```

#### 重写文件

```
services/
├── llm.py                    ← 模型改为 qwen3-max
├── embeddings.py             ← 模型改为 text-embedding-v4，新增 get_embedding_dim()
├── vector_store.py           ← 完全重写：Milvus + HNSW + pymilvus SDK，替代旧 JSON store
tools/
└── rag_faq.py                ← 适配 Milvus API，保留关键词兜底
scripts/
└── ingest_knowledge.py       ← 适配 Milvus add_documents()
graph/
└── builder.py                ← MySQLSaver 自动选择（mysql/memory 环境变量切换）
api/
└── main.py                   ← lifespan 生命周期（MySQL/Redis/Milvus 初始化 + 表创建）
                                + health 返回组件状态 + static→frontend 路径更新
```

#### 配置文件更新

```
requirements.txt              ← 新增 pymilvus / sqlalchemy / aiomysql / redis
.env.example                  ← 新增 MYSQL_/REDIS_/MILVUS_ 配置段 + 模型更新
Dockerfile                    ← 添加 HEALTHCHECK
docker-compose.yml            ← 从 1 服务扩展到 6 服务（app/mysql/redis/etcd/minio/milvus）
.gitignore                    ← 添加 Docker 数据卷忽略
```

#### 删除文件

```
tools/mock_faq.py             ← 旧版关键词 FAQ（已被 rag_faq.py 替代）
```

#### Docker Compose 服务

| 服务 | 镜像 | 端口 | 用途 |
|------|------|:---:|------|
| app | python:3.12-slim | 8000 | FastAPI 后端 |
| mysql | mysql:8.0 | 3306 | 会话 + Checkpoint |
| redis | redis:7-alpine | 6379 | 缓存 |
| etcd | quay.io/coreos/etcd:v3.5.5 | 2379 | Milvus 元数据 |
| minio | minio/minio | 9000/9001 | Milvus 对象存储 |
| milvus-standalone | milvusdb/milvus:v2.4.0 | 19530 | 向量检索 |

#### 异地部署

```bash
# 1. 复制项目到目标服务器
scp -r Multi_Agent user@server:/opt/

# 2. 配置环境
cp .env.example .env
vim .env  # 填入 LLM_API_KEY

# 3. 启动
docker-compose up --build -d

# 4. 导入知识库
docker-compose exec app python scripts/ingest_knowledge.py
```

#### Docker 启动修复（2026-07-30）

调试过程中发现并修复的问题：

1. **MinIO 健康检查**：镜像不含 curl/wget，改用 bash TCP 重定向 `echo > /dev/tcp/localhost/9000`
2. **端口冲突**：宿主机 8000（FastAPI）和 3306（MySQL）已被占用，调整为 8001:8000 和 3307:3306
3. **MySQL DDL 主键过长**：checkpoint_writes 表 5 个 VARCHAR(255) 联合主键超过 InnoDB 3072 字节限制，缩短为 VARCHAR(128)
4. **Milvus REST API**：默认不启用 RESTful 接口，向量存储改为 Milvus REST + JSON 双模式自动检测
5. **pymilvus 依赖**：Windows 上 grpcio 编译/下载过慢，改为 httpx 直连 Milvus REST API

#### 全链路验证结果

```
travel-mysql    Up (healthy)   3307→3306   ✅ 3 张表就绪
travel-redis    Up (healthy)   6379/tcp   ✅ 读写正常
travel-etcd     Up (healthy)   2379/tcp   ✅ Milvus 协调
travel-minio    Up (healthy)   9000/tcp   ✅ 对象存储
travel-milvus   Up (healthy)   19530/tcp  ✅ 向量检索（待启用 REST）
app (本地)      localhost:8001             ✅ /health /chat 正常
```

- `/chat` FAQ 路由："签证" → service(1.0) ✅
- `/chat` 规划路由："西安4天" → planner(0.95) ✅
- 向量存储：JSON 回退模式，30 篇文档 ✅

---

### Phase 9 ✅ SSE 流式输出（2026-07-30）

解决行程生成时 qwen3-max 长时间无响应（30-120s）导致前端"思考中"无限等待的体验问题。

#### 变更摘要

1. **新增 `/chat/stream` SSE 端点**：使用 LangGraph `astream(stream_mode="updates")` 在每个图节点完成时推送进度事件
2. **前端 SSE 消费**：`fetch()` + `ReadableStream` 替换静态 `fetch()`，实时显示进度标签
3. **降级兼容**：`/chat/stream` 不可用时自动回退到普通 `/chat` 端点
4. **零 Agent 侵入**：`stream_mode="updates"` 无需修改任何 Agent 或节点代码

#### 修改文件

```
api/main.py                   ← 新增 /chat/stream 端点（StreamingResponse + astream）
                                + NODE_LABELS 进度标签（12 个节点中英文映射）
frontend/index.html           ← SSE reader + 流式气泡 UI + 降级回退 + CSS fadeIn 动画
```

#### SSE 事件格式

```
event: node_start      → {"node":"intent_router","label":"正在分析意图..."}
event: node_complete   → {"node":"intent_router"}
event: node_start      → {"node":"trip_planner","label":"正在生成行程..."}
event: node_complete   → {"node":"trip_planner"}
event: done            → {完整 ChatResponse}
event: error           → {"message":"..."}
```

#### 效果对比

| | 之前 | 现在 |
|------|------|------|
| 等待时看到 | "思考中" 一直转 | "⏳ 正在分析意图..." → "⏳ 正在生成行程..." |
| 超时处理 | 无（无限等待） | 降级到 `/chat` 普通模式 |
| Agent 修改 | — | **零改动**（`astream(updates)` 无需侵入 Agent） |

#### 验证结果

- `curl /chat/stream` → 逐节点推送 `node_start` → `node_complete` → `done` ✅
- 浏览器 FAQ 测试 → 前端显示进度标签，不再静态"思考中" ✅
- `/chat` 旧端点 → 正常返回 JSON，向后兼容 ✅
- 全部 12 组 `python main.py test --quick` → 通过 ✅

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
| 2026-07-31 | CSS flexbox 修复 + Markdown 块解析重写：① 用户消息框跑左边 Bug——width:100%+row-reverse+justify-content:flex-end 在反转轴上指向左侧，回退 max-width:80%+align-self:flex-end 方案；② --- 和 ### 显示为原始文本——后端所有 --- 与 ### 之间补空行（标准 Markdown 块分隔），前端重写为按 \n\n+ 分块解析（h1/h2/h3/hr/ul/pre/p 独立判断），块首遇 --- 自动拆分；③ Markdown 间距收紧：p { margin:0 }、p+p { margin-top:6px }，h1/h2/h3/hr/ul 间距收紧，首尾元素 margin 归零 | ✅ |

