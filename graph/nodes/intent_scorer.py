"""意向评分——评估用户对行程草案的反馈

当行程草案生成后，分析用户反馈（或接受信号），
输出意向等级（high/mid/low）和下一步行动（accept/revise/give_up）。
"""

from typing import Literal
from pydantic import BaseModel, Field
from graph.state import AgentState
from services.llm import get_router_llm


class ScorerResult(BaseModel):
    """意向评分结构化输出——使用 Literal 严格约束"""
    intent_level: Literal["high", "mid", "low"] = Field(
        description="意向等级：high=满意准备成交, mid=有兴趣但需调整, low=不满意可能流失"
    )
    next_action: Literal["accept", "revise", "give_up"] = Field(
        description="下一步行动：accept=接受行程结束流程, revise=需要修改行程, give_up=放弃转人工"
    )
    reasoning: str = Field(default="", description="简短判断依据（10字以内）")


def _normalize_result(result: ScorerResult, revision_count: int) -> dict:
    """后处理：确保输出值在合法范围内，做兜底修正"""
    intent_level = result.intent_level
    next_action = result.next_action

    # 如果修订次数已达上限，强制 accept 或 give_up
    if revision_count >= 3 and next_action == "revise":
        next_action = "give_up"
        intent_level = "low"

    # 确保 intent_level 和 next_action 的一致性
    if next_action == "accept" and intent_level == "low":
        intent_level = "mid"
    if next_action == "give_up" and intent_level == "high":
        intent_level = "low"

    return {
        "intent_level": intent_level,
        "next_action": next_action,
    }


def intent_scorer(state: AgentState) -> dict:
    """根据用户最新消息和行程草案，评估客户意向

    评分逻辑：
    - 客户满意/确认/要求下一步 → high + accept
    - 客户要求修改/有调整意见 → mid + revise
    - 客户明显不满意/放弃/超预算 → low + give_up

    特殊情况：
    - 首次生成行程（revision_count=0）且无明确反馈 → high + accept（正常结束）
    - 修订次数已达上限 → 禁止 revise，只能 accept 或 give_up

    Args:
        state: 当前 AgentState

    Returns:
        dict 包含 intent_level, next_action
    """
    messages = state.get("messages", [])
    user_feedback = ""
    if messages:
        last = messages[-1]
        user_feedback = last.content if hasattr(last, "content") else str(last)

    draft = state.get("draft", {})
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
                    "1. 如果客户消息包含「确认」「预订」「支付」「不错」「满意」「可以」"
                    "等词汇 → intent_level='high', next_action='accept'\n"
                    "2. 如果客户消息包含「改」「加」「换」「调整」「能不能」"
                    "等词汇 → intent_level='mid', next_action='revise'\n"
                    "3. 如果客户消息包含「算了」「太贵」「不要」「取消」「放弃」"
                    "等词汇 → intent_level='low', next_action='give_up'\n"
                    "4. 如果客户消息是对新需求/目的地的描述（而非对草案的反馈），"
                    "→ intent_level='high', next_action='accept'（正常结束流程）\n"
                    "5. 如果无法明确判断 → intent_level='high', next_action='accept'\n\n"
                    "## 重要约束\n"
                    "- intent_level 只能是 'high', 'mid', 'low' 之一\n"
                    "- next_action 只能是 'accept', 'revise', 'give_up' 之一\n"
                    "- 不要输出任何其他值！"
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

        return _normalize_result(result, revision_count)

    except Exception:
        # LLM 调用失败 → 默认 accept，让流程结束
        return {
            "intent_level": "high",
            "next_action": "accept",
        }
