"""人工接管——生成交接摘要

v2: 使用 HandoffContext 结构化上下文，替代裸 need_human 判断。
交接单包含：谁触发、为什么、紧急程度、完整业务数据、最近对话。
"""

from graph.state import AgentState


def human_handoff(state: AgentState) -> dict:
    """生成转人工交接摘要

    从 State 中提取当前会话的核心信息：
    - handoff 上下文（v2 新增：from_agent / reason / priority / summary）
    - 客户标识和渠道
    - 当前分支和意图分数
    - 已收集的出行需求（如有）
    - 行程草案版本（如有）
    - 报价单（如有）
    - 最近对话历史摘要
    - Agent 执行审计日志

    Args:
        state: 当前 AgentState

    Returns:
        dict 包含 final_reply（交接单文本）和 need_human=True
    """
    handoff = state.get("handoff", {}) or {}

    # ---- 优先级标签 ----
    priority = handoff.get("priority", "normal")
    priority_label = {
        "urgent": "🔴 紧急",
        "normal": "🟡 普通",
    }.get(priority, "🟡 普通")

    lines = [
        "=" * 40,
        f"转人工交接单  {priority_label}",
        "=" * 40,
        "",
    ]

    # ---- 触发原因（v2：从 handoff 上下文读取） ----
    lines.append(f"触发来源   : {handoff.get('from_agent', 'unknown')}")
    lines.append(f"触发原因   : {handoff.get('reason', 'unknown')}")
    lines.append(f"紧急程度   : {priority}")
    if handoff.get("summary"):
        lines.append(f"摘要       : {handoff['summary']}")
    lines.append("")

    # ---- 会话信息 ----
    lines.extend([
        f"客户 ID    : {state.get('customer_id', 'N/A')}",
        f"会话 ID    : {state.get('session_id', 'N/A')}",
        f"来源渠道   : {state.get('channel', 'N/A')}",
        f"语言偏好   : {state.get('language', 'zh')}",
        f"当前分支   : {state.get('current_branch', 'N/A')}",
    ])

    # 意图分数
    scores = state.get("intent_scores", {})
    if scores:
        lines.append(f"意图分数   : {scores}")

    lines.append("")

    # ---- 出行需求 ----
    need = state.get("need", {}) or {}
    if need and any(v for v in need.values()):
        lines.append("-" * 40)
        lines.append("已收集的出行需求")
        lines.append("-" * 40)
        if need.get("destination"):
            lines.append(f"  目的地     : {need['destination']}")
        if need.get("days"):
            lines.append(f"  天数       : {need['days']} 天")
        if need.get("arrival_date"):
            lines.append(f"  抵达日期   : {need['arrival_date']}")
        if need.get("pax"):
            lines.append(f"  人数       : {need['pax']} 人")
        if need.get("budget"):
            lines.append(f"  预算       : {need['budget']}")
        if need.get("theme"):
            lines.append(f"  偏好主题   : {need['theme']}")
        if need.get("pace"):
            lines.append(f"  节奏偏好   : {need['pace']}")
        if need.get("special_requests"):
            lines.append(f"  特殊需求   : {need['special_requests']}")

    # ---- 行程草案 ----
    draft = state.get("draft", {}) or {}
    if draft.get("version"):
        lines.append("")
        lines.append("-" * 40)
        lines.append(f"行程草案 v{draft['version']}")
        lines.append("-" * 40)
        lines.append(f"  修订次数   : {state.get('revision_count', 0)}")
        if draft.get("itinerary_md"):
            itinerary = draft["itinerary_md"][:500]
            lines.append(f"  行程摘要   : {itinerary}...")
        if draft.get("estimated_cost"):
            lines.append(f"  预估费用   : {draft['estimated_cost']}")

    # ---- 报价单（v2：从 sales_agent 的 quote 字段读取） ----
    quote = state.get("quote", "")
    if quote:
        lines.append("")
        lines.append("-" * 40)
        lines.append("报价单")
        lines.append("-" * 40)
        lines.append(f"  {quote[:400]}")

    # ---- 最近对话 ----
    messages = state.get("messages", [])
    if messages:
        last = messages[-1]
        last_text = last.content if hasattr(last, "content") else str(last)
        lines.append("")
        lines.append("-" * 40)
        lines.append("最后一条用户消息")
        lines.append("-" * 40)
        lines.append(f"  {last_text[:300]}")

    # ---- Agent 执行审计（v2 新增） ----
    traces = state.get("agent_traces", [])
    if traces:
        lines.append("")
        lines.append("-" * 40)
        lines.append("Agent 执行链")
        lines.append("-" * 40)
        for t in traces[-6:]:  # 最近 6 条
            agent = t.get("agent", "?")
            action = t.get("action", "?")
            outcome = t.get("outcome", "?")
            lines.append(f"  {agent} → {action} → {outcome}")

    lines.append("")
    lines.append("=" * 40)

    return {
        "final_reply": "\n".join(lines),
        "need_human": True,
        "agent_traces": [{
            "agent": "human_handoff",
            "action": "generated_handoff_ticket",
            "outcome": f"priority={priority}, from={handoff.get('from_agent', 'unknown')}",
            "confidence": "high",
        }],
    }
