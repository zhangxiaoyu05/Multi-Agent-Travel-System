"""路由决策条件边

根据意图路由器的输出，决定下一步进入哪个业务分支。
"""

from graph.state import AgentState

# 意图分类 → 目标节点名称映射
# MVP 阶段销售(sales)和运营(operations)暂不启用，兜底到客服
_BRANCH_MAP = {
    "service": "customer_service",
    "sales": "sales_agent",
    "operations": "operations_agent",
    "planner": "trip_planner",
}


def route_decision(state: AgentState) -> str:
    """根据意图分数选择目标分支节点

    决策优先级：
        1. need_human 为 True → human_handoff（跳过正常路由）
        2. 取最高分意图 → 对应业务 Agent
        3. 所有意图分数 < 0.3 → customer_service（兜底）

    Args:
        state: 当前 AgentState

    Returns:
        目标节点名称字符串
    """
    # 优先级 1：转人工
    if state.get("need_human"):
        return "human_handoff"

    scores = state.get("intent_scores", {})
    if not scores:
        return "customer_service"

    # 优先级 2：最高分意图
    max_branch = max(scores, key=scores.get)
    max_score = scores[max_branch]

    # 优先级 3：低置信度兜底
    if max_score < 0.3:
        return "customer_service"

    return _BRANCH_MAP.get(max_branch, "customer_service")
