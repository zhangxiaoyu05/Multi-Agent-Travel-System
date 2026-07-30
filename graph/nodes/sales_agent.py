"""销售节点——图节点薄层包装

从 State 取数据，调 SalesAgent，结果写回 State。
"""

from graph.state import AgentState
from agents.sales_agent import get_sales_agent


def sales_agent(state: AgentState) -> dict:
    """销售分支入口节点

    调用 SalesAgent 处理销售咨询：
    - 产品推介、报价生成、库存查询
    - 评估购买意向等级
    - 检测是否需要转人工

    Args:
        state: 当前 AgentState

    Returns:
        dict 包含 final_reply, need_human, intent_level, next_action
    """
    agent = get_sales_agent()
    result = agent.run(state)

    return {
        "final_reply": result.get("final_reply", ""),
        "need_human": result.get("need_human", False),
        "intent_level": result.get("intent_level", "mid"),
        "next_action": result.get("next_action", "revise"),
        "current_branch": "sales",
    }
