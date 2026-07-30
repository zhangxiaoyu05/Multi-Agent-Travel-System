"""运营节点——图节点薄层包装

从 State 取数据，调 OperationsAgent，结果写回 State。
"""

from graph.state import AgentState
from agents.operations_agent import get_operations_agent


def operations_agent(state: AgentState) -> dict:
    """运营分支入口节点

    调用 OperationsAgent 处理运营任务：
    - 商家入驻、订单履约、售后工单、平台规则
    - 所有操作写入 CRM + 发送 CAPI 事件
    - 严重投诉升级转人工

    Args:
        state: 当前 AgentState

    Returns:
        dict 包含 final_reply, need_human
    """
    agent = get_operations_agent()
    result = agent.run(state)

    return {
        "final_reply": result.get("final_reply", ""),
        "need_human": result.get("need_human", False),
        "current_branch": "operations",
    }
