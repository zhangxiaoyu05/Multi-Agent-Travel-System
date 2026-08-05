"""路由决策——节点版 + 条件版

v4: Journey Stage 驱动的多 Agent 路由。

路由优先级（从高到低）：
    1. need_human → human_handoff（强制）
    2. force_branch → 指定分支（support 模式）
    3. next_agent 显式声明 → 映射到对应分支
    4. journey_stage ≠ discovery → 映射到对应分支
    5. intent_scores 分类（仅 discovery 阶段）
"""

from graph.state import AgentState

# 意图分类 → 目标节点名称映射
_BRANCH_MAP = {
    "service": "customer_service",
    "sales": "sales_agent",
    "operations": "operations_agent",
    "planner": "trip_planner",
}

# Journey Stage → 默认分支映射
_STAGE_TO_BRANCH = {
    "planning": "trip_planner",
    "sales": "sales_agent",
    "post_purchase": "operations_agent",
    "discovery": None,  # 走 intent 分类
}

# Agent 名称 → 分支名映射（next_agent 值 → branch 值）
_AGENT_TO_BRANCH = {
    "trip_planner": "trip_planner",
    "sales_agent": "sales_agent",
    "operations_agent": "operations_agent",
    "customer_service": "customer_service",
}

# current_branch 偏向阈值
_BRANCH_INERTIA_THRESHOLD = 0.25


# =============================================================================
# 辅助函数
# =============================================================================

def _build_stage_scores(stage: str) -> dict:
    """根据 journey_stage 构建对应的 intent_scores（非 discovery 阶段使用）。

    用于 intent_router 透传阶段意图，保持 State 中 intent_scores 的一致性。
    """
    key_map = {
        "planning": "planner",
        "sales": "sales",
        "post_purchase": "operations",
    }
    key = key_map.get(stage, "service")
    scores = {"service": 0.05, "sales": 0.05, "operations": 0.05, "planner": 0.05}
    scores[key] = 0.85
    return scores


# =============================================================================
# 节点函数（写入 State）
# =============================================================================

def route_decision_node(state: AgentState) -> dict:
    """根据 Journey Stage + next_agent 决定目标分支，写入 current_branch。

    同时在分支切换时重置上一个分支的控制信号（intent_level/next_action），
    防止跨分支语义污染。

    决策优先级：
        1. need_human 为 True → human_handoff
        2. force_branch 非空 → 对应分支
        3. next_agent 显式声明 → 对应分支
        4. journey_stage ≠ discovery → 阶段映射
        5. intent_scores 分类（discovery 兜底）
    """
    # 优先级 0：强制路由（support 模式跳过意图识别）
    force = state.get("force_branch", "")
    if force:
        return {
            "current_branch": force,
            "branch_history": [{"from": state.get("current_branch", ""), "to": force, "force": True}],
        }

    old_branch = state.get("current_branch", "")

    # 优先级 1：转人工
    if state.get("need_human"):
        new_branch = "human_handoff"
    # 优先级 2：next_agent 显式声明
    elif state.get("next_agent"):
        new_branch = _AGENT_TO_BRANCH.get(
            state["next_agent"],
            "customer_service",
        )
    # 优先级 3：journey_stage 驱动
    elif state.get("journey_stage"):
        stage = state["journey_stage"]
        mapped = _STAGE_TO_BRANCH.get(stage)
        if mapped:
            new_branch = mapped
        else:
            # discovery → 走 intent 分类（优先级 4）
            new_branch = _intent_classify(state)
    else:
        # 无 journey_stage → 走 intent 分类
        new_branch = _intent_classify(state)

    # ---- 构建 State 更新 ----
    result: dict = {
        "current_branch": new_branch,
        "branch_history": [{
            "from": old_branch,
            "to": new_branch,
            "scores": state.get("intent_scores", {}),
        }],
    }

    # 分支切换时重置旧分支的控制信号（防止跨分支污染）
    if new_branch != old_branch:
        result["intent_level"] = ""
        result["next_action"] = ""

    # 如果 journey_stage 驱动了路由，同步更新 intent_scores
    if not state.get("next_agent") and state.get("journey_stage", "discovery") != "discovery":
        if state["journey_stage"] in _STAGE_TO_BRANCH and _STAGE_TO_BRANCH[state["journey_stage"]]:
            result["intent_scores"] = _build_stage_scores(state["journey_stage"])

    return result


def _intent_classify(state: AgentState) -> str:
    """基于 intent_scores 的分类逻辑（discovery 阶段使用）。

    保持原有的惯性偏向逻辑。
    """
    scores = state.get("intent_scores", {})
    old_branch = state.get("current_branch", "")

    if not scores:
        return "customer_service"

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
                return old_branch
            elif max_score < 0.3:
                return "customer_service"
            else:
                return _BRANCH_MAP.get(max_key, "customer_service")
        elif max_score < 0.3:
            return "customer_service"
        else:
            return _BRANCH_MAP.get(max_key, "customer_service")

    if max_score < 0.3:
        return "customer_service"
    return _BRANCH_MAP.get(max_key, "customer_service")


# =============================================================================
# 条件边函数（从 State 读取 current_branch）
# =============================================================================

def route_condition(state: AgentState) -> str:
    """根据 current_branch 返回目标节点名。

    必须在 route_decision_node 之后调用，因为 current_branch 由它写入。

    v4: 新增 next_agent 直通——如果 Agent 已声明下一站，直接映射返回。
    """
    force = state.get("force_branch", "")
    if force:
        return force
    branch = state.get("current_branch", "")
    if branch == "human_handoff":
        return "human_handoff"
    # 如果 next_agent 已设置，优先使用
    if state.get("next_agent"):
        return _AGENT_TO_BRANCH.get(state["next_agent"], "customer_service")
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

    # v4: journey_stage 驱动
    if state.get("next_agent"):
        return _AGENT_TO_BRANCH.get(state["next_agent"], "customer_service")

    stage = state.get("journey_stage", "")
    if stage and stage in _STAGE_TO_BRANCH:
        branch = _STAGE_TO_BRANCH[stage]
        if branch:
            return branch

    return _intent_classify(state)
