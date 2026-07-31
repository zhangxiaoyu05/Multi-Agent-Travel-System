"""运营节点——图节点薄层包装（异步版）"""

from graph.state import AgentState
from agents.operations_agent import get_operations_agent


async def operations_agent(state: AgentState) -> dict:
    agent = get_operations_agent()
    result = await agent.run(state)
    return {
        "final_reply": result.get("final_reply", ""),
        "need_human": result.get("need_human", False),
        "current_branch": "operations",
    }
