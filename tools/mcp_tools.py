"""MCP-backed LangChain 工具包装器

将 MCP Server 的工具包装为 LangChain @tool 兼容格式。
Agent 导入这些工具后，调用 .invoke() / .ainvoke() 透明转发到 MCP Server。

三层降级策略：
    1. MCP Server 可用 → 调用真实 API
    2. MCP Server 不可用 → 回退到 mock 实现
    3. mock 也不可用 → 返回错误提示

用法：
    from tools.mcp_tools import get_weather, query_calendar, query_inventory
    result = get_weather.invoke({"city": "北京", "date": "2026-08-15"})
"""

from __future__ import annotations

import os
import asyncio
import logging
from langchain_core.tools import tool

logger = logging.getLogger(__name__)

# 是否强制使用 mock（测试/开发环境）
_FORCE_MOCK = os.getenv("MCP_FORCE_MOCK", "").lower() in ("1", "true", "yes")


def _get_client():
    """延迟导入 MCP client（避免循环依赖）"""
    from services.mcp_client import get_mcp_client
    return get_mcp_client()


def _is_mcp_available() -> bool:
    """检查 MCP 是否可用"""
    if _FORCE_MOCK:
        return False
    try:
        client = _get_client()
        return getattr(client, '_started', False)
    except Exception:
        return False


def _run_async(coro):
    """在同步上下文中运行异步协程"""
    try:
        loop = asyncio.get_running_loop()
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor() as executor:
            future = executor.submit(asyncio.run, coro)
            return future.result(timeout=60)
    except RuntimeError:
        return asyncio.run(coro)


def _mcp_call(tool_name: str, args: dict, mock_func=None) -> str:
    """调用 MCP 工具，失败时回退到 mock

    Args:
        tool_name: MCP 工具名
        args: 工具参数
        mock_func: mock 回退函数（接收 **args，返回 str）
    """
    if _is_mcp_available():
        try:
            client = _get_client()
            # 检查是否有活跃连接
            active = sum(1 for c in client._connections.values() if c.is_running)
            if active > 0:
                return _run_async(client.call_tool(tool_name, args))
        except Exception as e:
            logger.warning("MCP call '%s' failed, falling back to mock: %s", tool_name, e)

    # 回退到 mock
    if mock_func:
        try:
            return mock_func(**args)
        except Exception as e:
            logger.error("Mock fallback for '%s' also failed: %s", tool_name, e)
            return f"[{tool_name}] 服务暂时不可用，请稍后重试。({e})"

    return f"[{tool_name}] MCP 服务未启动，且无 mock 回退。"


# =============================================================================
# Tool 定义
# =============================================================================


@tool
def get_weather(city: str, date: str) -> str:
    """查询指定城市在指定日期的天气情况（Open-Meteo 实时数据）。

    用于行程规划时获取目的地天气，以便合理安排户外/室内活动。

    Args:
        city: 城市中文名，如 "北京"、"三亚"、"西安"
        date: 日期，格式 YYYY-MM-DD

    Returns:
        天气描述文本（含温度、降水概率、风力、出行指数）
    """
    def _mock(city, date):
        from tools.mock_weather import _MOCK_WEATHER
        weather = _MOCK_WEATHER.get(city)
        if weather:
            return f"[{city}] {date}\n{weather}"
        return f"[{city}] {date}\n晴转多云，20°C ~ 28°C，微风 2-3 级，适合出行指数：良好"
    return _mcp_call("get_weather", {"city": city, "date": date}, _mock)


@tool
def query_calendar(date: str) -> str:
    """查询指定日期的星期、节假日状态、预计人流量和游览建议。

    Args:
        date: 日期，格式 YYYY-MM-DD

    Returns:
        日期信息文本（含星期、节假日、人流量、游览建议）
    """
    def _mock(date):
        from tools.mock_calendar import query_calendar as mock_cal
        return mock_cal.invoke({"date": date})
    return _mcp_call("query_calendar", {"date": date}, _mock)


@tool
def query_inventory(city: str, date: str, pax: int) -> str:
    """查询指定城市在指定日期的酒店、门票、车辆库存和价格。

    用于行程规划时确认资源可用性和预算估算。

    Args:
        city: 城市中文名
        date: 日期，格式 YYYY-MM-DD
        pax: 出行人数

    Returns:
        库存信息文本（含酒店/门票/车辆可用性和价格）
    """
    def _mock(city, date, pax):
        from tools.mock_inventory import query_inventory as mock_inv
        return mock_inv.invoke({"city": city, "date": date, "pax": pax})
    return _mcp_call("query_inventory", {"city": city, "date": date, "pax": pax}, _mock)


@tool
def quote_price(destination: str, days: int, pax: int, theme: str = "经典必游",
                pace: str = "适中", currency: str = "¥") -> str:
    """根据目的地、天数、人数等参数生成详细的行程报价单。

    用于销售场景下为客户提供价格参考。

    Args:
        destination: 目的地城市
        days: 行程天数
        pax: 出行人数
        theme: 偏好主题（经典必游/美食/自然风光/历史文化/探险/豪华）
        pace: 节奏偏好（轻松/适中/紧凑）
        currency: 货币符号（¥/$）

    Returns:
        格式化的报价单（含分项明细和总计）
    """
    def _mock(destination, days, pax, theme, pace, currency):
        from tools.mock_quote import quote_price as mock_q
        return mock_q.invoke({"destination": destination, "days": days, "pax": pax,
                              "theme": theme, "pace": pace, "currency": currency})
    return _mcp_call("quote_price", {
        "destination": destination, "days": days, "pax": pax,
        "theme": theme, "pace": pace, "currency": currency,
    }, _mock)


@tool
def update_crm(customer_id: str, session_data: str) -> str:
    """将客户会话数据写入 CRM 系统（MySQL 持久化）。

    Args:
        customer_id: 客户唯一标识
        session_data: 会话数据 JSON 字符串

    Returns:
        写入结果确认文本
    """
    def _mock(customer_id, session_data):
        from tools.mock_crm import update_crm as mock_crm
        return mock_crm.invoke({"customer_id": customer_id, "session_data": session_data})
    return _mcp_call("update_crm", {
        "customer_id": customer_id, "session_data": session_data,
    }, _mock)


@tool
def send_capi(event_type: str, event_data: str) -> str:
    """上报转化事件到广告平台（Meta/Google/TikTok）。

    用于追踪客户转化路径和广告归因。

    Args:
        event_type: 事件类型（session_completed/trip_confirmed/purchase/handoff/lead）
        event_data: 事件数据 JSON 字符串

    Returns:
        事件发送结果确认
    """
    def _mock(event_type, event_data):
        from tools.mock_capi import send_capi as mock_capi
        return mock_capi.invoke({"event_type": event_type, "event_data": event_data})
    return _mcp_call("send_capi", {
        "event_type": event_type, "event_data": event_data,
    }, _mock)
