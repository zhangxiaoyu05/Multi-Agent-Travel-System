"""路由决策——节点版 + 条件版

v3: 拆分为两个函数：
  - route_decision_node: 节点函数，计算路由并写入 State（支持分支切换时重置信号）
  - route_condition: 条件边函数，从 current_branch 读取目标节点名

这样解决了条件边不能写入 State 的限制。
"""

from graph.state import AgentState

# 意图分类 → 目标节点名称映射
_BRANCH_MAP = {
    "service": "customer_service",
    "sales": "sales_agent",
    "operations": "operations_agent",
    "planner": "trip_planner",
}

# current_branch 偏向阈值：当 top-1 分数与 current_branch 分数差距 ≤ 此值时，
# 优先选择 current_branch（避免流程被意外打断）
_BRANCH_INERTIA_THRESHOLD = 0.25


# =============================================================================
# 节点函数（写入 State）
# =============================================================================

def route_decision_node(state: AgentState) -> dict:
    """根据意图分数决定目标分支，写入 current_branch + branch_history。

    同时在分支切换时重置上一个分支的控制信号（intent_level/next_action），
    防止跨分支语义污染。

    决策优先级：
        1. need_human 为 True → human_handoff
        2. current_branch 惯性偏向
        3. 取最高分意图 → 对应业务 Agent
        4. 所有意图分数 < 0.3 → customer_service（兜底）
    """
    scores = state.get("intent_scores", {})
    old_branch = state.get("current_branch", "")

    # 优先级 1：转人工
    if state.get("need_human"):
        new_branch = "human_handoff"
    elif not scores:
        new_branch = "customer_service"
    else:
        # 优先级 2-4：基于分数的路由
        max_key = max(scores, key=scores.get)
        max_score = scores[max_key]

        # 惯性偏向
        if old_branch and old_branch in _BRANCH_MAP.values():
            _reverse = {v: k for k, v in _BRANCH_MAP.items()}
            old_key = _reverse.get(old_branch)
            if old_key and old_key in scores:
                old_score = scores[old_key]
                gap = max_score - old_score
                if 0 < gap <= _BRANCH_INERTIA_THRESHOLD and max_key != old_key:
                    new_branch = old_branch
                elif max_score < 0.3:
                    new_branch = "customer_service"
                else:
                    new_branch = _BRANCH_MAP.get(max_key, "customer_service")
            elif max_score < 0.3:
                new_branch = "customer_service"
            else:
                new_branch = _BRANCH_MAP.get(max_key, "customer_service")
        elif max_score < 0.3:
            new_branch = "customer_service"
        else:
            new_branch = _BRANCH_MAP.get(max_key, "customer_service")

    # ---- 构建 State 更新 ----
    result: dict = {
        "current_branch": new_branch,
        # 追加分支历史
        "branch_history": [{
            "from": old_branch,
            "to": new_branch,
            "scores": scores,
        }],
    }

    # 分支切换时重置旧分支的控制信号（防止跨分支污染）
    if new_branch != old_branch:
        result["intent_level"] = ""
        result["next_action"] = ""

    return result


# =============================================================================
# 条件边函数（从 State 读取 current_branch）
# =============================================================================

def route_condition(state: AgentState) -> str:
    """根据 current_branch 返回目标节点名。

    必须在 route_decision_node 之后调用，因为 current_branch 由它写入。
    """
    branch = state.get("current_branch", "")
    if branch == "human_handoff":
        return "human_handoff"
    return _BRANCH_MAP.get(
        {v: k for k, v in _BRANCH_MAP.items()}.get(branch, ""),
        "customer_service",
    )


# =============================================================================
# 兼容旧接口
# =============================================================================

def route_decision(state: AgentState) -> str:
    """旧版兼容——直接返回目标节点名（不含 State 写入）。

    用于测试和简单场景。生产环境请使用 route_decision_node + route_condition。
    """
    if state.get("need_human"):
        return "human_handoff"

    scores = state.get("intent_scores", {})
    if not scores:
        return "customer_service"

    max_key = max(scores, key=scores.get)
    max_score = scores[max_key]

    old_branch = state.get("current_branch", "")
    if old_branch and old_branch in _BRANCH_MAP.values():
        _reverse = {v: k for k, v in _BRANCH_MAP.items()}
        old_key = _reverse.get(old_branch)
        if old_key and old_key in scores:
            old_score = scores[old_key]
            gap = max_score - old_score
            if 0 < gap <= _BRANCH_INERTIA_THRESHOLD and max_key != old_key:
                return old_branch

    if max_score < 0.3:
        return "customer_service"

    return _BRANCH_MAP.get(max_key, "customer_service")
