"""LangGraph 图构建——Phase 5

组装所有节点和边，编译为可执行的 StateGraph。

完整图结构（Phase 5）：
    START → input_guard → session_context → intent_router
                                                   │
         ┌─────────────────────────────────────────┼──────────────────────────┐
         ▼                                         ▼                          ▼
  customer_service                          trip_planner               human_handoff
         │                                  │        ▲                       │
         ├─ after_service                  ├─ requirements_complete         │
         │  ├─→ human_handoff ─────────────┤   │                            │
         │  ├─→ intent_router              │   ├─→ intent_scorer            │
         │  └─→ END                        │   └─→ END                     │
         │                                 │                                │
         │                                 └─→ intent_scorer               │
         │                                     │                            │
         │                                     ├─ revision_decision         │
         │                                     │  ├─→ operations_sync ───┐  │
         │                                     │  ├─→ revision_loop ────┘  │
         │                                     │  └─→ human_handoff ──┐    │
         │                                     │                       │    │
         └─────────────────────────────────────┼───────────────────────┼────│
                                               │                       │    │
                                               └───────────────────────┼────│
                                                                       ▼    ▼
                                                                 operations_sync → END
"""

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

# Conditions
from graph.conditions.route_decision import route_decision
from graph.conditions.after_service import after_service
from graph.conditions.requirements_complete import requirements_complete
from graph.conditions.revision_decision import revision_decision


# =============================================================================
# 图构建函数
# =============================================================================


def build_graph():
    """构建并编译 LangGraph 图

    图结构：
        START → input_guard → session_context → intent_router
                                                      │
        ┌─────────────────────────────────────────────┼──────────────────────────┐
        ▼                                             ▼                          ▼
        customer_service                       trip_planner               human_handoff
        │                                       │        ▲                       │
        ├─ after_service                       ├─ requirements_complete         │
        │  ├─→ human_handoff ──────────────────┤   ├─→ intent_scorer            │
        │  ├─→ intent_router                   │   └─→ END                     │
        │  └─→ END                             │                                │
        │                                      └─→ intent_scorer               │
        │                                          │                            │
        │                                          ├─ revision_decision         │
        │                                          │  ├─→ operations_sync ──┐   │
        │                                          │  ├─→ revision_loop ───┘   │
        │                                          │  └─→ human_handoff ──┐   │
        │                                          │                       │   │
        └──────────────────────────────────────────┼───────────────────────┼───│
                                                   └───────────────────────┼───│
                                                                           ▼   ▼
                                                                     operations_sync
                                                                           │
                                                                          END

    Returns:
        编译后的 StateGraph（含 MemorySaver checkpoint）
    """
    builder = StateGraph(AgentState)

    # ====== 注册节点 ======
    builder.add_node("input_guard", input_guard)
    builder.add_node("session_context", session_context)
    builder.add_node("intent_router", intent_router)

    # Phase 3 节点
    builder.add_node("customer_service", customer_service)
    builder.add_node("human_handoff", human_handoff)

    # Phase 4 节点
    builder.add_node("trip_planner", trip_planner)
    builder.add_node("intent_scorer", intent_scorer)
    builder.add_node("revision_loop", revision_loop)

    # Phase 5 节点：终态数据写入
    builder.add_node("operations_sync", operations_sync)

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

    # ---- 客服分支 ----
    builder.add_conditional_edges(
        "customer_service",
        after_service,
        {
            "human_handoff": "human_handoff",
            "intent_router": "intent_router",
            "end": END,
        }
    )

    # ---- 定制分支：必填项检查 ----
    builder.add_conditional_edges(
        "trip_planner",
        requirements_complete,
        {
            "intent_scorer": "intent_scorer",
            "end": END,
        }
    )

    # ---- 定制分支：修订决策 ----
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

    # 开发期使用内存 checkpoint（生产环境切 PostgresSaver）
    memory = MemorySaver()
    compiled_graph = builder.compile(checkpointer=memory)

    return compiled_graph
