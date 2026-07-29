"""LangGraph 图构建——Phase 1-2

组装所有节点和边，编译为可执行的 StateGraph。
骨架版：客服、定制、人工接管均为占位节点，Phase 3-4 替换为真实实现。
"""

from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver

from graph.state import AgentState

# Nodes
from graph.nodes.input_guard import input_guard
from graph.nodes.session_context import session_context
from graph.nodes.intent_router import intent_router

# Conditions
from graph.conditions.route_decision import route_decision


# =============================================================================
# 占位节点（Phase 3-4 替换为真实实现）
# =============================================================================


def _placeholder_customer_service(state: AgentState) -> dict:
    """客服占位节点"""
    return {"final_reply": "[客服] 功能开发中，即将支持 FAQ 答疑与订单查询。"}


def _placeholder_trip_planner(state: AgentState) -> dict:
    """定制占位节点"""
    return {"final_reply": "[定制] 功能开发中，即将支持行程规划与草案生成。"}


def _placeholder_human_handoff(state: AgentState) -> dict:
    """人工接管占位节点"""
    return {
        "final_reply": "正在为您转接人工客服，请稍候...",
        "need_human": True,
    }


# =============================================================================
# 图构建函数
# =============================================================================


def build_graph():
    """构建并编译 LangGraph 图

    图结构：
        START → input_guard → session_context → intent_router
                                                      │
                          ┌───────────────────────────┼───────────────────┐
                          ▼                           ▼                   ▼
                   customer_service             trip_planner        human_handoff
                          │                           │                   │
                          ▼                           ▼                   ▼
                         END                         END                 END

    Returns:
        编译后的 StateGraph（含 MemorySaver checkpoint）
    """
    builder = StateGraph(AgentState)

    # ====== 注册节点 ======
    builder.add_node("input_guard", input_guard)
    builder.add_node("session_context", session_context)
    builder.add_node("intent_router", intent_router)

    # 占位节点（Phase 3-5 逐步替换为真实实现）
    builder.add_node("customer_service", _placeholder_customer_service)
    builder.add_node("trip_planner", _placeholder_trip_planner)
    builder.add_node("human_handoff", _placeholder_human_handoff)

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

    # 终端节点 → END
    builder.add_edge("customer_service", END)
    builder.add_edge("trip_planner", END)
    builder.add_edge("human_handoff", END)

    # ====== 编译 ======

    # 开发期使用内存 checkpoint（生产环境切 PostgresSaver）
    memory = MemorySaver()
    compiled_graph = builder.compile(checkpointer=memory)

    return compiled_graph
