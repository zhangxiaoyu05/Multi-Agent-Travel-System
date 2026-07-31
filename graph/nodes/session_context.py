"""会话初始化节点

初始化会话级别的默认值，确保所有 State 字段都有合理的初始值。
"""

from graph.state import AgentState


def session_context(state: AgentState) -> dict:
    """初始化会话级默认值

    在 input_guard 之后、intent_router 之前执行，
    为空的字段设置默认值，避免下游节点访问不存在的 key。

    Args:
        state: 当前 AgentState

    Returns:
        要合并到 State 的字段 dict
    """
    return {
        "language": state.get("language", "zh"),
        "need_human": state.get("need_human", False),
        "revision_count": state.get("revision_count", 0),
        "draft": state.get("draft", {}),
        "need": state.get("need", {}),
        "intent_scores": state.get("intent_scores", {}),
        "current_branch": state.get("current_branch", ""),
        "intent_level": state.get("intent_level", ""),
        "next_action": state.get("next_action", ""),
        "final_reply": state.get("final_reply", ""),
        "quote": state.get("quote", ""),
        # 🆕 共享黑板 v2 新字段
        "handoff": state.get("handoff", {}),
        "agent_traces": state.get("agent_traces", []),
        "branch_history": state.get("branch_history", []),
    }
