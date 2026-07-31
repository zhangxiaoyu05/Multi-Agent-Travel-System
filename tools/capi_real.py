"""真实 CAPI（Conversion API）——预留接口

需要对接：
- Meta Conversions API (Facebook/Instagram 广告归因)
- Google Ads Conversion Tracking
- TikTok Events API

实现方式：使用 httpx 发送 POST 请求到各平台 Conversions API。

当前骨架直接 raise NotImplementedError。
"""


def send_capi_real(event_type: str, event_data: str) -> str:
    """真实 CAPI 事件发送——待对接广告平台。

    Args:
        event_type: 事件类型（session_completed/trip_confirmed/handoff/purchase）
        event_data: 事件数据 JSON 字符串

    Raises:
        NotImplementedError: 尚未实现真实 CAPI 对接
    """
    raise NotImplementedError(
        "真实 CAPI 尚未对接。\n\n"
        "需要对接以下平台：\n"
        "1. Meta Conversions API —— Facebook/Instagram 广告转化回传\n"
        "2. Google Ads Conversion Tracking\n"
        "3. TikTok Events API\n\n"
        f"事件类型：{event_type}"
    )
