"""运营节点——图节点薄层包装（异步版）"""

from graph.state import AgentState
from agents.operations_agent import get_operations_agent


async def operations_agent(state: AgentState) -> dict:
    agent = get_operations_agent()
    result = await agent.run(state)

    need_human = result.get("need_human", False)
    final_reply = result.get("final_reply", "")

    handoff = {}
    if need_human:
        is_urgent = any(
            kw in final_reply for kw in ["事故", "安全", "媒体", "诈骗", "报警"]
        )
        handoff = {
            "from_agent": "operations_agent",
            "reason": "escalation" if is_urgent else "user_request",
            "priority": "urgent" if is_urgent else "normal",
            "summary": "运营问题需升级到人工处理",
        }

    return {
        "final_reply": final_reply,
        "need_human": need_human,
        "handoff": handoff,
        "current_branch": "operations_agent",
        "agent_traces": [{
            "agent": "operations_agent",
            "action": "handled_ops" if not need_human else "escalated",
            "outcome": "resolved" if not need_human else "handoff_to_human",
            "confidence": "high" if not need_human else "mid",
        }],
    }
