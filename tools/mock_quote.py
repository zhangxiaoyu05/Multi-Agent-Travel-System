"""Mock 报价生成工具

根据行程需求生成结构化的报价单。
MVP 阶段使用固定价格模板，Phase 8 对接真实供应商价格 API。
"""

from langchain.tools import tool


# 城市基准价格（人均/天，人民币）
_CITY_BASE_PRICE = {
    "北京": 800, "上海": 900, "西安": 650, "成都": 600,
    "广州": 750, "桂林": 550, "杭州": 700, "重庆": 550,
    "昆明": 600, "拉萨": 850, "哈尔滨": 600, "三亚": 1000,
    "深圳": 850, "南京": 650, "武汉": 550, "苏州": 700,
    "厦门": 750, "大理": 600, "丽江": 650, "张家界": 600,
    "黄山": 600, "洛阳": 500, "开封": 500, "青岛": 700,
    "大连": 650, "长沙": 550, "贵阳": 550, "乌鲁木齐": 700,
    "呼和浩特": 550, "西宁": 600, "兰州": 500, "银川": 500,
    "南宁": 500,
}

# 默认基准价（未匹配城市使用）
_DEFAULT_BASE = 650


@tool
def quote_price(
    destination: str,
    days: int,
    pax: int,
    budget: str = "",
    theme: str = "",
    pace: str = "",
) -> str:
    """生成行程报价单。

    根据目的地、天数、人数和预算生成详细的分项报价。
    包含住宿、交通、门票、餐饮、导游服务等费用明细。

    Args:
        destination: 目的地城市（中文）
        days: 行程天数
        pax: 出行人数
        budget: 客户预算（如 "¥5000/人" 或 "$2000/人"），可选
        theme: 偏好主题，可选
        pace: 节奏偏好，可选

    Returns:
        结构化的报价单文本，包含分项明细和总费用。
    """
    base = _CITY_BASE_PRICE.get(destination, _DEFAULT_BASE)

    # 价格调整因子
    theme_factor = 1.0
    if theme:
        if "美食" in theme:
            theme_factor = 1.15  # 美食游餐饮占比高
        elif "自然" in theme:
            theme_factor = 0.95  # 自然风光门票较低
        elif "历史" in theme:
            theme_factor = 1.05  # 历史文化景点门票适中

    pace_factor = 1.0
    if pace:
        if pace == "轻松":
            pace_factor = 1.3   # 轻松游住宿/交通品质更高
        elif pace == "紧凑":
            pace_factor = 0.85  # 紧凑游性价比更高

    daily_base = base * theme_factor * pace_factor

    # 分项计算
    accommodation = daily_base * 0.35   # 住宿 35%
    transport = daily_base * 0.22       # 交通 22%
    tickets = daily_base * 0.18         # 门票 18%
    dining = daily_base * 0.15          # 餐饮 15%
    guide = daily_base * 0.10           # 导游 10%

    total_per_person = daily_base * days
    total_all = total_per_person * pax

    # 根据预算调整货币符号
    currency = "¥"
    if budget and "$" in budget:
        currency = "$"
        # 美元换算（约 1 USD = 7.2 CNY）
        rate = 7.2
        accommodation = round(accommodation / rate)
        transport = round(transport / rate)
        tickets = round(tickets / rate)
        dining = round(dining / rate)
        guide = round(guide / rate)
        total_per_person = round(total_per_person / rate)
        total_all = total_per_person * pax

    lines = [
        f"## {destination}{days}日游报价单",
        "",
        f"| 费用项目 | 人均/天（{currency}） | {days}天人均（{currency}） | {pax}人合计（{currency}） |",
        f"|----------|---------------------|--------------------------|--------------------------|",
        f"| 住宿     | {currency}{accommodation} | {currency}{accommodation * days} | {currency}{accommodation * days * pax} |",
        f"| 交通     | {currency}{transport} | {currency}{transport * days} | {currency}{transport * days * pax} |",
        f"| 门票/活动 | {currency}{tickets} | {currency}{tickets * days} | {currency}{tickets * days * pax} |",
        f"| 餐饮     | {currency}{dining} | {currency}{dining * days} | {currency}{dining * days * pax} |",
        f"| 导游服务 | {currency}{guide} | {currency}{guide * days} | {currency}{guide * days * pax} |",
        f"| **合计** | **{currency}{daily_base}** | **{currency}{total_per_person}** | **{currency}{total_all}** |",
        "",
        "> 💡 以上为基础套餐价格，包含：",
        "> - 精选四星/精品酒店住宿（含早）",
        "> - 全程专车接送 + 高铁/机票代订",
        "> - 主要景点门票 + 1-2 个特色体验项目",
        "> - 每日特色餐饮推荐 + 2 顿正餐",
        "> - 中文/英文持证导游全程陪同",
        "",
        "> 📌 预订须知：",
        "> - 报价有效期 48 小时",
        "> - 预订需支付 30% 定金",
        "> - 出发前 7 天可免费取消",
        "> - 实际价格以预订时确认为准，旺季可能有 10-20% 上浮",
    ]

    if budget:
        lines.append(f"\n> 您的预算：{budget}")
        lines.append("> 以上报价在预算范围内，可以放心预订！")

    return "\n".join(lines)
