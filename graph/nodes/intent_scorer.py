"""意向评分——评估用户对行程草案的反馈（httpx 直连版）"""

from typing import Literal
from pydantic import BaseModel, Field
from graph.state import AgentState
from services.llm import get_router_llm


class ScorerResult(BaseModel):
    """意向评分结构化输出"""
    intent_level: Literal["high", "mid", "low"] = Field(
        description="high=满意成交, mid=需调整, low=可能流失"
    )
    next_action: Literal["accept", "revise", "give_up"] = Field(
        description="accept=结束, revise=修改, give_up=转人工"
    )
    reasoning: str = Field(default="", description="简短判断依据")


def _normalize_result(result: ScorerResult, revision_count: int) -> dict:
    intent_level = result.intent_level
    next_action = result.next_action

    if revision_count >= 3 and next_action == "revise":
        next_action = "give_up"
        intent_level = "low"

    if next_action == "accept" and intent_level == "low":
        intent_level = "mid"
    if next_action == "give_up" and intent_level == "high":
        intent_level = "low"

    return {"intent_level": intent_level, "next_action": next_action}


def intent_scorer(state: AgentState) -> dict:
    """根据用户最新消息和行程草案评估客户意向（同步）

    v4: accept 时设置 journey_stage="sales" + next_agent="sales_agent"，
    让下一轮自动进入销售流程。
    """
    messages = state.get("messages", [])
    user_feedback = ""
    if messages:
        last = messages[-1]
        user_feedback = last.content if hasattr(last, "content") else str(last)

    draft = state.get("draft", {})
    need = state.get("need", {}) or {}
    revision_count = state.get("revision_count", 0)
    itinerary = draft.get("itinerary_md", "")[:600]

    llm = get_router_llm()
    structured_llm = llm.with_structured_output(ScorerResult)

    try:
        result: ScorerResult = structured_llm.invoke([
            {
                "role": "system",
                "content": (
                    "你是一个客户意向分析助手。根据客户的最新消息和已生成的行程草案，"
                    "判断客户的意向等级和下一步行动。\n\n"
                    "## 判断规则\n"
                    "1. 客户消息含「确认」「预订」「支付」「不错」「满意」「可以」→ high + accept\n"
                    "2. 客户消息含「改」「加」「换」「调整」「能不能」→ mid + revise\n"
                    "3. 客户消息含「算了」「太贵」「不要」「取消」「放弃」→ low + give_up\n"
                    "4. 客户消息是对新需求/目的地的描述（非反馈）→ high + accept（正常结束）\n"
                    "5. 无法判断 → high + accept\n\n"
                    "intent_level 只能是 high/mid/low，next_action 只能是 accept/revise/give_up"
                ),
            },
            {
                "role": "user",
                "content": (
                    f"行程草案（摘要）：{itinerary}\n\n"
                    f"客户最新消息：{user_feedback}\n\n"
                    f"当前修订次数：{revision_count}/3"
                ),
            },
        ])
        normalized = _normalize_result(result, revision_count)
    except Exception:
        normalized = {"intent_level": "high", "next_action": "accept"}

    # ── v4: accept 时设置交接字段 ──
    response: dict = {
        **normalized,
        "agent_traces": [{
            "agent": "intent_scorer",
            "action": "scored_intent",
            "outcome": f"level={normalized['intent_level']}, action={normalized['next_action']}",
            "confidence": normalized["intent_level"],
        }],
    }

    if normalized["next_action"] == "accept":
        # 构建行程摘要供销售 Agent 使用
        dest = need.get("destination", "")
        days = need.get("days", 0)
        pax = need.get("pax", 0)
        budget = need.get("budget", "")
        theme = need.get("theme", "")

        draft_summary_parts = [f"{dest}{days}日游" if dest and days else ""]
        if theme:
            draft_summary_parts.append(f"偏好{theme}")
        draft_summary_parts = [p for p in draft_summary_parts if p]

        response.update({
            "journey_stage": "sales",
            "next_agent": "sales_agent",
            "handoff_context": {
                "reason": "draft_confirmed",
                "from_agent": "trip_planner",
                "draft_summary": "、".join(draft_summary_parts) if draft_summary_parts else "行程已确认",
                "draft_id": state.get("session_id", ""),
                "pipeline_stage": "qualified",
                "destination": dest,
                "days": days,
                "pax": pax,
                "budget": budget,
                "theme": theme,
                "itinerary_md": itinerary,
            },
        })
    else:
        # revise / give_up → 保持在 planning 阶段
        response["journey_stage"] = "planning"
        response["next_agent"] = "trip_planner"

    return response
