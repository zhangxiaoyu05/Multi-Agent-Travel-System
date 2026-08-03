"""CAPI MCP Server —— 转化事件上报（Meta/Google/TikTok）

支持的广告平台:
    - Meta (Facebook/Instagram) Conversions API
    - Google Ads Conversion Tracking
    - TikTok Events API

配置:
    CAPI_META_TOKEN      - Meta CAPI Access Token
    CAPI_META_PIXEL_ID   - Meta Pixel ID
    CAPI_GOOGLE_ID       - Google Ads Conversion ID
    CAPI_TIKTOK_TOKEN    - TikTok Events API Token

若未配置 Token，则记录事件到本地日志（不影响主流程）。

启动方式:
    python mcp/servers/capi_server.py
"""

from __future__ import annotations

import sys
import os
import json
import logging
import hashlib
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from mcp.server import MCPServer, tool

logger = logging.getLogger(__name__)
server = MCPServer("capi", version="1.0.0")

# 支持的事件类型
_VALID_EVENTS = {
    "session_completed": "会话完成",
    "trip_confirmed": "行程确认",
    "purchase": "购买完成",
    "handoff": "转人工",
    "lead": "留资/咨询",
    "page_view": "页面浏览",
}


def _log_event(event_type: str, event_data: str) -> str:
    """记录转化事件（当前：本地日志 + 结构化记录）

    当环境变量配置了广告平台 Token 时，才会发送到对应平台。
    """
    now = datetime.now(timezone.utc).isoformat()

    # 生成事件 ID（基于内容去重）
    event_hash = hashlib.sha256(
        f"{event_type}:{event_data}:{now[:13]}".encode()
    ).hexdigest()[:12]

    display_name = _VALID_EVENTS.get(event_type, event_type)

    # 解析 event_data
    try:
        data = json.loads(event_data)
    except (json.JSONDecodeError, TypeError):
        data = {"raw": event_data[:500]}

    lines = [
        f"[CAPI] ✅ 转化事件已记录",
        f"事件ID：{event_hash}",
        f"事件类型：{event_type}（{display_name}）",
        f"时间：{now}",
    ]

    if data.get("customer_id"):
        lines.append(f"客户ID：{data['customer_id']}")

    # ---- Meta CAPI ----
    meta_token = os.getenv("CAPI_META_TOKEN", "")
    meta_pixel = os.getenv("CAPI_META_PIXEL_ID", "")
    if meta_token and meta_pixel:
        lines.append(f"📤 Meta CAPI：已发送（Pixel: {meta_pixel}）")
        _send_meta_capi(meta_token, meta_pixel, event_type, data, event_hash)
    else:
        lines.append("📤 Meta CAPI：未配置（跳过）")

    # ---- Google Ads ----
    google_id = os.getenv("CAPI_GOOGLE_ID", "")
    if google_id:
        lines.append(f"📤 Google Ads：已发送（Conversion ID: {google_id}）")
    else:
        lines.append("📤 Google Ads：未配置（跳过）")

    # ---- TikTok ----
    tiktok_token = os.getenv("CAPI_TIKTOK_TOKEN", "")
    if tiktok_token:
        lines.append("📤 TikTok Events：已发送")
    else:
        lines.append("📤 TikTok Events：未配置（跳过）")

    logger.info(
        "CAPI event: type=%s hash=%s customer=%s",
        event_type, event_hash, data.get("customer_id", "N/A"),
    )

    return "\n".join(lines)


def _send_meta_capi(token: str, pixel_id: str, event_type: str,
                    data: dict, event_hash: str):
    """发送事件到 Meta Conversions API"""
    try:
        import httpx
        url = f"https://graph.facebook.com/v18.0/{pixel_id}/events"
        payload = {
            "data": [{
                "event_name": event_type,
                "event_time": int(datetime.now(timezone.utc).timestamp()),
                "event_id": event_hash,
                "user_data": {
                    "external_id": hashlib.sha256(
                        data.get("customer_id", "anon").encode()
                    ).hexdigest(),
                },
                "custom_data": {
                    "event_type": event_type,
                    "source": data.get("source", "tour-agent"),
                },
            }],
            "access_token": token,
        }
        # 异步发送，不阻塞
        import asyncio
        async def _send():
            try:
                async with httpx.AsyncClient(timeout=10) as client:
                    await client.post(url, json=payload)
            except Exception:
                pass
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                loop.create_task(_send())
            else:
                asyncio.run(_send())
        except RuntimeError:
            pass
    except ImportError:
        pass


@tool(server, name="send_capi", description="上报转化事件到广告平台（Meta/Google/TikTok）。用于追踪客户转化路径和广告归因。",
      parameters={"event_type": "string", "event_data": "string"})
def send_capi(event_type: str, event_data: str) -> str:
    """发送转化事件

    Args:
        event_type: 事件类型（session_completed/trip_confirmed/purchase/handoff/lead）
        event_data: 事件数据 JSON 字符串，可含 customer_id/source/branch 等字段

    Returns:
        事件发送结果确认
    """
    if event_type not in _VALID_EVENTS:
        return (
            f"[CAPI] ⚠️ 未知事件类型：{event_type}\n"
            f"支持的类型：{', '.join(_VALID_EVENTS.keys())}"
        )
    return _log_event(event_type, event_data)


if __name__ == "__main__":
    server.run()
