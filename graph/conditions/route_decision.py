"""路由决策条件边

根据意图路由器的输出，决定下一步进入哪个业务分支。

v2: 加入 current_branch 惯性偏向——当 LLM 分数接近时，优先延续当前分支。
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

# 意图名 → State 中 intent_scores 的 key
_INTENT_TO_KEY = {
    "customer_service": "service",
    "sales_agent": "sales",
    "operations_agent": "operations",
    "trip_planner": "planner",
}

# current_branch 偏向阈值：当 top-1 分数与 current_branch 分数差距 ≤ 此值时，
# 优先选择 current_branch（避免流程被意外打断）
_BRANCH_INERTIA_THRESHOLD = 0.25


def route_decision(state: AgentState) -> str:
    """根据意图分数选择目标分支节点

    决策优先级：
        1. need_human 为 True → human_handoff（跳过正常路由）
        2. current_branch 惯性偏向（v2 新增）
        3. 取最高分意图 → 对应业务 Agent
        4. 所有意图分数 < 0.3 → customer_service（兜底）

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

    # 优先级 2.5（v2 新增）：current_branch 惯性偏向
    # 当 LLM 给出的最高分分支与当前分支不同，但分数接近时，
    # 优先保持当前分支——避免"补充日期/预算"这类自然跟进被打断
    current_branch = state.get("current_branch", "")
    if current_branch and current_branch in _BRANCH_MAP.values():
        _current_intent_key = {v: k for k, v in _BRANCH_MAP.items()}.get(current_branch)
        if _current_intent_key and _current_intent_key in scores:
            current_score = scores[_current_intent_key]
            gap = max_score - current_score
            if 0 < gap <= _BRANCH_INERTIA_THRESHOLD and max_branch != _current_intent_key:
                # 偏离不大，保持当前分支
                return current_branch

    # 优先级 3：低置信度兜底
    if max_score < 0.3:
        return "customer_service"

    return _BRANCH_MAP.get(max_branch, "customer_service")
