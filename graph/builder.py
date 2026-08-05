"""LangGraph 图构建——Phase 22 旅程驱动多 Agent 协作

v4: Journey Stage 驱动的路由架构。
- journey_stage 决定主路径（planning → sales → post_purchase）
- intent_router 在 discovery 阶段做意图分类，在其他阶段做打断检测
- Agent 间通过 next_agent + handoff_context 接力
- 三个 Agent 出口统一为 _agent_exit（need_human / next_agent / sync）

完整图结构：
    START → input_guard → session_context → query_rewrite → intent_router
                                                                       │
         ┌────────────┰────────────┰───────────────────────────────────┼──────────────────────┐
         ▼            ▼            ▼                                   ▼                      ▼
  customer_service  sales   operations_agent                  trip_planner             human_handoff
         │            │            │           │        ▲                       │
         ├─ _agt_exit ├─ _agt_exit │           ├─ requirements_complete         │
         │  ├→ handoff│  ├→ handoff│           │   ├→ intent_scorer           │
         │  ├→ router │  ├→ router │           │   └→ END                     │
         │  └→ op_sync│  └→ op_sync│           │                                │
         │            │            │           └→ intent_scorer               │
         │            │            │               │                            │
         │            │            │               ├─ revision_decision         │
         │            │            │               │  ├→ operations_sync ──┐   │
         │            │            │               │  ├→ revision_loop ──┘   │
         │            │            │               │  └→ human_handoff ──┐    │
         │            │            │               │                      │    │
         └────────────╋────────────╋───────────────┼──────────────────────┼────│
                      │            │               │                      │    │
                      │            └───────────────┼──────────────────────┼────│
                      │                            │                      ▼    ▼
                      └────────────────────────────┼──────────→ operations_sync → END
"""

import os
import logging
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver

from graph.state import AgentState

# Nodes
from graph.nodes.input_guard import input_guard
from graph.nodes.session_context import session_context
from graph.nodes.query_rewrite import query_rewrite
from graph.nodes.intent_router import intent_router
from graph.nodes.customer_service import customer_service
from graph.nodes.trip_planner import trip_planner
from graph.nodes.intent_scorer import intent_scorer
from graph.nodes.revision_loop import revision_loop
from graph.nodes.human_handoff import human_handoff
from graph.nodes.operations_sync import operations_sync
from graph.nodes.sales_agent import sales_agent
from graph.nodes.operations_agent import operations_agent as ops_agent_node

# Conditions
from graph.conditions.route_decision import route_decision_node, route_condition
from graph.conditions.after_service import after_service
from graph.conditions.requirements_complete import requirements_complete
from graph.conditions.revision_decision import revision_decision
from graph.conditions.after_sales import after_sales

logger = logging.getLogger(__name__)


# =============================================================================
# 图构建函数
# =============================================================================


def build_graph(checkpointer=None):
    """构建并编译 LangGraph 图

    Args:
        checkpointer: LangGraph CheckpointSaver 实例。
                      None = 自动选择（MySQL 优先，失败回退 MemorySaver）

    Returns:
        编译后的 StateGraph
    """
    # ---- Checkpoint 选择 ----
    if checkpointer is None:
        backend = os.getenv("CHECKPOINT_BACKEND", "mysql")
        if backend == "mysql":
            try:
                from services.checkpoint import MySQLSaver
                checkpointer = MySQLSaver()
                logger.info("Using MySQLSaver for checkpoint persistence")
            except Exception as e:
                logger.warning(f"MySQLSaver not available ({e}), falling back to MemorySaver")
                checkpointer = MemorySaver()
        else:
            logger.info("Using MemorySaver (dev mode)")
            checkpointer = MemorySaver()

    builder = StateGraph(AgentState)

    # ====== 注册节点 ======
    builder.add_node("input_guard", input_guard)
    builder.add_node("session_context", session_context)
    builder.add_node("query_rewrite", query_rewrite)  # 查询改写：纠错+规范化
    builder.add_node("intent_router", intent_router)
    builder.add_node("route_decision", route_decision_node)  # v3: 拆分路由为节点+条件

    # Phase 3
    builder.add_node("customer_service", customer_service)
    builder.add_node("human_handoff", human_handoff)

    # Phase 4
    builder.add_node("trip_planner", trip_planner)
    builder.add_node("intent_scorer", intent_scorer)
    builder.add_node("revision_loop", revision_loop)

    # Phase 5
    builder.add_node("operations_sync", operations_sync)

    # Phase 6
    builder.add_node("sales_agent", sales_agent)
    builder.add_node("operations_agent", ops_agent_node)

    # ====== 边 ======

    # 主干线
    builder.add_edge(START, "input_guard")
    builder.add_edge("input_guard", "session_context")
    builder.add_edge("session_context", "query_rewrite")
    builder.add_edge("query_rewrite", "intent_router")
    builder.add_edge("intent_router", "route_decision")  # v3: 路由节点写 State

    # 路由分发（v3: route_condition 从 current_branch 读取，不做计算）
    builder.add_conditional_edges(
        "route_decision",
        route_condition,
        {
            "customer_service": "customer_service",
            "sales_agent": "sales_agent",
            "operations_agent": "operations_agent",
            "trip_planner": "trip_planner",
            "human_handoff": "human_handoff",
        }
    )

    # 客服分支（v4: 统一出口）
    builder.add_conditional_edges(
        "customer_service",
        _agent_exit,
        {
            "human_handoff": "human_handoff",
            "intent_router": "route_decision",  # 回到路由节点
            "operations_sync": "operations_sync",
        }
    )

    # 销售分支（v4: 统一出口，不再硬编码 trip_planner/operations_handoff）
    builder.add_conditional_edges(
        "sales_agent",
        _agent_exit,
        {
            "human_handoff": "human_handoff",
            "intent_router": "route_decision",  # 回到路由节点（含交接场景）
            "operations_sync": "operations_sync",
        }
    )

    # 运营分支（v4: 统一出口，支持回流转到销售/定制）
    builder.add_conditional_edges(
        "operations_agent",
        _agent_exit,
        {
            "human_handoff": "human_handoff",
            "intent_router": "route_decision",  # 回到路由节点（含回流转场景）
            "operations_sync": "operations_sync",
        }
    )

    # 定制分支：必填项检查
    builder.add_conditional_edges(
        "trip_planner",
        requirements_complete,
        {
            "intent_scorer": "intent_scorer",
            "end": END,
        }
    )

    # 定制分支：修订决策
    builder.add_conditional_edges(
        "intent_scorer",
        revision_decision,
        {
            "operations_sync": "operations_sync",
            "revision_loop": "revision_loop",
            "human_handoff": "human_handoff",
        }
    )

    # 修订循环回到定制
    builder.add_edge("revision_loop", "trip_planner")

    # 人工接管 → 终态写入 → END
    builder.add_edge("human_handoff", "operations_sync")
    builder.add_edge("operations_sync", END)

    # ====== 编译 ======
    compiled_graph = builder.compile(checkpointer=checkpointer)
    return compiled_graph


# =============================================================================
# v4: 统一的 Agent 出口条件边（替代 after_service / after_sales / _after_operations）
# =============================================================================

_AGENT_TO_BRANCH = {
    "trip_planner": "trip_planner",
    "sales_agent": "sales_agent",
    "operations_agent": "operations_agent",
    "customer_service": "customer_service",
}


def _agent_exit(state: AgentState) -> str:
    """统一的 Agent 出口条件——所有业务 Agent 共用。

    决策优先级：
        1. need_human → human_handoff（转人工接管）
        2. next_agent 指向不同的 Agent → intent_router（交接给下一个 Agent）
        3. 默认 → operations_sync（同步数据，结束本轮）

    关键：仅当 next_agent 与 current_branch 不同时才重路由，防止同一 Agent 循环。
    """
    # 优先级 1：转人工
    if state.get("need_human"):
        return "human_handoff"

    # 优先级 2：Agent 声明了不同下一站 → 回到路由管线
    next_agent = state.get("next_agent", "")
    current_branch = state.get("current_branch", "")
    if next_agent and next_agent in _AGENT_TO_BRANCH:
        next_branch = _AGENT_TO_BRANCH[next_agent]
        if next_branch != current_branch:
            return "intent_router"

    # 优先级 3：结束本轮
    return "operations_sync"


# 🟡 deprecated: 保留兼容别名，逐步替换
_after_operations = _agent_exit
