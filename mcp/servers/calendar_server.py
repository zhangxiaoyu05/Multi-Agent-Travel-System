"""日历 MCP Server —— 中国节假日 + 星期 + 人流量预估

数据源:
    - chinese-calendar: 中国法定节假日/调休（实时更新）
    - datetime: 真实星期计算

启动方式:
    python mcp/servers/calendar_server.py
"""

from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from datetime import datetime, date
from mcp.server import MCPServer, tool

server = MCPServer("calendar", version="1.0.0")

# 星期中文名
_WEEKDAY_CN = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]

# 2026-2027 额外节假日（chinese-calendar 可能未及时覆盖的）
# 旅行旺季标注
_PEAK_SEASONS = {
    # 2026
    "2026-02-14": "情人节（旅行小高峰）",
    "2026-04-01": "清明祭扫高峰",
    "2026-07-01": "暑期旅游旺季开始",
    "2026-08-01": "暑期旅游旺季",
    "2026-09-01": "暑期结束/开学季",
    "2026-12-24": "圣诞+元旦旅游旺季",
    # 2027
    "2027-02-13": "情人节（旅行小高峰）",
    "2027-04-01": "清明祭扫高峰",
    "2027-07-01": "暑期旅游旺季开始",
    "2027-12-24": "圣诞+元旦旅游旺季",
}


def _get_calendar_info(date_str: str) -> dict:
    """获取指定日期的完整日历信息"""
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
    except ValueError:
        return {"error": f"日期格式错误：{date_str}，请使用 YYYY-MM-DD 格式。"}

    weekday = _WEEKDAY_CN[dt.weekday()]
    is_weekend = dt.weekday() >= 5
    today = date.today()
    target = dt.date()

    # ---- 节假日检测 ----
    holiday_name = ""
    is_holiday = False
    is_workday_override = False  # 调休上班日

    try:
        from chinese_calendar import is_holiday as cn_is_holiday
        from chinese_calendar import is_workday as cn_is_workday
        from chinese_calendar import get_holiday_detail

        is_holiday = cn_is_holiday(target)
        if is_holiday:
            detail = get_holiday_detail(target)
            if detail:
                holiday_name = str(detail) if detail else "法定节假日"

        # 检查是否为调休上班日（周末但是工作日）
        if is_weekend and cn_is_workday(target):
            is_workday_override = True
    except ImportError:
        pass

    # ---- 旅行旺季检测 ----
    peak_note = _PEAK_SEASONS.get(date_str, "")

    # ---- 人流量预估 ----
    if is_holiday:
        crowd = "极高（节假日高峰）"
        suggestion = "建议清晨 7:00 前或傍晚 17:00 后避开高峰，提前预约门票"
    elif is_workday_override:
        crowd = "中等（调休上班日）"
        suggestion = "全天均可，比正常周末人少"
    elif is_weekend:
        crowd = "中高（周末）"
        suggestion = "建议上午 9:00 前到达景区，下午人流较多"
    else:
        crowd = "中等偏低（工作日）"
        suggestion = "全天均可，游览体验较好"

    # ---- 提前天数提示 ----
    days_ahead = (target - today).days if target >= today else -1

    return {
        "date": date_str,
        "weekday": weekday,
        "is_weekend": is_weekend,
        "is_holiday": is_holiday,
        "holiday_name": holiday_name,
        "is_workday_override": is_workday_override,
        "peak_note": peak_note,
        "crowd": crowd,
        "suggestion": suggestion,
        "days_ahead": days_ahead,
    }


@tool(server, name="query_calendar", description="查询指定日期的星期、节假日状态、预计人流量和游览建议。用于行程规划时判断是否需要避开高峰。",
      parameters={"date": "string"})
def query_calendar(date: str) -> str:
    """查询日期信息

    Args:
        date: 日期，格式 YYYY-MM-DD

    Returns:
        格式化的日期信息文本（含星期、节假日、人流量、游览建议）
    """
    info = _get_calendar_info(date)
    if "error" in info:
        return info["error"]

    lines = [f"{info['date']} 是 {info['weekday']}"]

    if info["holiday_name"]:
        lines.append(f"🏖️ 节假日：{info['holiday_name']}")
    if info["is_workday_override"]:
        lines.append("📋 调休上班日（按工作日计算）")
    if info["peak_note"]:
        lines.append(f"📌 {info['peak_note']}")

    lines.append(f"👥 预计人流量：{info['crowd']}")
    lines.append(f"💡 游览建议：{info['suggestion']}")

    if info["days_ahead"] >= 0:
        lines.append(f"📅 距今 {info['days_ahead']} 天")

    return "\n".join(lines)


if __name__ == "__main__":
    server.run()
