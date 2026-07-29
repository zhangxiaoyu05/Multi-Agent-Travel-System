"""修订决策条件边

根据意向评分和修订次数决定下一步：
- accept / high → end（正常结束）
- revise 且次数 < 3 → revision_loop（回到 trip_planner 重新生成）
- give_up 或超限 → human_handoff
"""

from graph.state import AgentState

MAX_REVISIONS = 3


def revision_decision(state: AgentState) -> str:
    """修订决策

    决策优先级：
    1. intent_level=high 或 next_action=accept → end
    2. next_action=revise 且 revision_count < 3 → revision_loop
    3. 其他（give_up / 超限） → human_handoff

    Args:
        state: 当前 AgentState

    Returns:
        目标节点名称：'end' / 'revision_loop' / 'human_handoff'
    """
    intent = state.get("intent_level", "mid")
    action = state.get("next_action", "accept")
    count = state.get("revision_count", 0)

    # 高意向或明确接受 → 正常结束
    if intent == "high" or action == "accept":
        return "end"

    # 修订请求且未超限 → 再给一次机会
    if action == "revise" and count < MAX_REVISIONS:
        return "revision_loop"

    # 放弃或超限 → 转人工
    return "human_handoff"
