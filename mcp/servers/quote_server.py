"""报价 MCP Server —— 实时行程报价引擎

定价策略:
    - 城市基准价 + 天数 + 人数 + 季节系数
    - 主题溢价（美食+15%、探险+10%）
    - 节奏因子（轻松+30%、紧凑-20%）
    - 汇率：固定 1 USD ≈ 7.2 CNY（可配置）

启动方式:
    python mcp/servers/quote_server.py
"""

from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from datetime import datetime
from mcp.server import MCPServer, tool

server = MCPServer("quote", version="1.0.0")

# 城市日均基准价（元/人/天，含住宿+餐饮+门票+交通）
_CITY_DAILY_BASE: dict[str, int] = {
    "北京": 800, "上海": 900, "西安": 650, "成都": 600,
    "广州": 750, "桂林": 550, "杭州": 750, "重庆": 580,
    "昆明": 500, "拉萨": 700, "哈尔滨": 550, "三亚": 1000,
    "深圳": 850, "南京": 700, "武汉": 600, "苏州": 700,
    "厦门": 720, "大理": 520, "丽江": 550, "张家界": 500,
    "黄山": 520, "洛阳": 500, "青岛": 680, "大连": 650,
    "长沙": 550, "贵阳": 500, "乌鲁木齐": 680, "西宁": 550,
    "兰州": 520, "银川": 520, "南宁": 550,
}

_DEFAULT_DAILY = 650  # 未知城市默认基准价

# 主题溢价因子
_THEME_FACTORS = {
    "美食": 1.15, "探险": 1.10, "豪华": 1.50,
    "历史文化": 1.05, "自然风光": 1.00, "经典必游": 1.00,
    "综合": 1.00, "购物": 1.10, "摄影": 1.05,
}

# 节奏因子
_PACE_FACTORS = {
    "轻松": 1.30,  # 更好的酒店，更长的休息时间
    "适中": 1.00,
    "紧凑": 0.80,  # 经济型安排
}

# 汇率
_USD_TO_CNY = 7.2


def _seasonal_factor(arrival_date: str) -> float:
    """根据抵达日期计算季节系数"""
    try:
        dt = datetime.strptime(arrival_date, "%Y-%m-%d")
        month = dt.month
        day = dt.day

        if month == 1 and day >= 20:
            return 1.5
        if month == 2 and day <= 20:
            return 1.6
        if month in (4, 5):
            return 1.3
        if month in (7, 8):
            return 1.4
        if (month == 9 and day >= 25) or (month == 10 and day <= 10):
            return 1.7
        if month == 11 or month == 12 or (month == 1 and day <= 10):
            return 0.7
        return 1.0
    except ValueError:
        return 1.0


@tool(server, name="quote_price", description="根据目的地、天数、人数、主题偏好和节奏生成详细的行程报价单。用于销售场景下为客户提供价格参考。",
      parameters={
          "destination": "string",
          "days": "integer",
          "pax": "integer",
          "theme": "string",
          "pace": "string",
          "currency": "string",
      })
def quote_price(
    destination: str,
    days: int,
    pax: int,
    theme: str = "经典必游",
    pace: str = "适中",
    currency: str = "¥",
) -> str:
    """生成行程报价

    Args:
        destination: 目的地城市
        days: 行程天数
        pax: 出行人数
        theme: 偏好主题（经典必游/美食/自然风光/历史文化/探险/豪华/购物/摄影）
        pace: 节奏偏好（轻松/适中/紧凑）
        currency: 货币符号（¥/$）

    Returns:
        格式化的报价单（含分项明细和总计）
    """
    days = max(1, min(days, 30))
    pax = max(1, min(pax, 50))
    daily_base = _CITY_DAILY_BASE.get(destination, _DEFAULT_DAILY)
    theme_factor = _THEME_FACTORS.get(theme, 1.0)
    pace_factor = _PACE_FACTORS.get(pace, 1.0)

    total_per_person_cny = daily_base * days * theme_factor * pace_factor
    total_cny = total_per_person_cny * pax

    # 分项预算
    hotel_share = 0.35
    transport_share = 0.22
    tickets_share = 0.18
    food_share = 0.18
    guide_share = 0.07

    hotel_cny = total_cny * hotel_share
    transport_cny = total_cny * transport_share
    tickets_cny = total_cny * tickets_share
    food_cny = total_cny * food_share
    guide_cny = total_cny * guide_share

    # 货币转换
    if currency == "$" or currency == "USD":
        symbol = "$"
        total_display = total_cny / _USD_TO_CNY
        per_person_display = total_per_person_cny / _USD_TO_CNY
        suffix = f"（按 1 USD ≈ {_USD_TO_CNY} CNY 换算）"
    else:
        symbol = "¥"
        total_display = total_cny
        per_person_display = total_per_person_cny
        suffix = ""

    lines = [
        f"📊 【{destination}】{days}日行程报价单",
        f"",
        f"## 基本信息",
        f"- 目的地：{destination}",
        f"- 行程天数：{days} 天",
        f"- 出行人数：{pax} 人",
        f"- 偏好主题：{theme}（溢价 {theme_factor:.0%}）",
        f"- 节奏偏好：{pace}（因子 {pace_factor:.0%}）",
        f"",
        f"## 费用预估",
        f"| 类别 | 占比 | 金额 |",
        f"|------|------|------|",
        f"| 🏨 住宿 | {hotel_share:.0%} | {symbol}{hotel_cny:,.0f} |",
        f"| 🚗 交通 | {transport_share:.0%} | {symbol}{transport_cny:,.0f} |",
        f"| 🎫 门票/活动 | {tickets_share:.0%} | {symbol}{tickets_cny:,.0f} |",
        f"| 🍜 餐饮 | {food_share:.0%} | {symbol}{food_cny:,.0f} |",
        f"| 🧑‍💼 司导服务 | {guide_share:.0%} | {symbol}{guide_cny:,.0f} |",
        f"",
        f"## 汇总",
        f"- 人均费用：**{symbol}{per_person_display:,.0f}** /人",
        f"- 总计（{pax}人）：**{symbol}{total_display:,.0f}**",
    ]

    if suffix:
        lines.append(f"  {suffix}")

    lines.append("")
    lines.append("> 📝 此为实时估算价格，实际价格以签约时为准。旺季/节假日价格可能上浮。")

    return "\n".join(lines)


if __name__ == "__main__":
    server.run()
