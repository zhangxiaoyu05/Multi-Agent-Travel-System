"""定制节点——图节点薄层包装

从 State 取数据，调 TripPlannerAgent，结果写回 State。
"""

from graph.state import AgentState
from agents.trip_planner import get_trip_planner_agent


def trip_planner(state: AgentState) -> dict:
    """定制分支入口节点

    调用 TripPlannerAgent 处理用户需求：
    - 提取需求字段并与已有 need 合并
    - 必填项不齐则追问
    - 齐全则查询 weather/calendar/inventory 并生成行程草案

    Args:
        state: 当前 AgentState

    Returns:
        dict 包含 need, draft, final_reply
    """
    agent = get_trip_planner_agent()
    result = agent.run(state)

    return {
        "need": result.get("need", {}),
        "draft": result.get("draft", {}),
        "final_reply": result.get("final_reply", ""),
        "current_branch": result.get("current_branch", "planner"),
    }
