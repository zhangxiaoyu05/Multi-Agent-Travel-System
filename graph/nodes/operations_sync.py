"""终态数据写入节点

所有会话终态（行程确认、转人工）在返回用户前经过此节点，
执行 CRM 写入和 CAPI 事件发送。

MVP 阶段全部 Mock，Phase 8 切换为真实 API。
"""

from graph.state import AgentState
from tools.mock_crm import update_crm
from tools.mock_capi import send_capi


def operations_sync(state: AgentState) -> dict:
    """终态数据同步——写 CRM + 发 CAPI 事件

    这是一个透传节点：保留已有的 final_reply 不变，
    在后台完成数据持久化和事件上报。

    触发场景：
    1. 行程确认（accept / high）→ 记录成交意向
    2. 转人工（human_handoff）→ 记录服务升级
    3. 客服 FAQ 正常结束 → 记录客户接触

    Args:
        state: 当前 AgentState

    Returns:
        dict（透传 final_reply，静默完成数据写入）
    """
    customer_id = state.get("customer_id", "unknown")
    branch = state.get("current_branch", "")
    intent_level = state.get("intent_level", "")
    next_action = state.get("next_action", "")
    need_human = state.get("need_human", False)
    need = state.get("need", {}) or {}
    draft = state.get("draft", {}) or {}
    revision_count = state.get("revision_count", 0)
    handoff = state.get("handoff", {}) or {}

    # ---- 确定事件类型（v2: 优先用 handoff 上下文） ----
    if need_human:
        reason = handoff.get("reason", "unknown")
        if reason in ("complaint", "escalation"):
            event_type = "escalation"
        else:
            event_type = "handoff"
    elif intent_level == "high" or next_action == "accept":
        event_type = "trip_confirmed"
    elif draft.get("itinerary_md"):
        event_type = "session_completed"
    else:
        event_type = "session_completed"

    # ---- 构建会话摘要 ----
    session_summary = {
        "branch": branch,
        "intent_level": intent_level,
        "next_action": next_action,
        "revision_count": revision_count,
        "need_human": need_human,
        "destination": need.get("destination", ""),
        "days": need.get("days", 0),
        "arrival_date": need.get("arrival_date", ""),
        "pax": need.get("pax", 0),
        "budget": need.get("budget", ""),
        "draft_version": draft.get("version", 0),
    }

    import json
    session_data_str = json.dumps(session_summary, ensure_ascii=False)
    event_data_str = json.dumps({
        "customer_id": customer_id,
        "event_type": event_type,
        "branch": branch,
    }, ensure_ascii=False)

    # ---- 执行写入 ----
    try:
        crm_result = update_crm.invoke({
            "customer_id": customer_id,
            "session_data": session_data_str,
        })
        capi_result = send_capi.invoke({
            "event_type": event_type,
            "event_data": event_data_str,
        })
    except Exception:
        crm_result = "[CRM] 写入失败（Mock，忽略）"
        capi_result = "[CAPI] 发送失败（Mock，忽略）"

    # ---- 透传：不改变 final_reply ----
    return {
        "final_reply": state.get("final_reply", ""),
        "agent_traces": [{
            "agent": "operations_sync",
            "action": "synced_to_crm_capi",
            "outcome": f"event={event_type}, crm={crm_result[:50]}",
            "confidence": "high",
        }],
    }
