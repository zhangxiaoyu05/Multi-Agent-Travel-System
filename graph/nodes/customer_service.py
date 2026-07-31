"""客服节点——图节点薄层包装（异步版）"""

from graph.state import AgentState
from agents.customer_service import get_customer_service_agent


async def customer_service(state: AgentState) -> dict:
    agent = get_customer_service_agent()
    result = await agent.run(state)
    return {
        "final_reply": result.get("final_reply", ""),
        "need_human": result.get("need_human", False),
        "current_branch": "service",
    }
