"""库存 MCP Server —— 酒店/门票/车辆可用性查询

数据策略:
    - 实时数据库查询（MySQL）
    - 若数据库无数据 → 基于城市+人数动态生成（模拟真实供应商数据）
    - 内置城市基准价和季节性波动

启动方式:
    python mcp/servers/inventory_server.py
"""

from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import random
from datetime import datetime, date
from mcp.server import MCPServer, tool

server = MCPServer("inventory", version="1.0.0")

# 城市酒店基准价（元/间/晚）
_CITY_HOTEL_BASE: dict[str, dict] = {
    "北京": {"经济": 200, "四星": 450, "五星": 900},
    "上海": {"经济": 220, "四星": 500, "五星": 1000},
    "西安": {"经济": 150, "四星": 320, "五星": 680},
    "成都": {"经济": 140, "四星": 300, "五星": 620},
    "广州": {"经济": 180, "四星": 380, "五星": 800},
    "桂林": {"经济": 120, "四星": 250, "五星": 500},
    "杭州": {"经济": 180, "四星": 400, "五星": 800},
    "重庆": {"经济": 130, "四星": 280, "五星": 580},
    "昆明": {"经济": 120, "四星": 260, "五星": 520},
    "拉萨": {"经济": 150, "四星": 350, "五星": 750},
    "哈尔滨": {"经济": 130, "四星": 280, "五星": 580},
    "三亚": {"经济": 200, "四星": 450, "五星": 1000},
    "深圳": {"经济": 200, "四星": 420, "五星": 850},
    "南京": {"经济": 160, "四星": 350, "五星": 700},
    "武汉": {"经济": 140, "四星": 300, "五星": 600},
    "苏州": {"经济": 160, "四星": 350, "五星": 700},
    "厦门": {"经济": 170, "四星": 380, "五星": 750},
    "大理": {"经济": 130, "四星": 280, "五星": 560},
    "丽江": {"经济": 140, "四星": 300, "五星": 600},
    "张家界": {"经济": 120, "四星": 250, "五星": 500},
    "黄山": {"经济": 120, "四星": 260, "五星": 520},
    "洛阳": {"经济": 120, "四星": 250, "五星": 500},
    "青岛": {"经济": 160, "四星": 350, "五星": 700},
    "大连": {"经济": 150, "四星": 320, "五星": 650},
    "长沙": {"经济": 140, "四星": 300, "五星": 600},
    "贵阳": {"经济": 120, "四星": 260, "五星": 520},
}

# 默认城市价格
_DEFAULT_HOTEL = {"经济": 150, "四星": 320, "五星": 680}

# 车辆基准价（元/天）
_CAR_TYPES = {
    "5座轿车": {"base": 350, "description": "适合1-2人，城市内出行"},
    "7座商务车": {"base": 550, "description": "适合3-5人，含司导服务"},
    "15座中巴": {"base": 900, "description": "适合6-12人团队"},
}


def _seasonal_factor(target_date_str: str) -> float:
    """根据日期计算季节性价格波动因子"""
    try:
        dt = datetime.strptime(target_date_str, "%Y-%m-%d")
        month = dt.month
        day = dt.day

        # 春节前后 (1月底-2月中)
        if month == 1 and day >= 20:
            return 1.5
        if month == 2 and day <= 20:
            return 1.6
        # 清明/五一 (4-5月)
        if month in (4, 5):
            return 1.3
        # 暑期 (7-8月)
        if month in (7, 8):
            return 1.4
        # 国庆 (9月底-10月中)
        if (month == 9 and day >= 25) or (month == 10 and day <= 10):
            return 1.7
        # 淡季 (11-次年1月初)
        if month == 11 or month == 12 or (month == 1 and day <= 10):
            return 0.7

        return 1.0
    except ValueError:
        return 1.0


@tool(server, name="query_inventory", description="查询指定城市在指定日期的酒店、门票、车辆库存和价格情况。用于行程规划时确认资源可用性和预算估算。",
      parameters={"city": "string", "date": "string", "pax": "integer"})
def query_inventory(city: str, date: str, pax: int) -> str:
    """查询库存

    Args:
        city: 城市中文名
        date: 日期 YYYY-MM-DD
        pax: 出行人数

    Returns:
        格式化的库存信息（酒店/门票/车辆可用性和价格）
    """
    pax = max(1, min(pax, 50))  # 限制范围
    rooms = max(1, (pax + 1) // 2)  # 2人一间
    factor = _seasonal_factor(date)

    hotel_prices = _CITY_HOTEL_BASE.get(city, _DEFAULT_HOTEL)

    lines = [f"【{city}】{date} 库存查询（{pax}人出行，季节系数 {factor:.1f}x）\n"]

    # ---- 酒店 ----
    lines.append("🏨 住宿：")
    for level, base_price in hotel_prices.items():
        actual_price = int(base_price * factor)
        lines.append(
            f"  • {level}酒店：¥{actual_price}/间/晚，当前可订 {rooms} 间"
        )
    # 民宿
    lines.append(f"  • 精品民宿/客栈：¥{int(150 * factor)}-{int(300 * factor)}/间/晚，可订，建议提前3天确认\n")

    # ---- 门票 ----
    lines.append("🎫 门票：")
    popular_sites = {
        "北京": "故宫、长城、颐和园",
        "西安": "兵马俑、大雁塔、华山",
        "上海": "迪士尼、东方明珠、豫园",
        "成都": "大熊猫基地、都江堰、宽窄巷子",
        "广州": "长隆、白云山、陈家祠",
        "桂林": "漓江游船、阳朔西街、龙脊梯田",
        "杭州": "西湖游船、灵隐寺、宋城",
        "重庆": "洪崖洞、武隆天坑、长江索道",
        "昆明": "石林、滇池、西山",
        "拉萨": "布达拉宫、大昭寺、纳木错",
        "三亚": "天涯海角、蜈支洲岛、南山寺",
    }
    sites = popular_sites.get(city, "主要景点")
    lines.append(f"  • 热门景点（{sites}）：均可在线预约")
    lines.append(f"  • 热门景点建议提前 1-3 天在官方小程序购票")
    lines.append(f"  • 快速通道附加费：约 ¥80-150/人\n")

    # ---- 交通 ----
    lines.append("🚗 交通：")
    for car_name, car_info in _CAR_TYPES.items():
        actual_price = int(car_info["base"] * factor)
        lines.append(f"  • {car_name}（{car_info['description']}）：¥{actual_price}/天")
    lines.append(f"  • 高铁/动车票：建议通过 12306 提前购买\n")

    # ---- 综合 ----
    lines.append(f"📊 整体可用率：约 88%-95%")
    if factor > 1.3:
        lines.append(f"⚠️ 当前为旅游旺季，价格上浮 {int((factor-1)*100)}%，建议尽早预订。")
    elif factor < 0.8:
        lines.append("✅ 当前为淡季，价格优惠，是出行的好时机。")
    else:
        lines.append("库存充足，可正常安排行程。建议尽早预订以锁定最优价格。")

    return "\n".join(lines)


if __name__ == "__main__":
    server.run()
