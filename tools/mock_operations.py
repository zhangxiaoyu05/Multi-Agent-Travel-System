"""运营 Mock 工具——产品查询 + 订单管理 + 工单系统

运营 Agent 的工具集，是"用户与产品的桥梁"。
所有工具被 MCP 层包装（MCP→Mock 降级），也可被其他 Agent 直接调用。

工具分组：
- 产品查询 ×4：search_hotels, search_flights, search_tickets, search_guides
- 订单管理 ×4：get_order, list_orders, cancel_order, modify_order
- 工单 ×2：create_ticket, check_ticket
"""

import random
import uuid
from datetime import datetime, date
from langchain_core.tools import tool

# =============================================================================
# 假数据——5 个城市的真实感产品库存
# =============================================================================

_MOCK_PRODUCTS = {
    "北京": {
        "hotels": [
            {"name": "王府井希尔顿酒店", "stars": 5, "price_per_night": "¥1,200",
             "status": "available", "address": "东城区王府井大街", "contact": "010-5811-8888"},
            {"name": "北京国贸大酒店", "stars": 5, "price_per_night": "¥1,500",
             "status": "available", "address": "朝阳区建国门外大街1号", "contact": "010-6505-2299"},
            {"name": "北京长安街W酒店", "stars": 4, "price_per_night": "¥800",
             "status": "limited", "address": "东城区建国门南大街", "contact": "010-6515-8855"},
            {"name": "南锣鼓巷胡同客栈", "stars": 3, "price_per_night": "¥380",
             "status": "available", "address": "东城区南锣鼓巷", "contact": "010-6400-1122"},
        ],
        "tickets": [
            {"name": "故宫博物院", "price": "¥60/人", "status": "available",
             "time_slots": "上午场 8:30-12:00 / 下午场 12:00-16:00", "note": "需提前1天实名预约"},
            {"name": "八达岭长城", "price": "¥40/人", "status": "available",
             "time_slots": "全天 7:00-17:00", "note": "含缆车另加¥100/人"},
            {"name": "颐和园", "price": "¥30/人", "status": "available",
             "time_slots": "全天 7:00-17:00", "note": ""},
            {"name": "天坛公园", "price": "¥15/人", "status": "available",
             "time_slots": "全天 6:00-17:30", "note": ""},
        ],
        "guides": [
            {"name": "张磊", "languages": "中文/英文", "price_per_day": "¥800",
             "specialty": "历史文化/故宫讲解", "status": "available"},
            {"name": "李芳", "languages": "中文/日文", "price_per_day": "¥1,000",
             "specialty": "长城/颐和园/美食", "status": "available"},
            {"name": "王浩", "languages": "中文/韩文", "price_per_day": "¥900",
             "specialty": "胡同文化/故宫/天坛", "status": "limited"},
        ],
    },
    "上海": {
        "hotels": [
            {"name": "上海外滩华尔道夫酒店", "stars": 5, "price_per_night": "¥1,800",
             "status": "available", "address": "黄浦区中山东一路2号", "contact": "021-6322-9988"},
            {"name": "上海静安香格里拉", "stars": 5, "price_per_night": "¥1,350",
             "status": "available", "address": "静安区延安中路1218号", "contact": "021-2203-8888"},
            {"name": "上海新天地朗廷酒店", "stars": 5, "price_per_night": "¥1,400",
             "status": "limited", "address": "黄浦区马当路99号", "contact": "021-2330-2288"},
        ],
        "tickets": [
            {"name": "上海迪士尼乐园", "price": "¥475/人", "status": "available",
             "time_slots": "全天 9:00-20:30", "note": "需提前预约入园日期"},
            {"name": "东方明珠塔", "price": "¥199/人", "status": "available",
             "time_slots": "全天 8:30-21:00", "note": ""},
            {"name": "上海豫园", "price": "¥40/人", "status": "available",
             "time_slots": "全天 8:45-16:30", "note": ""},
        ],
        "guides": [
            {"name": "陈明", "languages": "中文/英文/上海话", "price_per_day": "¥900",
             "specialty": "外滩/法租界/美食探店", "status": "available"},
            {"name": "刘洋", "languages": "中文/法文", "price_per_day": "¥1,100",
             "specialty": "老上海/博物馆/艺术展", "status": "available"},
        ],
    },
    "西安": {
        "hotels": [
            {"name": "西安索菲特传奇酒店", "stars": 5, "price_per_night": "¥980",
             "status": "available", "address": "新城区东新街319号", "contact": "029-8792-9999"},
            {"name": "西安威斯汀大酒店", "stars": 5, "price_per_night": "¥850",
             "status": "available", "address": "雁塔区慈恩路66号", "contact": "029-6568-6666"},
            {"name": "钟楼饭店", "stars": 4, "price_per_night": "¥420",
             "status": "available", "address": "碑林区东大街", "contact": "029-8721-2222"},
        ],
        "tickets": [
            {"name": "秦始皇兵马俑博物馆", "price": "¥120/人", "status": "available",
             "time_slots": "全天 8:30-17:00", "note": "旺季需提前3天预约"},
            {"name": "西安城墙", "price": "¥54/人", "status": "available",
             "time_slots": "全天 8:00-22:00", "note": "可租自行车骑行"},
            {"name": "大雁塔·大慈恩寺", "price": "¥50/人", "status": "available",
             "time_slots": "全天 8:00-17:30", "note": ""},
        ],
        "guides": [
            {"name": "赵敏", "languages": "中文/英文", "price_per_day": "¥750",
             "specialty": "兵马俑/汉唐历史/考古", "status": "available"},
            {"name": "马超", "languages": "中文/日文", "price_per_day": "¥850",
             "specialty": "丝绸之路/长安文化", "status": "available"},
        ],
    },
    "三亚": {
        "hotels": [
            {"name": "三亚亚龙湾瑞吉度假酒店", "stars": 5, "price_per_night": "¥2,200",
             "status": "available", "address": "亚龙湾国家旅游度假区", "contact": "0898-8855-8888"},
            {"name": "三亚海棠湾艾迪逊酒店", "stars": 5, "price_per_night": "¥1,800",
             "status": "available", "address": "海棠湾海棠北路100号", "contact": "0898-8865-9999"},
            {"name": "三亚湾海居铂尔曼度假酒店", "stars": 5, "price_per_night": "¥1,100",
             "status": "available", "address": "三亚湾路158号", "contact": "0898-8898-6666"},
        ],
        "tickets": [
            {"name": "蜈支洲岛", "price": "¥144/人", "status": "available",
             "time_slots": "全天 8:00-17:30", "note": "含往返船票，水上项目另付"},
            {"name": "南山文化旅游区", "price": "¥129/人", "status": "available",
             "time_slots": "全天 8:00-17:00", "note": "含南山寺+海上观音"},
            {"name": "亚龙湾热带天堂森林公园", "price": "¥170/人", "status": "available",
             "time_slots": "全天 8:00-17:30", "note": "含过江龙索桥"},
        ],
        "guides": [
            {"name": "林海", "languages": "中文/英文", "price_per_day": "¥700",
             "specialty": "海岛/水上运动/热带雨林", "status": "available"},
            {"name": "周诗雨", "languages": "中文/俄文", "price_per_day": "¥800",
             "specialty": "三亚/海岛/海鲜美食", "status": "available"},
        ],
    },
    "成都": {
        "hotels": [
            {"name": "成都博舍酒店", "stars": 5, "price_per_night": "¥1,600",
             "status": "available", "address": "锦江区笔帖式街81号", "contact": "028-6297-8888"},
            {"name": "成都瑞吉酒店", "stars": 5, "price_per_night": "¥1,200",
             "status": "available", "address": "锦江区太升南路88号", "contact": "028-8500-9999"},
            {"name": "成都宽窄巷子亚朵酒店", "stars": 4, "price_per_night": "¥450",
             "status": "available", "address": "青羊区长顺上街", "contact": "028-8666-1122"},
        ],
        "tickets": [
            {"name": "成都大熊猫繁育研究基地", "price": "¥55/人", "status": "available",
             "time_slots": "全天 7:30-17:00", "note": "建议早上7:30前到达看熊猫活动"},
            {"name": "都江堰景区", "price": "¥80/人", "status": "available",
             "time_slots": "全天 8:00-17:30", "note": "距成都市区约1.5小时车程"},
            {"name": "武侯祠博物馆", "price": "¥50/人", "status": "available",
             "time_slots": "全天 8:00-18:00", "note": ""},
        ],
        "guides": [
            {"name": "杨雪", "languages": "中文/英文", "price_per_day": "¥700",
             "specialty": "大熊猫/川菜美食/三国文化", "status": "available"},
            {"name": "黄鹏", "languages": "中文/泰文", "price_per_day": "¥800",
             "specialty": "都江堰/青城山/川西环线", "status": "available"},
        ],
    },
}

# 通用航班模拟数据（按航线）
_MOCK_FLIGHTS = [
    {"flight": "CA1234", "airline": "中国国际航空", "departure": "08:30", "arrival": "10:45",
     "duration": "2h15m", "price_per_pax": "¥1,280", "class": "经济舱", "status": "available"},
    {"flight": "MU5678", "airline": "中国东方航空", "departure": "10:15", "arrival": "12:30",
     "duration": "2h15m", "price_per_pax": "¥1,450", "class": "经济舱", "status": "available"},
    {"flight": "CZ9012", "airline": "中国南方航空", "departure": "14:00", "arrival": "16:15",
     "duration": "2h15m", "price_per_pax": "¥1,080", "class": "经济舱", "status": "limited"},
    {"flight": "HU3456", "airline": "海南航空", "departure": "17:30", "arrival": "19:45",
     "duration": "2h15m", "price_per_pax": "¥950", "class": "经济舱", "status": "available"},
    {"flight": "3U7890", "airline": "四川航空", "departure": "07:00", "arrival": "09:15",
     "duration": "2h15m", "price_per_pax": "¥880", "class": "经济舱", "status": "available"},
]


# =============================================================================
# 全局内存存储（订单 + 工单）
# =============================================================================

_ORDERS: dict[str, dict] = {}     # order_id → order_data（与 mock_sales.py _ORDERS 互相独立）
_TICKETS: dict[str, dict] = {}    # ticket_id → ticket_data


def _make_order_id() -> str:
    ts = datetime.now().strftime("%Y%m%d%H%M%S")
    suffix = uuid.uuid4().hex[:6].upper()
    return f"ORD-{ts}-{suffix}"


def _make_ticket_id() -> str:
    ts = datetime.now().strftime("%Y%m%d%H%M%S")
    suffix = uuid.uuid4().hex[:6].upper()
    return f"TK-{ts}-{suffix}"


# =============================================================================
# 产品查询工具（4 个）
# =============================================================================


@tool
def search_hotels(city: str, check_in: str = "", check_out: str = "",
                  pax: int = 1) -> str:
    """搜索目的地酒店，返回可用酒店列表及价格和库存状态。

    用于帮助用户挑选目的地住宿。如果用户有行程方案，结合行程中的天数
    和目的地来推荐合适的酒店。

    Args:
        city: 城市名称（如"北京"、"上海"、"三亚"等）
        check_in: 入住日期 YYYY-MM-DD（可选）
        check_out: 离店日期 YYYY-MM-DD（可选）
        pax: 人数（用于推荐合适房型）

    Returns:
        酒店列表文本，包含名称、星级、价格、库存状态和联系方式
    """
    city_data = _MOCK_PRODUCTS.get(city)
    if not city_data:
        known = ", ".join(_MOCK_PRODUCTS.keys())
        return f"抱歉，目前 {city} 暂无合作酒店。已覆盖城市：{known}。更多城市即将上线！"

    hotels = city_data["hotels"]
    lines = [f"## {city} 酒店（{len(hotels)} 家）\n"]
    for i, h in enumerate(hotels, 1):
        status_icon = {"available": "✅", "limited": "⚠️", "sold_out": "❌"}.get(h["status"], "❓")
        status_text = {"available": "可预订", "limited": "仅剩少量", "sold_out": "已售罄"}.get(h["status"], "未知")
        lines.append(
            f"### {i}. {h['name']}  {status_icon} {status_text}\n"
            f"- ⭐ 星级：{'★' * h['stars']}\n"
            f"- 💰 价格：{h['price_per_night']}/晚\n"
            f"- 📍 地址：{h['address']}\n"
            f"- 📞 联系方式：{h['contact']}\n"
        )

    if check_in and check_out:
        lines.append(f"\n> 入住日期：{check_in} → 离店日期：{check_out}")

    return "\n".join(lines)


@tool
def search_flights(origin: str = "", destination: str = "", date: str = "",
                   pax: int = 1) -> str:
    """搜索国内航班，返回可用航班列表及价格和余票状态。

    用于帮助用户挑选国内机票。支持按出发地、目的地、日期筛选。

    Args:
        origin: 出发城市（如"北京"）
        destination: 到达城市（如"西安"）
        date: 出发日期 YYYY-MM-DD（可选）
        pax: 人数

    Returns:
        航班列表文本，包含航班号、航司、时间、价格和余票状态
    """
    lines = ["## 航班搜索结果\n"]

    if origin and destination:
        lines.append(f"航线：{origin} → {destination}")
    if date:
        lines.append(f"日期：{date}")
    lines.append("")

    for i, f in enumerate(_MOCK_FLIGHTS, 1):
        status_icon = {"available": "✅", "limited": "⚠️", "sold_out": "❌"}.get(f["status"], "❓")
        status_text = {"available": f"余票充足（≥{pax}张）", "limited": "仅剩少量（≤3张）", "sold_out": "已售罄"}.get(f["status"], "未知")
        lines.append(
            f"### {i}. {f['flight']} — {f['airline']}  {status_icon}\n"
            f"- 🕐 {f['departure']} → {f['arrival']}（{f['duration']}）\n"
            f"- 💰 {f['price_per_pax']}/人（{f['class']}）\n"
            f"- 📊 状态：{status_text}\n"
        )

    lines.append("\n> 💡 提示：建议至少提前 7 天预订以获得最优价格。")
    return "\n".join(lines)


@tool
def search_tickets(city: str, type: str = "", date: str = "",
                   pax: int = 1) -> str:
    """搜索目的地门票和活动，返回可用门票列表及价格和时段。

    用于帮助用户了解和预订景点门票。按城市和类型筛选。

    Args:
        city: 城市名称
        type: 门票类型筛选（可选，如"博物馆"、"自然风光"、"主题乐园"）
        date: 游玩日期 YYYY-MM-DD（可选）
        pax: 人数

    Returns:
        门票/活动列表文本，包含名称、价格、时段和预订提示
    """
    city_data = _MOCK_PRODUCTS.get(city)
    if not city_data:
        known = ", ".join(_MOCK_PRODUCTS.keys())
        return f"抱歉，目前 {city} 暂无合作门票。已覆盖城市：{known}。更多城市即将上线！"

    tickets = city_data["tickets"]
    lines = [f"## {city} 门票/活动（{len(tickets)} 项）\n"]

    for i, t in enumerate(tickets, 1):
        if type and type not in t.get("name", "") and type not in t.get("note", ""):
            continue
        lines.append(
            f"### {i}. {t['name']}  ✅ 可预订\n"
            f"- 💰 价格：{t['price']}\n"
            f"- 🕐 时段：{t['time_slots']}\n"
        )
        if t.get("note"):
            lines.append(f"- 📝 注意：{t['note']}\n")

    if date:
        lines.append(f"\n> 游玩日期：{date}")
    lines.append(f"\n> 💡 总价估算：约 {len(tickets) * 50}~{len(tickets) * 200} ¥/人（以实际预订为准）")

    return "\n".join(lines)


@tool
def search_guides(city: str, language: str = "中文", date: str = "") -> str:
    """搜索目的地导游，返回可用导游列表及语言、专长和价格。

    用于帮助用户挑选当地导游。按城市和语言筛选。

    Args:
        city: 城市名称
        language: 需要的语言（默认"中文"，可选"英文"/"日文"/"韩文"/"法文"/"俄文"等）
        date: 服务日期 YYYY-MM-DD（可选）

    Returns:
        导游列表文本，包含姓名、语言、专长、价格和可订状态
    """
    city_data = _MOCK_PRODUCTS.get(city)
    if not city_data:
        known = ", ".join(_MOCK_PRODUCTS.keys())
        return f"抱歉，目前 {city} 暂无合作导游。已覆盖城市：{known}。"

    guides = city_data["guides"]
    lines = [f"## {city} 导游（{len(guides)} 位）\n"]

    found = 0
    for i, g in enumerate(guides, 1):
        if language not in g["languages"] and language != "中文":
            continue
        status_icon = {"available": "✅", "limited": "⚠️"}.get(g["status"], "❓")
        status_text = {"available": "可预订", "limited": "仅剩少量时段"}.get(g["status"], "未知")
        lines.append(
            f"### {i}. {g['name']}  {status_icon} {status_text}\n"
            f"- 🗣 语言：{g['languages']}\n"
            f"- 🎯 专长：{g['specialty']}\n"
            f"- 💰 价格：{g['price_per_day']}/天\n"
        )
        found += 1

    if found == 0:
        lines.append(f"\n暂未找到会说 {language} 的导游。可尝试切换语言筛选。")

    if date:
        lines.append(f"\n> 服务日期：{date}")

    return "\n".join(lines)


# =============================================================================
# 订单管理工具（4 个）
# =============================================================================


@tool
def get_order(order_id: str) -> str:
    """查询单个订单的详细信息及供应商确认状态。

    返回订单的所有行项目（酒店/机票/门票/导游），每个项目显示确认状态、
    确认号和联系方式。对于确认失败的项目，给出下一步建议。

    Args:
        order_id: 订单编号（格式：ORD-YYYYMMDDHHMMSS-XXXXXX）

    Returns:
        订单详情文本，含所有 item 状态和下一步建议
    """
    order = _ORDERS.get(order_id)
    if not order:
        return (
            f"❌ 未找到订单 {order_id}。\n\n"
            f"可能原因：\n"
            f"1. 订单号输入有误\n"
            f"2. 订单尚未创建\n"
            f"3. 订单已过期归档\n\n"
            f"请核对订单号后重试，或使用 list_orders 查看您的订单列表。"
        )

    items = order.get("items", [])
    status_map = {
        "confirmed": "✅ 已确认",
        "pending": "⏳ 确认中",
        "rejected": "❌ 确认失败",
        "cancelled": "🚫 已取消",
    }

    lines = [
        f"## 订单 {order_id}",
        f"",
        f"| 项目 | 状态 |",
        f"|------|------|",
        f"| 目的地 | {order.get('destination', '未知')} |",
        f"| 行程日期 | {order.get('trip_start', '')} ~ {order.get('trip_end', '')} |",
        f"| 人数 | {order.get('pax', 0)} 人 |",
        f"| 订单金额 | {order.get('total_amount', '待确认')} {order.get('currency', '¥')} |",
        f"| 支付状态 | {'✅ 已支付' if order.get('paid_at') else '⏳ 待支付'} |",
        f"| 整体状态 | {order.get('status', '未知')} |",
        f"",
        f"### 📋 供应商确认明细",
        f"",
        f"| 类型 | 产品 | 供应商 | 确认状态 | 确认号 |",
        f"|------|------|--------|----------|--------|",
    ]

    issues = []
    for item in items:
        status = item.get("confirm_status", "pending")
        status_text = status_map.get(status, "⏳ 确认中")
        lines.append(
            f"| {item.get('type', '')} | {item.get('product_name', '')} | "
            f"{item.get('supplier', '')} | {status_text} | "
            f"{item.get('confirm_ref', '-')} |"
        )
        if status == "rejected":
            issues.append(
                f"⚠️ {item.get('product_name', '')} 确认失败！"
                f"建议联系 {item.get('supplier', '供应商')} "
                f"（{item.get('contact_info', '暂无联系方式')}）"
            )
        elif status == "pending":
            issues.append(
                f"⏳ {item.get('product_name', '')} 仍在确认中，"
                f"预计 24 小时内更新。"
            )

    lines.append("")

    if issues:
        lines.append("### ⚠️ 需要关注的问题")
        for issue in issues:
            lines.append(f"- {issue}")
    else:
        lines.append("### ✅ 所有项目已确认，您的行程一切就绪！")

    # 倒计时
    trip_start = order.get("trip_start", "")
    if trip_start:
        lines.append(f"\n> 🗓 距出发还有 **计算中** 天（{trip_start}）")

    return "\n".join(lines)


@tool
def list_orders(user_id: str) -> str:
    """列出用户的所有订单摘要。

    按创建时间倒序排列，最多返回 10 条。每条包含订单号、目的地、
    状态和金额摘要。

    Args:
        user_id: 用户 ID

    Returns:
        订单摘要列表文本
    """
    user_orders = [
        o for o in _ORDERS.values()
        if o.get("user_id") == user_id
    ]
    # 按创建时间倒序
    user_orders.sort(key=lambda o: o.get("created_at", ""), reverse=True)

    if not user_orders:
        return "📭 您目前没有任何订单。\n\n当您通过销售顾问预订行程后，订单会出现在这里。"

    lines = [f"## 您的订单（{len(user_orders)} 笔）\n"]
    status_map = {
        "pending_confirmation": "⏳ 待确认",
        "confirmed": "✅ 已确认",
        "active": "🛫 进行中",
        "completed": "🏁 已完成",
        "cancelled": "🚫 已取消",
        "disputed": "⚡ 争议中",
    }

    for i, o in enumerate(user_orders[:10], 1):
        status_text = status_map.get(o.get("status", ""), o.get("status", "未知"))
        lines.append(
            f"### {i}. {o['order_id']}\n"
            f"- 📍 {o.get('destination', '未知')} · "
            f"{o.get('days', 0)} 天 · {o.get('pax', 0)} 人\n"
            f"- 💰 {o.get('total_amount', '待确认')} {o.get('currency', '¥')}\n"
            f"- 📊 {status_text}\n"
            f"- 📅 {o.get('trip_start', '')} ~ {o.get('trip_end', '')}\n"
        )

    return "\n".join(lines)


@tool
def cancel_order(order_id: str, reason: str = "") -> str:
    """取消订单。

    计算退款金额（根据距离出发日期的天数阶梯退款），
    生成取消确认信息。实际退款需人工审核。

    Args:
        order_id: 订单编号
        reason: 取消原因（可选，帮助改进服务）

    Returns:
        取消确认文本，包含退款计算和后续步骤
    """
    order = _ORDERS.get(order_id)
    if not order:
        return f"❌ 未找到订单 {order_id}。请核对订单号。"

    if order.get("status") in ("cancelled", "completed"):
        return f"订单 {order_id} 当前状态为 {order.get('status')}，无法取消。"

    # 模拟退款计算（阶梯退款）
    total = order.get("total_amount", "0")
    try:
        import re
        amount_match = re.search(r"[\d,]+", str(total))
        amount_num = int(amount_match.group().replace(",", "")) if amount_match else 0
    except Exception:
        amount_num = 0

    # 简化的阶梯退款逻辑
    trip_start = order.get("trip_start", "")
    if trip_start:
        try:
            start_date = datetime.strptime(trip_start, "%Y-%m-%d").date()
            days_until = (start_date - date.today()).days
            if days_until > 30:
                refund_rate = 0.9
            elif days_until > 14:
                refund_rate = 0.7
            elif days_until > 7:
                refund_rate = 0.5
            elif days_until > 3:
                refund_rate = 0.3
            else:
                refund_rate = 0.1
        except (ValueError, TypeError):
            refund_rate = 0.7
    else:
        refund_rate = 0.9  # 没有出发日期，默认全额退款

    refund_amount = int(amount_num * refund_rate)

    # 标记订单为已取消
    order["status"] = "cancelled"
    order["cancel_reason"] = reason

    lines = [
        f"## 订单取消确认",
        f"",
        f"订单号：**{order_id}**",
        f"目的地：{order.get('destination', '未知')}",
        f"原订单金额：{total} {order.get('currency', '¥')}",
        f"预计退款金额：**¥{refund_amount:,}**（退款比例 {int(refund_rate * 100)}%）",
        f"",
        f"### 📋 后续步骤",
        f"1. 退款将在 **3-7 个工作日** 内原路返回",
        f"2. 如已购买旅行保险，请单独联系保险公司",
        f"3. 如有疑问，可创建工单追踪退款进度",
    ]

    if reason:
        lines.append(f"\n取消原因：{reason}")

    return "\n".join(lines)


@tool
def modify_order(order_id: str, changes: str = "") -> str:
    """修改订单内容（改期、加人、减人、更换酒店等）。

    根据变更内容重新计算差价，生成变更确认信息。
    变更需所有供应商重新确认。

    Args:
        order_id: 订单编号
        changes: 变更内容描述（如"改期到2026-09-20出发"、"增加1人"、"换到王府井希尔顿"）

    Returns:
        变更确认文本，包含差价计算和重新确认说明
    """
    order = _ORDERS.get(order_id)
    if not order:
        return f"❌ 未找到订单 {order_id}。请核对订单号。"

    if order.get("status") in ("cancelled", "completed", "disputed"):
        return f"订单 {order_id} 当前状态为 {order.get('status')}，无法修改。"

    lines = [
        f"## 订单变更确认",
        f"",
        f"订单号：**{order_id}**",
        f"变更内容：{changes if changes else '（未指定具体变更）'}",
        f"",
        f"### 📊 变更影响",
    ]

    # 模拟差价计算
    import random
    diff = random.choice([-200, 0, 200, 350, 500])
    if diff > 0:
        lines.append(f"- 💰 需补差价：**+¥{diff}**")
    elif diff < 0:
        lines.append(f"- 💰 退还差价：**¥{abs(diff)}**")
    else:
        lines.append(f"- 💰 价格不变")

    lines.extend([
        f"",
        f"### 📋 注意事项",
        f"- 变更后所有供应商将重新确认（预计 24h 内）",
        f"- 如果供应商无法确认新内容，将自动回退原订单",
        f"- 差价将在变更确认后自动处理",
        f"",
        f"> 💡 需要我帮您提交变更吗？变更确认前原订单保持有效。",
    ])

    return "\n".join(lines)


# =============================================================================
# 工单系统（2 个）
# =============================================================================


@tool
def create_ticket(user_id: str, type: str, description: str,
                  order_id: str = "") -> str:
    """创建售后工单（投诉、退款申请、改期申请等）。

    工单创建后将自动分配优先级和预计处理时间。
    严重投诉（安全事故、伤亡）会自动升级为紧急工单。

    Args:
        user_id: 用户 ID
        type: 工单类型（complaint/refund/modification/inquiry/emergency）
        description: 问题描述
        order_id: 关联订单号（可选）

    Returns:
        工单创建确认文本，含工单号和预计处理时间
    """
    ticket_id = _make_ticket_id()

    # 自动判定优先级
    priority = "normal"
    emergency_keywords = ["事故", "安全", "伤亡", "诈骗", "紧急", "媒体", "报警"]
    if type == "emergency" or any(kw in description for kw in emergency_keywords):
        priority = "critical"
    elif type == "complaint" or "投诉" in description:
        priority = "urgent"

    etas = {
        "normal": "24 小时内响应",
        "urgent": "4 小时内响应",
        "critical": "1 小时内响应（已通知值班主管）",
    }

    _TICKETS[ticket_id] = {
        "ticket_id": ticket_id,
        "user_id": user_id,
        "order_id": order_id,
        "type": type,
        "priority": priority,
        "status": "open",
        "description": description,
        "resolution": "",
        "assigned_to": "值班运营" if priority == "critical" else "运营团队",
        "created_at": datetime.now().isoformat(),
        "updated_at": datetime.now().isoformat(),
    }

    lines = [
        f"## 工单已创建",
        f"",
        f"| 项目 | 详情 |",
        f"|------|------|",
        f"| 工单号 | **{ticket_id}** |",
        f"| 类型 | {type} |",
        f"| 优先级 | {'🔴 紧急' if priority == 'critical' else '🟡 加急' if priority == 'urgent' else '🟢 普通'} |",
        f"| 状态 | 已受理 |",
        f"| 处理人 | {_TICKETS[ticket_id]['assigned_to']} |",
        f"| 预计响应 | {etas.get(priority, '24 小时内')} |",
    ]

    if order_id:
        lines.append(f"| 关联订单 | {order_id} |")

    lines.extend([
        f"",
        f"### 您的问题描述",
        f"> {description}",
        f"",
        f"我们会尽快处理您的请求。如需查询进度，使用 check_ticket 并提供工单号 {ticket_id}。",
    ])

    return "\n".join(lines)


@tool
def check_ticket(ticket_id: str) -> str:
    """查询工单处理进度。

    返回工单的当前状态、处理人和处理结果（如有）。

    Args:
        ticket_id: 工单编号（格式：TK-YYYYMMDDHHMMSS-XXXXXX）

    Returns:
        工单状态文本
    """
    ticket = _TICKETS.get(ticket_id)
    if not ticket:
        return (
            f"❌ 未找到工单 {ticket_id}。\n\n"
            f"可能原因：\n"
            f"1. 工单号输入有误\n"
            f"2. 工单已关闭归档\n"
            f"3. 工单尚未创建\n\n"
            f"请核对工单号后重试。"
        )

    status_map = {
        "open": "🟢 已受理",
        "processing": "🔵 处理中",
        "resolved": "✅ 已解决",
        "closed": "📁 已归档",
    }

    priority_map = {
        "normal": "普通",
        "urgent": "加急",
        "critical": "紧急",
    }

    lines = [
        f"## 工单 {ticket_id}",
        f"",
        f"| 项目 | 详情 |",
        f"|------|------|",
        f"| 类型 | {ticket.get('type', '')} |",
        f"| 优先级 | {priority_map.get(ticket.get('priority', ''), '普通')} |",
        f"| 状态 | {status_map.get(ticket.get('status', ''), '未知')} |",
        f"| 处理人 | {ticket.get('assigned_to', '待分配')} |",
        f"| 创建时间 | {ticket.get('created_at', '')} |",
    ]

    if ticket.get("order_id"):
        lines.append(f"| 关联订单 | {ticket.get('order_id', '')} |")

    if ticket.get("resolution"):
        lines.extend([
            f"",
            f"### 📝 处理结果",
            f"{ticket['resolution']}",
        ])

    if ticket.get("status") == "resolved":
        lines.extend([
            f"",
            f"> ✅ 工单已解决。如果对处理结果不满意，可创建新工单说明。",
        ])

    return "\n".join(lines)
