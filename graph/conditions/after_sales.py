"""销售后置条件边

销售节点执行完毕后，根据意向等级和转人工标志决定下一步：
- need_human=True  → human_handoff（交接人工客服）
- intent=high + accept → operations_sync（终态写入，成交！）
- 其他情况 → END（等待客户下一轮消息，继续培育）
"""

from graph.state import AgentState


def after_sales(state: AgentState) -> str:
    """销售节点出口条件

    决策优先级：
    1. 需要转人工 → human_handoff
    2. 高意向 + 接受 → operations_sync（成交！）
    3. 其他（中/低意向 or 意向不明）→ end（等待继续对话）

    Args:
        state: 当前 AgentState

    Returns:
        目标节点名称：'human_handoff' / 'operations_sync' / 'end'
    """
    # 优先级 1：需要转人工
    if state.get("need_human"):
        return "human_handoff"

    # 优先级 2：高意向接受 → 终态写入（成交）
    intent_level = state.get("intent_level", "mid")
    next_action = state.get("next_action", "revise")

    if intent_level == "high" or next_action == "accept":
        return "operations_sync"

    # 优先级 3：中/低意向 → 等待继续对话
    return "end"
