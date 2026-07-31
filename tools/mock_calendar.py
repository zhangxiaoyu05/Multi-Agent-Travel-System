"""日历/节假日查询工具

支持双模式：
- TOOL_MODE=mock（默认）：基于 datetime 计算真实星期 + 内置节假日列表
- TOOL_MODE=real：预留对接真实节假日 API（如 chinese-calendar）

使用方式：
    from tools.mock_calendar import query_calendar
    result = query_calendar.invoke({"date": "2026-08-15"})
"""

import os
import logging
from langchain.tools import tool
from datetime import datetime

logger = logging.getLogger(__name__)


def _get_tool_mode() -> str:
    return os.getenv("TOOL_MODE", "mock").lower()


@tool
def query_calendar(date: str) -> str:
    """查询指定日期是否为节假日、工作日，以及预计人流量。

    Args:
        date: 日期，格式 YYYY-MM-DD

    Returns:
        日期信息文本，包含星期、节假日状态、预计人流量和建议游览时间。
    """
    # ---- Real mode ----
    if _get_tool_mode() == "real":
        try:
            from tools.calendar_real import query_calendar_real
            return query_calendar_real(date)
        except Exception as e:
            logger.warning(f"Real calendar API failed, falling back to mock: {e}")

    # ---- Mock mode (default) ----
    try:
        dt = datetime.strptime(date, "%Y-%m-%d")
    except ValueError:
        return f"日期格式错误：{date}，请使用 YYYY-MM-DD 格式。"

    # 中国 2026-2027 法定节假日
    holidays = {
        # 2026
        "2026-01-01": "元旦假期",
        "2026-02-17": "春节假期（除夕）",
        "2026-02-18": "春节假期（初一）",
        "2026-02-19": "春节假期（初二）",
        "2026-04-05": "清明节假期",
        "2026-05-01": "劳动节假期",
        "2026-06-19": "端午节假期",
        "2026-09-25": "中秋节假期",
        "2026-10-01": "国庆节假期",
        # 2027
        "2027-01-01": "元旦假期",
        "2027-02-05": "春节假期（除夕）",
        "2027-02-06": "春节假期（初一）",
        "2027-02-07": "春节假期（初二）",
        "2027-04-05": "清明节假期",
        "2027-05-01": "劳动节假期",
        "2027-06-07": "端午节假期",
        "2027-09-14": "中秋节假期",
        "2027-10-01": "国庆节假期",
    }

    date_str = dt.strftime("%Y-%m-%d")
    weekday_cn = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
    weekday = weekday_cn[dt.weekday()]

    is_weekend = dt.weekday() >= 5
    is_holiday = date_str in holidays
    holiday_name = holidays.get(date_str, "")

    if is_holiday:
        crowd = "极高（节假日高峰）"
        suggestion = "建议清晨 7:00 前或傍晚 17:00 后避开高峰，提前预约门票"
    elif is_weekend:
        crowd = "中高（周末）"
        suggestion = "建议上午 9:00 前到达景区，下午人流较多"
    else:
        crowd = "中等偏低（工作日）"
        suggestion = "全天均可，游览体验较好"

    holiday_note = ""
    if holiday_name:
        holiday_note = f"\n标记：{holiday_name}"

    return (
        f"{date} 是 {weekday}{holiday_note}\n"
        f"预计人流量：{crowd}\n"
        f"游览建议：{suggestion}"
    )
