"""LangGraph 图构建——Phase 7+

组装所有节点和边，编译为可执行的 StateGraph。

Checkpoint 后端：
    - 生产：MySQLSaver（MySQL 8.0，服务重启不丢失会话）
    - 开发：MemorySaver（进程内，调试用）

环境变量：
    CHECKPOINT_BACKEND=mysql（默认）| memory

完整图结构：
    START → input_guard → session_context → intent_router
                                                       │
         ┌────────────┰────────────┰───────────────────┼──────────────────────┐
         ▼            ▼            ▼                   ▼                      ▼
  customer_service  sales   operations_agent  trip_planner             human_handoff
         │            │            │           │        ▲                       │
         ├─ after_svc ├─ after_sls │           ├─ requirements_complete         │
         │  ├→ handoff│  ├→ ops_sync│           │   ├→ intent_scorer           │
         │  ├→ router │  ├→ handoff│           │   └→ END                     │
         │  └→ END    │  └→ END    │           │                                │
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
    builder.add_edge("session_context", "intent_router")
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

    # 客服分支
    builder.add_conditional_edges(
        "customer_service",
        after_service,
        {
            "human_handoff": "human_handoff",
            "intent_router": "route_decision",  # v3: 回到路由节点
            "end": END,
        }
    )

    # 销售分支
    builder.add_conditional_edges(
        "sales_agent",
        after_sales,
        {
            "operations_sync": "operations_sync",
            "human_handoff": "human_handoff",
            "end": END,
        }
    )

    # 运营分支
    builder.add_conditional_edges(
        "operations_agent",
        _after_operations,
        {
            "human_handoff": "human_handoff",
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
# 运营分支条件边
# =============================================================================

def _after_operations(state: AgentState) -> str:
    """运营节点出口条件"""
    if state.get("need_human"):
        return "human_handoff"
    return "operations_sync"
