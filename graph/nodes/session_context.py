"""会话初始化节点

初始化会话级别的默认值 + 从 MemoryManager 加载用户画像/偏好。
在 input_guard 之后、intent_router 之前执行。
"""

from graph.state import AgentState


async def session_context(state: AgentState) -> dict:
    """初始化会话级默认值并加载用户记忆

    1. 为空的字段设置默认值
    2. 从 MySQL 加载用户画像（长期记忆）和中期偏好快照
    3. 将记忆数据注入 State 供所有 Agent 使用

    Args:
        state: 当前 AgentState

    Returns:
        要合并到 State 的字段 dict
    """
    user_id = state.get("customer_id", "")
    result = {
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
        # 🧠 记忆字段
        "user_profile": state.get("user_profile", {}),
        "user_preferences": state.get("user_preferences", {}),
    }

    # 加载用户画像和偏好（仅当 State 中尚无数据时）
    if not result["user_profile"] and user_id:
        try:
            from services.memory import MemoryManager
            mm = MemoryManager()
            profile = await mm.get_profile(user_id)
            if profile:
                result["user_profile"] = profile

            prefs_list = await mm.get_active_preferences(user_id)
            if prefs_list:
                # 取最新一条（置信度最高的）
                result["user_preferences"] = prefs_list[0]
        except Exception:
            pass  # 加载失败不阻塞对话

    return result
