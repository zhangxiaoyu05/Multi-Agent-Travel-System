"""必填项检查条件边

trip_planner 节点执行后，检查出行需求必填项是否齐全、行程是否已生成。
"""

from graph.state import AgentState

REQUIRED_FIELDS = ["destination", "days", "arrival_date", "pax", "budget"]


def requirements_complete(state: AgentState) -> str:
    """检查需求必填项和行程生成状态

    决策逻辑：
    - 必填项齐全 且 已有行程草案 → intent_scorer（评分）
    - 其他情况（缺信息 或 无草案）→ end（等待用户下一轮消息）

    Args:
        state: 当前 AgentState

    Returns:
        目标节点名称：'intent_scorer' / 'end'
    """
    need = state.get("need", {}) or {}
    draft = state.get("draft", {}) or {}

    all_filled = all(need.get(f) for f in REQUIRED_FIELDS)
    has_itinerary = bool(draft.get("itinerary_md"))

    if all_filled and has_itinerary:
        return "intent_scorer"

    return "end"
