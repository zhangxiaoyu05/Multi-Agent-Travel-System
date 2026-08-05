"""修订决策条件边

根据意向评分、旅程阶段和修订次数决定下一步：
- accept + journey_stage 变更 → route_decision（交接给下一个 Agent，同轮接力）
- accept + journey_stage 不变 → operations_sync（正常结束）
- revise 且次数 < 3 → revision_loop（回到 trip_planner 重新生成）
- give_up 或超限 → human_handoff

v4.1: 当 intent_scorer 在 accept 时改变了 journey_stage（如 planning→sales），
说明需要下一个 Agent 立即接力，此时返回 route_decision 触发同轮交接。
"""

from graph.state import AgentState

MAX_REVISIONS = 3


def revision_decision(state: AgentState) -> str:
    """修订决策

    决策优先级：
    1. accept + journey_stage ≠ planning → route_decision（交接给销售/运营）
    2. accept + journey_stage = planning → operations_sync（兜底）
    3. revise 且 revision_count < 3 → revision_loop
    4. 其他（give_up / 超限） → human_handoff

    Args:
        state: 当前 AgentState

    Returns:
        目标节点名称：'route_decision' / 'operations_sync' / 'revision_loop' / 'human_handoff'
    """
    intent = state.get("intent_level", "mid")
    action = state.get("next_action", "accept")
    count = state.get("revision_count", 0)

    # 高意向或明确接受
    if intent == "high" or action == "accept":
        # v4.1: 旅程阶段变更 → 同轮交接给下一个 Agent
        new_stage = state.get("journey_stage", "planning")
        if new_stage != "planning":
            return "route_decision"
        return "operations_sync"

    # 修订请求且未超限 → 再给一次机会
    if action == "revise" and count < MAX_REVISIONS:
        return "revision_loop"

    # 放弃或超限 → 转人工（human_handoff 之后进入 operations_sync）
    return "human_handoff"
