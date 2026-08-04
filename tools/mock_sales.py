"""Mock 销售工具——订单、支付、优惠、行程加载

Phase 20: 销售 Agent 重设计所需的工具集。
所有工具返回 mock 数据，未来可对接真实支付/订单系统。
"""

import json
import uuid
from datetime import datetime, timedelta, timezone
from langchain_core.tools import tool


# =============================================================================
# 内存订单存储（模拟订单数据库）
# =============================================================================

_ORDERS: dict[str, dict] = {}  # order_id → order dict


def _make_order_id() -> str:
    return f"ORD-{uuid.uuid4().hex[:8].upper()}"


def _make_coupon_code() -> str:
    return f"TRIP{uuid.uuid4().hex[:4].upper()}"


# =============================================================================
# 工具定义
# =============================================================================


@tool
def load_trip_draft(draft_id: str = "", destination: str = "", days: int = 0,
                    pax: int = 0, budget: str = "") -> str:
    """加载或查看用户的行程方案。

    用于销售场景下回顾客户之前设计的行程，以便精准推荐和报价。
    如果没有 draft_id，可以根据目的地/天数/人数等参数模拟加载。

    Args:
        draft_id: 行程方案标识（如 session_id），可选
        destination: 目的地城市，可选
        days: 行程天数，可选
        pax: 出行人数，可选
        budget: 预算，可选

    Returns:
        结构化的行程方案文本
    """
    dest = destination or "目的地"
    d = days or 5
    p = pax or 2
    b = budget or "¥5000/人"

    lines = [
        f"## 行程方案概要",
        "",
        f"- **方案编号**：{draft_id or 'DRAFT-' + uuid.uuid4().hex[:6].upper()}",
        f"- **目的地**：{dest}",
        f"- **天数**：{d} 天",
        f"- **人数**：{p} 人",
        f"- **预算**：{b}",
        "",
        "### 行程亮点",
        f"- Day 1：抵达{dest}，专车接机，入住精选四星酒店",
        f"- Day 2-{d-1}：核心景点深度游 + 特色美食体验",
        f"- Day {d}：自由活动 + 送机服务",
        "",
        "### 包含服务",
        "- 全程专车接送（含司机+中文导游）",
        "- {d}晚四星/精品酒店住宿（含早）",
        "- 主要景点门票 + 2个特色体验项目",
        "- 每日特色餐饮推荐",
        "",
        f"> 📌 此方案可随时调整，您可以告诉销售顾问需要修改的部分。",
    ]

    return "\n".join(lines)


@tool
def create_order(draft_id: str, quote_ref: str = "", notes: str = "") -> str:
    """创建行程预订订单。

    在客户确认购买意向后，创建正式的订单记录。
    订单创建后会返回订单号，可用于后续支付和追踪。

    Args:
        draft_id: 关联的行程方案标识
        quote_ref: 报价单引用（报价摘要或报价单 ID），可选
        notes: 订单备注（特殊需求等），可选

    Returns:
        订单创建结果，包含订单号
    """
    order_id = _make_order_id()
    now = datetime.now(timezone.utc)

    _ORDERS[order_id] = {
        "order_id": order_id,
        "draft_id": draft_id,
        "quote_ref": quote_ref,
        "notes": notes,
        "status": "pending_payment",
        "created_at": now.isoformat(),
        "expires_at": (now + timedelta(hours=48)).isoformat(),
    }

    lines = [
        f"## 订单已创建 ✅",
        "",
        f"| 项目 | 详情 |",
        f"|------|------|",
        f"| 订单编号 | **{order_id}** |",
        f"| 关联方案 | {draft_id} |",
        f"| 状态 | 待支付 |",
        f"| 创建时间 | {now.strftime('%Y-%m-%d %H:%M')} |",
        f"| 支付截止 | {(now + timedelta(hours=48)).strftime('%Y-%m-%d %H:%M')} |",
        "",
        "> ⚠️ 请在 48 小时内完成支付，超时订单将自动取消。",
    ]

    if notes:
        lines.append(f"\n> 📝 备注：{notes}")

    return "\n".join(lines)


@tool
def get_payment_url(order_id: str) -> str:
    """获取订单的支付链接。

    生成安全的支付页面链接，客户可通过此链接完成在线支付。
    支持微信支付、支付宝、信用卡等支付方式。

    Args:
        order_id: 订单编号（由 create_order 返回）

    Returns:
        支付链接信息
    """
    if order_id not in _ORDERS:
        return f"[get_payment_url] 订单 {order_id} 不存在，请先创建订单。"

    order = _ORDERS[order_id]
    if order["status"] != "pending_payment":
        return f"[get_payment_url] 订单 {order_id} 当前状态为「{order['status']}」，无法支付。"

    payment_url = f"https://pay.example.com/order/{order_id}"

    lines = [
        f"## 支付链接",
        "",
        f"| 项目 | 详情 |",
        f"|------|------|",
        f"| 订单编号 | {order_id} |",
        f"| 支付链接 | {payment_url} |",
        f"| 支持方式 | 微信支付 / 支付宝 / Visa / Mastercard |",
        f"| 有效期至 | {order['expires_at'][:16] if order.get('expires_at') else '48小时后'} |",
        "",
        "> 💳 点击链接即可完成支付，支付成功后行程即刻锁定。",
        "> 🔒 支付过程由第三方支付平台加密保护，请放心使用。",
    ]

    return "\n".join(lines)


@tool
def apply_coupon(user_id: str, draft_id: str, amount: str = "") -> str:
    """为客户发放优惠券，应用于当前行程方案。

    优惠以分项折扣形式发放（机票、酒店、门票中选 1-2 项），
    而非全单打折，更自然合理。

    Args:
        user_id: 用户 ID
        draft_id: 关联的行程方案标识
        amount: 优惠金额描述（如 "¥200"、"酒店 95 折"），可选

    Returns:
        优惠券详情
    """
    code = _make_coupon_code()
    amount_desc = amount or "¥200"

    # 随机选择 1-2 个优惠项目
    items = ["酒店", "机票", "门票", "餐饮"]
    import random
    selected = random.sample(items, k=random.randint(1, 2))

    discount_items = []
    for item in selected:
        if "%" in amount_desc or "折" in amount_desc:
            discount_items.append(f"- {item}：{amount_desc}")
        else:
            discount_items.append(f"- {item}：减免 {amount_desc}")

    lines = [
        f"## 专属优惠券 🎫",
        "",
        f"| 项目 | 详情 |",
        f"|------|------|",
        f"| 券码 | **{code}** |",
        f"| 适用范围 | {', '.join(selected)} |",
        f"| 有效期 | 3 天 |",
        f"| 关联方案 | {draft_id} |",
        "",
        "### 优惠明细",
    ] + discount_items + [
        "",
        f"> 🎉 此优惠已自动应用到您的行程方案中。",
        f"> 📌 券码 {code} 将在 3 天后过期，请尽快使用。",
    ]

    return "\n".join(lines)


@tool
def check_order_status(user_id: str) -> str:
    """检查用户是否有未完成或已完成的订单。

    用于防止重复下单，也用于跟进时判断用户当前状态。

    Args:
        user_id: 用户 ID

    Returns:
        订单状态摘要
    """
    # 在内存中查找相关订单（mock 实现简单遍历）
    user_orders = []
    for oid, order in _ORDERS.items():
        # mock: 用 draft_id 关联用户（实际应有关联表）
        user_orders.append(order)

    if not user_orders:
        return f"[check_order_status] 用户 {user_id} 暂无订单记录。"

    lines = [f"## 订单状态查询（用户 {user_id}）", ""]
    for order in user_orders[-5:]:  # 最近 5 条
        status_icon = {
            "pending_payment": "⏳ 待支付",
            "paid": "✅ 已支付",
            "cancelled": "❌ 已取消",
            "refunded": "↩️ 已退款",
        }.get(order["status"], order["status"])
        lines.append(
            f"- {order['order_id']} | {status_icon} | "
            f"创建：{order['created_at'][:10]}"
        )

    return "\n".join(lines)
