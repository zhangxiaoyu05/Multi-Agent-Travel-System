"""Mock CAPI（Conversion API）事件发送工具

模拟向广告平台/分析系统发送转化事件。
Phase 8 替换为真实 CAPI（Meta / Google / TikTok）调用。
"""

from langchain.tools import tool


@tool
def send_capi(event_type: str, event_data: str) -> str:
    """发送 CAPI 转化事件。

    将用户行为事件（会话完成、行程确认、转人工等）发送到分析系统。

    Args:
        event_type: 事件类型（session_completed / trip_confirmed / handoff / purchase）
        event_data: 事件附加数据（JSON 字符串）

    Returns:
        CAPI 发送结果描述
    """
    # Mock: 假装发送成功
    return (
        f"[CAPI] 事件「{event_type}」已发送。\n"
        f"事件数据：{event_data[:200]}...\n"
        f"状态：✅ 成功发送至分析平台"
    )
