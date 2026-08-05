"""定制节点——图节点薄层包装（异步版，v4 透传 journey_stage）"""

from graph.state import AgentState
from agents.trip_planner import get_trip_planner_agent


async def trip_planner(state: AgentState) -> dict:
    agent = get_trip_planner_agent()
    result = await agent.run(state)

    draft = result.get("draft", {})
    has_draft = bool(draft.get("itinerary_md"))
    missing = not all(
        result.get("need", {}).get(f)
        for f in ["destination", "days", "arrival_date", "pax", "budget"]
    )

    return {
        "need": result.get("need", {}),
        "draft": draft,
        "final_reply": result.get("final_reply", ""),
        "current_branch": result.get("current_branch", "trip_planner"),
        "journey_stage": result.get("journey_stage", "planning"),
        "next_agent": result.get("next_agent", "trip_planner"),
        "agent_traces": [{
            "agent": "trip_planner",
            "action": "generated_draft" if has_draft else "asked_missing_fields",
            "outcome": f"draft_v{draft.get('version', 0)}" if has_draft else "awaiting_info",
            "confidence": "high" if has_draft and not missing else "mid" if has_draft else "low",
        }],
    }
