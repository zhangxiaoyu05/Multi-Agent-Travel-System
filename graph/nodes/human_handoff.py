"""人工接管——生成交接摘要

当系统判定需要转人工（投诉/退款/复杂问题）时，
生成一份结构化的交接单，方便人工客服快速了解上下文。
"""

from graph.state import AgentState


def human_handoff(state: AgentState) -> dict:
    """生成转人工交接摘要

    从 State 中提取当前会话的核心信息：
    - 客户标识和渠道
    - 当前分支和意图分数
    - 已收集的出行需求（如有）
    - 行程草案版本（如有）
    - 最后一条用户消息

    Args:
        state: 当前 AgentState

    Returns:
        dict 包含 final_reply（交接单文本）和 need_human=True
    """
    lines = [
        "=" * 40,
        "转人工交接单",
        "=" * 40,
        "",
        f"客户 ID    : {state.get('customer_id', 'N/A')}",
        f"会话 ID    : {state.get('session_id', 'N/A')}",
        f"来源渠道   : {state.get('channel', 'N/A')}",
        f"语言偏好   : {state.get('language', 'zh')}",
        f"当前分支   : {state.get('current_branch', 'N/A')}",
    ]

    # 意图分数
    scores = state.get("intent_scores", {})
    if scores:
        lines.append(f"意图分数   : {scores}")

    lines.append("")

    # 出行需求
    need = state.get("need", {})
    if need and any(v for v in need.values()):
        lines.append("-" * 40)
        lines.append("已收集的出行需求")
        lines.append("-" * 40)
        if need.get("destination"):
            lines.append(f"  目的地     : {need['destination']}")
        if need.get("days"):
            lines.append(f"  天数       : {need['days']} 天")
        if need.get("arrival_date"):
            lines.append(f"  抵达日期   : {need['arrival_date']}")
        if need.get("pax"):
            lines.append(f"  人数       : {need['pax']} 人")
        if need.get("budget"):
            lines.append(f"  预算       : {need['budget']}")
        if need.get("theme"):
            lines.append(f"  偏好主题   : {need['theme']}")
        if need.get("pace"):
            lines.append(f"  节奏偏好   : {need['pace']}")
        if need.get("special_requests"):
            lines.append(f"  特殊需求   : {need['special_requests']}")

    # 行程草案
    draft = state.get("draft", {})
    if draft and draft.get("version"):
        lines.append("")
        lines.append("-" * 40)
        lines.append(f"行程草案 v{draft['version']}")
        lines.append("-" * 40)
        lines.append(f"  修订次数   : {state.get('revision_count', 0)}")

        if draft.get("itinerary_md"):
            # 截取前 500 字
            itinerary = draft["itinerary_md"][:500]
            lines.append(f"  行程摘要   : {itinerary}...")

    # 最后一条消息
    messages = state.get("messages", [])
    if messages:
        last = messages[-1]
        last_text = last.content if hasattr(last, "content") else str(last)
        lines.append("")
        lines.append("-" * 40)
        lines.append("最后一条用户消息")
        lines.append("-" * 40)
        lines.append(f"  {last_text[:300]}")

    lines.append("")
    lines.append("=" * 40)

    return {
        "final_reply": "\n".join(lines),
        "need_human": True,
    }
