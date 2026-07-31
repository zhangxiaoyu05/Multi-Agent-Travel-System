"""销售节点——图节点薄层包装（异步版）"""

from graph.state import AgentState
from agents.sales_agent import get_sales_agent


async def sales_agent(state: AgentState) -> dict:
    agent = get_sales_agent()
    result = await agent.run(state)
    return {
        "final_reply": result.get("final_reply", ""),
        "need_human": result.get("need_human", False),
        "intent_level": result.get("intent_level", "mid"),
        "next_action": result.get("next_action", "revise"),
        "current_branch": "sales",
    }
