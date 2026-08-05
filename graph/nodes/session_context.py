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
        # Phase 20: 销售 Pipeline
        "sales_pipeline_stage": state.get("sales_pipeline_stage", ""),
        "sales_context": state.get("sales_context", {}),
        "has_unconverted_trip": state.get("has_unconverted_trip", False),
        "previous_draft_id": state.get("previous_draft_id", ""),
        "goto_planner": state.get("goto_planner", False),
        # Phase 21: 运营订单检测
        "has_active_order": state.get("has_active_order", False),
        "active_order_id": state.get("active_order_id", ""),
        "order_context": state.get("order_context", {}),
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

    # 销售跟进检测（Phase 20）：检查用户是否有未转化的行程方案
    if user_id and not result.get("has_unconverted_trip"):
        try:
            from services.memory import MemoryManager
            from datetime import datetime, timezone
            mm = MemoryManager()
            pipeline = await mm.get_active_pipeline(user_id)
            if pipeline and pipeline.get("status") == "active":
                updated_at = pipeline.get("updated_at", "")
                if updated_at:
                    last_time = datetime.fromisoformat(updated_at)
                    now = datetime.now(timezone.utc)
                    if last_time.tzinfo is None:
                        last_time = last_time.replace(tzinfo=timezone.utc)
                    gap_hours = (now - last_time).total_seconds() / 3600
                    if gap_hours >= 24:
                        result["has_unconverted_trip"] = True
                        result["previous_draft_id"] = pipeline.get("draft_id", "")
                        # 7天以上 → 标记 pipeline lost
                        if gap_hours >= 7 * 24:
                            await mm.mark_pipeline_lost(user_id)
                            result["has_unconverted_trip"] = False
        except Exception:
            pass  # 检测失败不阻塞对话

    # Phase 21: 检测用户是否有进行中的订单（运营路由加权用）
    if user_id and not result.get("has_active_order"):
        try:
            from services.memory import MemoryManager
            mm = MemoryManager()
            active_order = await mm.get_active_order(user_id)
            if active_order:
                result["has_active_order"] = True
                result["active_order_id"] = active_order["order_id"]
        except Exception:
            pass  # 检测失败不阻塞对话

    return result
