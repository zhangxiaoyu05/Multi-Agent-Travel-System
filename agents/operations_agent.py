"""运营 Agent——用户与产品的桥梁（Phase 21 重写）

覆盖场景：
- 产品查询：搜索酒店/航班/门票/导游
- 订单管理：查看/跟踪/取消/变更
- 行中保障：诊断问题、协调资源
- 售后工单：投诉/退款/赔付

核心设计：
- 单 Prompt + 场景识别（不拆分阶段 Prompt）
- 工具作为平台共享能力层（trip_planner/sales 也可调用）
- 成交接管：WON 时主动生成接管消息
- 紧急升级：安全事故/重大投诉立即转人工
"""

import json
import logging
from agents.base import BaseAgent
from graph.state import AgentState
from tools.mcp_tools import (
    search_hotels,
    search_flights,
    search_tickets,
    search_guides,
    get_order,
    list_orders,
    cancel_order,
    modify_order,
    create_ticket,
    check_ticket,
    update_crm,
    send_capi,
)
from services.llm import get_light_llm
from prompts import load_prompt

logger = logging.getLogger(__name__)


class OperationsAgent(BaseAgent):
    """运营专员——用户与产品的桥梁"""

    def __init__(self):
        llm = get_light_llm()
        tools = [
            # 产品查询
            search_hotels, search_flights, search_tickets, search_guides,
            # 订单管理
            get_order, list_orders, cancel_order, modify_order,
            # 工单
            create_ticket, check_ticket,
            # 保留
            update_crm, send_capi,
        ]
        system_prompt = load_prompt("operations_agent.txt")
        super().__init__(llm=llm, tools=tools, system_prompt=system_prompt)

    async def run(self, state: AgentState) -> dict:
        user_msg = self._get_user_message(state)
        language = self._get_language(state)
        customer_id = state.get("customer_id", "unknown")
        session_id = state.get("session_id", "")

        # ── 第 1 步：加载活跃订单 ──
        active_order = await self._load_active_order(customer_id)

        # ── 第 2 步：检测是否刚成交（WON → 接管） ──
        is_handoff = state.get("sales_pipeline_stage") == "won"
        if is_handoff:
            handoff_msg = self._build_handoff_message(active_order)
        else:
            handoff_msg = ""

        # ── 第 3 步：构建 extra_context ──
        extra_context = self._build_extra_context(state, active_order, handoff_msg)

        # ── 第 4 步：空消息兜底 ──
        if not user_msg:
            return self._empty_reply(active_order, is_handoff, handoff_msg)

        # ── 第 5 步：LLM + Tool Calling ──
        loop_result = await self._run_tool_calling_loop(
            user_msg, language=language, extra_context=extra_context,
            session_id=session_id,
        )
        final_text = loop_result["final_text"]
        need_human = loop_result["need_human"]

        # ── 第 6 步：紧急升级检测 ──
        need_human = self._check_escalation(user_msg, final_text, need_human)

        # ── 第 7 步：CRM 强制写入 ──
        crm_result = loop_result["tool_results"].get("update_crm", "")
        if not crm_result:
            await self._enforce_crm_write(customer_id, user_msg, need_human)

        # ── 第 8 步：构建订单上下文 ──
        order_context = self._build_order_context(active_order)

        # ── 第 9 步：构建返回 ──
        return {
            "final_reply": final_text,
            "need_human": need_human,
            "order_context": order_context,
            "intent_level": "high" if need_human else "mid",
            "next_action": "accept",
        }

    # =========================================================================
    # 订单加载
    # =========================================================================

    async def _load_active_order(self, customer_id: str) -> dict | None:
        """从 DB 加载用户活跃订单"""
        try:
            from services.memory import MemoryManager
            mm = MemoryManager()
            return await mm.get_active_order(customer_id)
        except Exception as e:
            logger.debug("Failed to load active order: %s", e)
            return None

    # =========================================================================
    # 成交接管
    # =========================================================================

    def _build_handoff_message(self, active_order: dict | None) -> str:
        """生成 WON 接管开场白

        销售刚成交 → 运营接管，主动介绍后续流程。
        """
        if not active_order:
            return (
                "【系统提示】客户刚完成支付。"
                "在回复中主动介绍接下来会发生什么："
                "1) 订单确认（各供应商正在确认中）"
                "2) 出行准备（出发前3天发送出行须知）"
                "3) 行中保障（旅途中随时联系）"
                "让客户感到安心和'有人管'。"
            )

        dest = active_order.get("destination", "")
        days = active_order.get("days", 0)
        order_id = active_order.get("order_id", "")

        items_count = len(active_order.get("items", []))
        confirmed = sum(
            1 for item in active_order.get("items", [])
            if item.get("confirm_status") == "confirmed"
        )

        return (
            f"【系统提示】订单 {order_id} 已创建。"
            f"客户行程：{dest}{days}天。"
            f"订单共 {items_count} 项产品，目前 {confirmed} 项已确认。"
            f"在回复中说明接下来会跟进各供应商确认，"
            f"出发前3天发送出行须知，行中随时联系。"
        )

    # =========================================================================
    # extra_context 构建
    # =========================================================================

    def _build_extra_context(
        self, state: AgentState, active_order: dict | None,
        handoff_msg: str,
    ) -> dict | None:
        """构建传给 LLM 的附加上下文"""
        ctx = {}

        # 用户画像
        profile = state.get("user_profile", {}) or {}
        if profile.get("nationality"):
            ctx["客户国籍"] = profile["nationality"]

        # 订单摘要
        if active_order:
            ctx["活跃订单"] = {
                "订单号": active_order.get("order_id", ""),
                "目的地": active_order.get("destination", ""),
                "天数": active_order.get("days", 0),
                "人数": active_order.get("pax", 0),
                "状态": active_order.get("status", ""),
                "总金额": f"{active_order.get('total_amount', '')} {active_order.get('currency', '¥')}",
                "出发日期": active_order.get("trip_start", ""),
            }
            items = active_order.get("items", [])
            if items:
                ctx["订单行项目"] = [
                    f"{it.get('type', '')}: {it.get('product_name', '')} "
                    f"({it.get('confirm_status', 'pending')})"
                    for it in items
                ]

        # WON 接管消息
        if handoff_msg:
            ctx["交接指令"] = handoff_msg

        # 是否有刚成交的状态
        if state.get("sales_pipeline_stage") == "won":
            ctx["刚成交"] = True

        return ctx if ctx else None

    # =========================================================================
    # 空消息兜底
    # =========================================================================

    def _empty_reply(self, active_order: dict | None, is_handoff: bool,
                     handoff_msg: str) -> dict:
        """无用户消息时的兜底回复"""
        if is_handoff:
            if active_order:
                dest = active_order.get("destination", "未知")
                days = active_order.get("days", 0)
                order_id = active_order.get("order_id", "")
                text = (
                    f"支付确认！您的 {dest}{days}日游 已生效。\n\n"
                    f"订单号：**{order_id}**\n\n"
                    f"接下来我会为您跟进 3 件事：\n"
                    f"① 供应商确认——各酒店/门票/导游正在确认中，预计 24 小时内完成\n"
                    f"② 出行准备——出发前 3 天为您发送出行须知和注意事项\n"
                    f"③ 行中保障——旅途中遇到任何问题，随时联系我协调处理\n\n"
                    f"现在有什么需要我帮您处理的吗？"
                )
            else:
                text = (
                    f"支付确认！您的订单已生效。\n\n"
                    f"接下来我会为您跟进供应商确认、出行准备和行中保障。\n"
                    f"有任何问题随时联系我！"
                )
        elif active_order:
            dest = active_order.get("destination", "未知")
            text = (
                f"您好！我是您的运营专员。\n"
                f"您的 {dest} 行程订单正在进行中，有什么需要帮您处理的吗？"
            )
        else:
            text = "您好！我是运营专员，有什么运营相关的问题需要处理吗？比如查询订单、搜索酒店机票、或者行程中遇到什么问题？"

        return {
            "final_reply": text,
            "need_human": False,
            "order_context": self._build_order_context(active_order),
            "intent_level": "mid",
            "next_action": "accept",
        }

    # =========================================================================
    # 紧急升级
    # =========================================================================

    def _check_escalation(self, user_msg: str, final_text: str,
                          need_human: bool) -> bool:
        """检测是否需要紧急升级

        安全事故、重大投诉、用户明确要求 → 立即转人工。
        """
        if need_human:
            return True

        escalation_keywords = [
            "投诉", "退款", "骗人", "诈骗", "报警", "重大事故",
            "伤亡", "安全事故", "媒体曝光", "叫你们主管", "找你们领导",
        ]
        for kw in escalation_keywords:
            if kw in user_msg:
                return True

        return False

    # =========================================================================
    # CRM 强制写入
    # =========================================================================

    async def _enforce_crm_write(self, customer_id: str, user_msg: str,
                                 need_human: bool) -> None:
        """兜底 CRM 写入——确保每次运营交互都有记录"""
        session_summary = json.dumps({
            "customer_id": customer_id,
            "branch": "operations",
            "user_message": user_msg[:200],
            "need_human": need_human,
        }, ensure_ascii=False)
        try:
            update_crm.invoke({
                "customer_id": customer_id,
                "session_data": session_summary,
            })
        except Exception:
            pass

    # =========================================================================
    # 订单上下文
    # =========================================================================

    def _build_order_context(self, active_order: dict | None) -> dict:
        """构建轻量订单上下文（用于 State 传递）"""
        if not active_order:
            return {}
        return {
            "order_id": active_order.get("order_id", ""),
            "status": active_order.get("status", ""),
            "destination": active_order.get("destination", ""),
            "trip_start": active_order.get("trip_start", ""),
            "trip_end": active_order.get("trip_end", ""),
            "items_summary": [
                f"{it.get('type', '')}: {it.get('product_name', '')}"
                for it in active_order.get("items", [])
            ],
        }


# =============================================================================
# 模块级单例
# =============================================================================

_agent_instance: OperationsAgent | None = None


def get_operations_agent() -> OperationsAgent:
    global _agent_instance
    if _agent_instance is None:
        _agent_instance = OperationsAgent()
    return _agent_instance
