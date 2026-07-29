"""客服节点——图节点薄层包装

从 State 取数据，调 Agent，结果写回 State。
遵循 graph/nodes/ 薄层原则：不做业务逻辑，只做数据搬运。
"""

from graph.state import AgentState
from agents.customer_service import get_customer_service_agent


def customer_service(state: AgentState) -> dict:
    """客服分支入口节点

    调用 CustomerServiceAgent 处理用户消息，
    将 Agent 返回的 final_reply 和 need_human 写回 State。

    Args:
        state: 当前 AgentState

    Returns:
        dict 包含 final_reply 和 need_human
    """
    agent = get_customer_service_agent()

    result = agent.run(state)

    return {
        "final_reply": result.get("final_reply", ""),
        "need_human": result.get("need_human", False),
        "current_branch": "service",
    }
