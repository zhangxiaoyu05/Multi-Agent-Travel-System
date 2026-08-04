"""销售后置条件边

销售节点执行完毕后，根据意向等级和转人工标志决定下一步：
- need_human=True  → human_handoff（交接人工客服）
- goto_planner=True → trip_planner（用户要修改行程）
- sales_pipeline_stage=won → operations_sync（成交！）
- sales_pipeline_stage=lost → end（流失，等待用户重新发起）
- 其他情况 → END（等待客户下一轮消息，继续培育）
"""

from graph.state import AgentState


def after_sales(state: AgentState) -> str:
    """销售节点出口条件

    决策优先级（Phase 20）：
    1. 需要转人工 → human_handoff
    2. 用户要修改行程 → trip_planner
    3. 成交 → operations_sync
    4. 流失 → end
    5. 其他（中/低意向 or 意向不明）→ end（等待继续对话）

    Args:
        state: 当前 AgentState

    Returns:
        目标节点名称：'human_handoff' / 'trip_planner' / 'operations_sync' / 'end'
    """
    # 优先级 1：需要转人工
    if state.get("need_human"):
        return "human_handoff"

    # 优先级 2：用户要修改行程 → 跳转 trip_planner
    if state.get("goto_planner"):
        return "trip_planner"

    # 优先级 3：成交 → 终态写入
    stage = state.get("sales_pipeline_stage", "")
    if stage == "won":
        return "operations_sync"

    # 优先级 4：流失 → end
    if stage == "lost":
        return "end"

    # 优先级 5：兼容旧版 intent_level 判断（过渡期）
    intent_level = state.get("intent_level", "mid")
    next_action = state.get("next_action", "revise")

    if intent_level == "high" or next_action == "accept":
        return "operations_sync"

    # 默认：等待继续对话
    return "end"
