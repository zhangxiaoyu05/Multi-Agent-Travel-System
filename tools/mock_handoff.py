"""Mock 转人工评估工具

根据用户消息内容和上下文，判断是否需要转接人工客服。
"""

from langchain.tools import tool


# 触发转人工的关键词
_HANDOFF_KEYWORDS = [
    "投诉", "退款", "差评", "人工", "真人",
    "我要投诉", "找你们领导", "叫你们经理",
    "骗人", "诈骗", "报警",
]

# 退改 + 投诉的复合关键词（强信号）
_STRONG_SIGNALS = ["投诉", "退款我要", "全部退款", "全额退款"]


@tool
def check_handoff(message: str) -> str:
    """评估当前对话是否需要转接人工客服。

    根据用户消息中的关键词判断是否需要人工介入。
    触发条件包括：投诉、退款争议、明确要求人工、情绪激动的负面反馈。

    Args:
        message: 用户的最新消息文本

    Returns:
        评估结果字符串，包含是否需要转人工的判断和原因。
    """
    # 强信号：立即转人工
    for kw in _STRONG_SIGNALS:
        if kw in message:
            return (
                "【需要转人工】检测到强烈投诉/退款信号。\n"
                "原因：用户消息包含「投诉」或「退款争议」关键词，情绪可能较为激动。\n"
                "建议：立即转接人工客服，由经验丰富的客服专员处理。"
            )

    # 一般信号
    matched = [kw for kw in _HANDOFF_KEYWORDS if kw in message]
    if matched:
        return (
            f"【需要转人工】检测到关键词：{'、'.join(matched)}。\n"
            "建议：转接人工客服处理，确保用户满意度。"
        )

    # 消息过长，可能包含复杂诉求
    if len(message) > 500:
        return (
            "【需要转人工】用户消息较长（>500字），可能包含复杂诉求。\n"
            "建议：转人工客服详细跟进。"
        )

    return "【无需转人工】当前问题可由 AI 客服自行处理。"
