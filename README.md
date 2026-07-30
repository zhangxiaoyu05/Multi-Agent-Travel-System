# 入境定制游多 Agent 系统

基于 **LangGraph** + **FastAPI** + **阿里百炼** 的智能旅游规划平台，由意图路由器统一分发到多个业务 Agent，为入境游客提供行程定制、FAQ 答疑、人工接管等一站式服务。

---

## 架构概览

```
用户消息 → input_guard → session_context → intent_router
                                                │
        ┌──────────────────┰────────────────────┼──────────────────────┐
        ▼                  ▼                    ▼                      ▼
 customer_service      sales_agent         trip_planner           human_handoff
  FAQ / 转人工         报价 / 签约         需求采集 / 草案            (人工接管)
        │                  │             生成 / 修订循环                  │
        ▼                  ▼                    │                        │
   human_handoff     operations_sync    ────────┘                        │
        │                  │                    │                        │
        └──────────────────╋────────────────────┼────────────────────────│
                           ▼                    ▼                        ▼
                    operations_agent      operations_sync ←──────────────┘
                     入驻 / 履约 / 工单   (终态：CRM + CAPI)
```

## 技术栈

| 层级 | 技术 |
|------|------|
| 编排引擎 | LangGraph ≥ 0.2 |
| Agent 框架 | LangChain ≥ 0.3 |
| Web 框架 | FastAPI ≥ 0.115 |
| LLM | 阿里百炼（qwen-turbo 路由 + qwen-plus 生成） |
| Python | 3.12 |
| 容器化 | Docker + docker-compose |

## 项目结构

```
Multi_Agent/
├── api/                   # FastAPI 层（/chat 接口、请求模型）
│   ├── main.py
│   └── schemas.py
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
│   │   ├── sales_agent.py        # Phase 6 新增
│   │   ├── operations_agent.py   # Phase 6 新增
│   │   ├── human_handoff.py
│   │   └── operations_sync.py    # 终态数据写入（CRM + CAPI）
│   └── conditions/        # 条件边（路由判断）
│       ├── route_decision.py
│       ├── after_service.py
│       ├── after_sales.py        # Phase 6 新增
│       ├── requirements_complete.py
│       └── revision_decision.py
├── agents/                # Agent 业务实现
│   ├── base.py            #   BaseAgent 抽象基类
│   ├── customer_service.py #   客服 Agent（FAQ + 转人工）
│   ├── trip_planner.py    #   定制 Agent（需求提取 + 草案生成 + 修订）
│   ├── sales_agent.py     #   销售 Agent（报价 + 意向评分）Phase 6
│   └── operations_agent.py #  运营 Agent（入驻 + 履约 + 工单）Phase 6
├── tools/                 # LangChain Tools（MVP 全 Mock）
│   ├── mock_faq.py        #   FAQ 知识库（签证/支付/退改等 10 类）
│   ├── mock_handoff.py    #   转人工评估
│   ├── mock_weather.py    #   天气查询（12 城市）
│   ├── mock_calendar.py   #   节假日 / 人流量
│   ├── mock_inventory.py  #   酒店 / 门票 / 车辆库存
│   ├── mock_quote.py      #   报价生成（32 城市基准价）Phase 6
│   ├── mock_crm.py        #   CRM 客户记录写入
│   └── mock_capi.py       #   CAPI 转化事件发送
├── services/              # 基础设施（LLM 网关）
├── prompts/               # System Prompt 模板（5 个）
│   ├── intent_router.txt
│   ├── customer_service.txt
│   ├── trip_planner.txt
│   ├── sales_agent.txt           # Phase 6 新增
│   └── operations_agent.txt      # Phase 6 新增
├── tests/                 # 测试
├── docker-compose.yml     # 本地开发编排
├── Dockerfile
├── requirements.txt
└── main.py                # 本地快速启动（12 组测试）
```

## 快速开始

### 前置条件

- Python ≥ 3.12
- Docker（可选，推荐）
- 阿里百炼 API Key（[获取地址](https://bailian.console.aliyun.com/)）

### 环境配置

```bash
# 1. 克隆项目
git clone https://github.com/zhangxiaoyu05/Multi-Agent-Travel-System.git
cd Multi-Agent-Travel-System

# 2. 配置环境变量
cp .env.example .env
# 编辑 .env，将 LLM_API_KEY 替换为你的百炼 API Key

# 3. 安装依赖
pip install -r requirements.txt

# 4. 启动服务
python main.py
```

访问 http://localhost:8000/docs 查看 Swagger API 文档。

### Docker 启动

```bash
docker-compose up --build
```

## API 接口

### `GET /health`

健康检查。

```json
{"status": "ok", "version": "0.1.0"}
```

### `POST /chat`

核心对话接口。

**请求体**：

```json
{
  "session_id": "sess-001",
  "customer_id": "cust-001",
  "channel": "web",
  "message": "我想去西安玩3天",
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

## 开发阶段

| Phase | 内容 | 状态 |
|-------|------|:---:|
| Phase 0 | 项目骨架 + Docker 环境 | ✅ |
| Phase 1 | State 定义 + 最简图 | ✅ |
| Phase 2 | 意图路由器完善 | ✅ |
| Phase 3 | 客服 Agent + 人工接管 | ✅ |
| Phase 4 | 定制 Agent + 修订循环 | ✅ |
| Phase 5 | 终态写入 + /chat 联调 | ✅ |
| Phase 6 | 销售 Agent + 运营 Agent | ✅ |
| Phase 7 | RAG 增强（真实向量检索） | 后续 |
| Phase 8 | 生产化 | 后续 |

## 关键文档

| 文档 | 说明 |
|------|------|
| `langgraph_agent实现方案.md` | 原始架构设计，含 Agent 定义与流转逻辑 |
| `implementation_plan.md` | 完整实现方案，逐 Phase 含具体代码 |
| `progress.md` | 项目进度日志，记录每次操作与决策 |

## 许可证

MIT
