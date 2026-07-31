"""销售节点——图节点薄层包装（异步版）"""

from graph.state import AgentState
from agents.sales_agent import get_sales_agent


async def sales_agent(state: AgentState) -> dict:
    agent = get_sales_agent()
    result = await agent.run(state)

    need_human = result.get("need_human", False)
    intent_level = result.get("intent_level", "mid")
    next_action = result.get("next_action", "revise")
    final_reply = result.get("final_reply", "")

    # 构建结构化报价（从回复中提取或由 Agent 提供）
    quote = result.get("quote", "")
    if not quote and "报价" in final_reply:
        quote = final_reply[:500]

    handoff = {}
    if need_human:
        handoff = {
            "from_agent": "sales_agent",
            "reason": "complaint" if any(
                kw in final_reply for kw in ["投诉", "退款", "诈骗", "太贵"]
            ) else "user_request",
            "priority": "urgent" if "投诉" in final_reply or "退款" in final_reply else "normal",
            "summary": f"销售流程中断，意向等级={intent_level}",
        }

    return {
        "final_reply": final_reply,
        "quote": quote,
        "need_human": need_human,
        "handoff": handoff,
        "intent_level": intent_level,
        "next_action": next_action,
        "current_branch": "sales",
        "agent_traces": [{
            "agent": "sales_agent",
            "action": "provided_quote" if quote else "engaged_customer",
            "outcome": f"intent={intent_level}, action={next_action}",
            "confidence": intent_level,
        }],
    }
