"""定制节点——图节点薄层包装（异步版）"""

from graph.state import AgentState
from agents.trip_planner import get_trip_planner_agent


async def trip_planner(state: AgentState) -> dict:
    agent = get_trip_planner_agent()
    result = await agent.run(state)
    return {
        "need": result.get("need", {}),
        "draft": result.get("draft", {}),
        "final_reply": result.get("final_reply", ""),
        "current_branch": result.get("current_branch", "planner"),
    }
