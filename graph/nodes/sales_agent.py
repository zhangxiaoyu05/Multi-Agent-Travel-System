"""销售节点——图节点薄层包装（Phase 20 重写）

适配新的 SalesAgent 返回结构：
- sales_pipeline_stage: 当前 Pipeline 阶段
- goto_planner: 是否要跳转到 trip_planner 修改行程
- quote: 结构化报价文本
"""

from graph.state import AgentState
from agents.sales_agent import get_sales_agent


async def sales_agent(state: AgentState) -> dict:
    agent = get_sales_agent()
    result = await agent.run(state)

    need_human = result.get("need_human", False)
    final_reply = result.get("final_reply", "")
    sales_pipeline_stage = result.get("sales_pipeline_stage", "lead")
    goto_planner = result.get("goto_planner", False)
    quote = result.get("quote", "")

    # 构建转人工上下文
    handoff = {}
    if need_human:
        handoff = {
            "from_agent": "sales_agent",
            "reason": "complaint" if any(
                kw in final_reply for kw in ["投诉", "退款", "诈骗", "太贵"]
            ) else "user_request",
            "priority": "urgent" if "投诉" in final_reply or "退款" in final_reply else "normal",
            "summary": f"销售流程中断，Pipeline阶段={sales_pipeline_stage}",
        }

    # 构建 agent_traces
    action = "provided_quote" if quote else "engaged_customer"
    if goto_planner:
        action = "redirected_to_planner"
    elif sales_pipeline_stage == "won":
        action = "closed_deal"
    elif sales_pipeline_stage == "lost":
        action = "marked_lost"

    return {
        "final_reply": final_reply,
        "quote": quote,
        "need_human": need_human,
        "handoff": handoff,
        "sales_pipeline_stage": sales_pipeline_stage,
        "goto_planner": goto_planner,
        "intent_level": result.get("intent_level", "mid"),
        "next_action": result.get("next_action", "revise"),
        "current_branch": "sales_agent",
        "agent_traces": [{
            "agent": "sales_agent",
            "action": action,
            "outcome": f"pipeline={sales_pipeline_stage}",
            "confidence": result.get("intent_level", "mid"),
        }],
    }
