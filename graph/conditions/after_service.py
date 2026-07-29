"""客服后置条件边

客服节点执行完毕后，根据 need_human 标志决定下一步：
- need_human=True  → human_handoff（生成交接单）
- 有 final_reply   → END（正常结束）
- 无 final_reply   → intent_router（重新路由，处理追问）
"""

from graph.state import AgentState


def after_service(state: AgentState) -> str:
    """客服节点出口条件

    决策优先级：
    1. 需要转人工 → human_handoff
    2. 已有回复 → end（正常结束，直接输出 final_reply）
    3. 无回复 → intent_router（重新分类）

    Args:
        state: 当前 AgentState

    Returns:
        目标节点名称：'human_handoff' / 'end' / 'intent_router'
    """
    # 优先级 1：需要转人工
    if state.get("need_human"):
        return "human_handoff"

    # 优先级 2：已有回复，正常结束
    if state.get("final_reply"):
        return "end"

    # 优先级 3：兜底——重新路由
    return "intent_router"
