"""真实日历 API——预留接口

对接方式（任选其一）：
1. pip install chinese-calendar → 自动判断中国节假日/调休
2. 对接政府公开 API（如国务院节假日安排公告）
3. 对接第三方服务（如 https://date.nager.at 国际节假日）

当前为骨架实现，返回基础星期信息。
"""

from datetime import datetime


def query_calendar_real(date_str: str) -> str:
    """真实日历查询——当前仅计算星期，待对接节假日 API。

    TODO: 对接 chinese-calendar 或政府 API 获取实际节假日状态。
    """
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
    except ValueError:
        return f"日期格式错误：{date_str}，请使用 YYYY-MM-DD 格式。"

    weekday_cn = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
    weekday = weekday_cn[dt.weekday()]
    is_weekend = dt.weekday() >= 5

    crowd = "中高（周末）" if is_weekend else "中等偏低（工作日）"
    suggestion = (
        "建议上午 9:00 前到达景区" if is_weekend
        else "全天均可，游览体验较好"
    )

    return (
        f"{date_str} 是 {weekday}\n"
        f"预计人流量：{crowd}\n"
        f"游览建议：{suggestion}\n"
        f"（注：节假日数据暂未接入，仅基于星期判断）"
    )
