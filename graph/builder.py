"""LangGraph 图构建——Phase 3

组装所有节点和边，编译为可执行的 StateGraph。

当前图结构：
    START → input_guard → session_context → intent_router
                                                   │
         ┌─────────────────────────────────────────┼───────────────────────┐
         ▼                                         ▼                       ▼
  customer_service                          trip_planner            human_handoff
         │                                    (Phase 4)                  │
         ├─ after_service                                               │
         │                                                              ▼
         ├─→ human_handoff ─────────────────────────────────────────→ END
         ├─→ intent_router (重新路由)
         └─→ END
"""

from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver

from graph.state import AgentState

# Nodes
from graph.nodes.input_guard import input_guard
from graph.nodes.session_context import session_context
from graph.nodes.intent_router import intent_router
from graph.nodes.customer_service import customer_service
from graph.nodes.human_handoff import human_handoff

# Conditions
from graph.conditions.route_decision import route_decision
from graph.conditions.after_service import after_service


# =============================================================================
# 占位节点（Phase 4 替换为真实实现）
# =============================================================================


def _placeholder_trip_planner(state: AgentState) -> dict:
    """定制占位节点（Phase 4 替换）"""
    return {"final_reply": "[定制] 功能开发中，即将支持行程规划与草案生成。"}


# =============================================================================
# 图构建函数
# =============================================================================


def build_graph():
    """构建并编译 LangGraph 图

    图结构：
        START → input_guard → session_context → intent_router
                                                      │
              ┌───────────────────────────────────────┼───────────────────┐
              ▼                                       ▼                   ▼
       customer_service                         trip_planner        human_handoff
              │                                 (placeholder)             │
              ├─ after_service                                           │
              │                                                          ▼
              ├─→ human_handoff ─────────────────────────────────────→ END
              ├─→ intent_router
              └─→ END

    Returns:
        编译后的 StateGraph（含 MemorySaver checkpoint）
    """
    builder = StateGraph(AgentState)

    # ====== 注册节点 ======
    builder.add_node("input_guard", input_guard)
    builder.add_node("session_context", session_context)
    builder.add_node("intent_router", intent_router)

    # Phase 3 真实节点
    builder.add_node("customer_service", customer_service)
    builder.add_node("human_handoff", human_handoff)

    # Phase 4 占位节点
    builder.add_node("trip_planner", _placeholder_trip_planner)

    # ====== 边 ======

    # 主干线：按顺序串联
    builder.add_edge(START, "input_guard")
    builder.add_edge("input_guard", "session_context")
    builder.add_edge("session_context", "intent_router")

    # 路由分发：根据意图分数选择分支
    builder.add_conditional_edges(
        "intent_router",
        route_decision,
        {
            "customer_service": "customer_service",
            "trip_planner": "trip_planner",
            "human_handoff": "human_handoff",
        }
    )

    # 客服分支：after_service 条件边
    builder.add_conditional_edges(
        "customer_service",
        after_service,
        {
            "human_handoff": "human_handoff",
            "intent_router": "intent_router",
            "end": END,
        }
    )

    # 终端节点 → END
    builder.add_edge("trip_planner", END)
    builder.add_edge("human_handoff", END)

    # ====== 编译 ======

    # 开发期使用内存 checkpoint（生产环境切 PostgresSaver）
    memory = MemorySaver()
    compiled_graph = builder.compile(checkpointer=memory)

    return compiled_graph
