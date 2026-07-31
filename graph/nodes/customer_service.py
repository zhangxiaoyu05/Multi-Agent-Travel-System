"""客服节点——图节点薄层包装（异步版）"""

from graph.state import AgentState
from agents.customer_service import get_customer_service_agent


async def customer_service(state: AgentState) -> dict:
    agent = get_customer_service_agent()
    result = await agent.run(state)

    need_human = result.get("need_human", False)
    handoff = {}
    if need_human:
        handoff = {
            "from_agent": "customer_service",
            "reason": "complaint" if "投诉" in result.get("final_reply", "") else "faq_not_covered",
            "priority": "urgent" if "投诉" in result.get("final_reply", "") else "normal",
            "summary": "客服 FAQ 无法覆盖，用户需要人工介入",
        }

    return {
        "final_reply": result.get("final_reply", ""),
        "need_human": need_human,
        "handoff": handoff,
        "current_branch": "service",
        "agent_traces": [{
            "agent": "customer_service",
            "action": "answered_faq" if not need_human else "requested_handoff",
            "outcome": "replied" if not need_human else "escalated_to_human",
            "confidence": "high",
        }],
    }
