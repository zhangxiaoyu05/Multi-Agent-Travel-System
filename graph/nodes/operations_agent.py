"""运营节点——图节点薄层包装（异步版，Phase 22 更新）

v4: 透传 journey_stage / next_agent / handoff_context
"""

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

    # 确定 action 和 outcome
    if need_human:
        action = "escalated"
        outcome = "handoff_to_human"
    elif result.get("order_context", {}).get("order_id"):
        action = "handled_order"
        outcome = "order_processed"
    else:
        action = "handled_ops"
        outcome = "resolved"

    return {
        "final_reply": final_reply,
        "need_human": need_human,
        "handoff": handoff,
        "order_context": result.get("order_context", {}),
        "current_branch": "operations_agent",
        # v4: 透传 journey 字段
        "journey_stage": result.get("journey_stage", "post_purchase"),
        "next_agent": result.get("next_agent", "operations_agent"),
        "handoff_context": result.get("handoff_context", {}),
        "agent_traces": [{
            "agent": "operations_agent",
            "action": action,
            "outcome": outcome,
            "confidence": "high" if not need_human else "mid",
        }],
    }
