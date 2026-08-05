"""运营接管节点——销售成交后自动生成运营开场消息（Phase 21）

在 sales WON 之后、operations_sync 之前执行。
检测 sales_pipeline_stage == "won"，生成运营接管开场白，
与销售的 final_reply 合并后返回。
"""

from graph.state import AgentState


async def operations_handoff(state: AgentState) -> dict:
    """运营接管——WON 时生成接管消息

    此节点在 after_sales 检测到 won 后触发。
    调用 OperationsAgent 生成接管开场白，
    合并到 final_reply 中形成无缝交接。
    """
    from agents.operations_agent import get_operations_agent

    agent = get_operations_agent()
    result = await agent.run(state)

    # 原有的销售 final_reply + 运营接管消息
    existing_reply = state.get("final_reply", "")
    ops_reply = result.get("final_reply", "")

    if ops_reply and existing_reply:
        combined_reply = f"{existing_reply}\n\n---\n\n{ops_reply}"
    elif ops_reply:
        combined_reply = ops_reply
    else:
        combined_reply = existing_reply

    return {
        "final_reply": combined_reply,
        "need_human": result.get("need_human", False),
        "order_context": result.get("order_context", {}),
        "current_branch": "operations_agent",
        "agent_traces": [{
            "agent": "operations_agent",
            "action": "handoff_from_sales",
            "outcome": "接管已成交订单",
            "confidence": "high",
        }],
    }
