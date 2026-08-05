"""测试销售分支：Phase 20 重写——Pipeline + 工具 + 跟进 + 条件边

覆盖：
- 5 个新销售工具（mock）
- Pipeline 阶段判定逻辑
- 跟进策略（24h/3d/7d）
- after_sales 条件边（含 trip_planner 路由）
- 销售节点（Mock Agent）
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# =============================================================================
# 销售工具测试（Mock）
# =============================================================================


class TestSalesTools:
    """5 个新 Mock 工具 + 保留的 quote_price"""

    def test_load_trip_draft(self):
        from tools.mock_sales import load_trip_draft
        result = load_trip_draft.invoke({
            "destination": "北京", "days": 3, "pax": 2,
        })
        assert "北京" in result
        assert "3 天" in result
        assert "2 人" in result

    def test_load_trip_draft_with_draft_id(self):
        from tools.mock_sales import load_trip_draft
        result = load_trip_draft.invoke({
            "draft_id": "DRAFT-ABC123", "destination": "三亚", "days": 5, "pax": 1,
        })
        assert "DRAFT-ABC123" in result
        assert "三亚" in result

    def test_create_order(self):
        from tools.mock_sales import create_order
        result = create_order.invoke({
            "draft_id": "session-001", "quote_ref": "报价单摘要",
        })
        assert "ORD-" in result
        assert "订单已创建" in result
        assert "待支付" in result

    def test_create_order_with_notes(self):
        from tools.mock_sales import create_order
        result = create_order.invoke({
            "draft_id": "session-002", "notes": "需要素食安排",
        })
        assert "ORD-" in result
        assert "素食" in result

    def test_get_payment_url_valid(self):
        from tools.mock_sales import create_order, get_payment_url
        # 先创建订单
        order_result = create_order.invoke({"draft_id": "test"})
        import re
        order_id = re.search(r"ORD-[A-Z0-9]+", order_result).group()
        # 获取支付链接
        result = get_payment_url.invoke({"order_id": order_id})
        assert "pay.example.com" in result
        assert order_id in result

    def test_get_payment_url_nonexistent(self):
        from tools.mock_sales import get_payment_url
        result = get_payment_url.invoke({"order_id": "ORD-FAKE"})
        assert "不存在" in result

    def test_apply_coupon(self):
        from tools.mock_sales import apply_coupon
        result = apply_coupon.invoke({
            "user_id": "user-001", "draft_id": "session-001",
            "amount": "¥200",
        })
        assert "TRIP" in result
        assert "优惠" in result

    def test_check_order_status_empty(self):
        from tools.mock_sales import check_order_status, _ORDERS
        # 清空全局订单存储，确保测试隔离
        _ORDERS.clear()
        result = check_order_status.invoke({"user_id": "new-user"})
        assert "暂无订单" in result

    def test_check_order_status_with_orders(self):
        from tools.mock_sales import create_order, check_order_status
        # 先创建订单
        create_order.invoke({"draft_id": "test", "quote_ref": "test"})
        result = check_order_status.invoke({"user_id": "user-001"})
        # 全局 _ORDERS 已经有数据
        assert "ORD-" in result or "待支付" in result

    def test_quote_price_still_works(self):
        """保留旧工具的回归测试"""
        from tools.mock_quote import quote_price
        result = quote_price.invoke({
            "destination": "西安", "days": 4, "pax": 2,
            "theme": "历史文化", "pace": "适中", "currency": "¥",
        })
        assert "西安" in result
        assert "¥" in result

    def test_query_inventory_still_works(self):
        """保留旧工具的回归测试"""
        from tools.mock_inventory import query_inventory
        result = query_inventory.invoke({"city": "成都", "date": "2026-09-15", "pax": 2})
        assert "成都" in result


# =============================================================================
# MCP Tool 包装器测试（新工具注册）
# =============================================================================


class TestMCPToolRegistration:
    """验证新工具在 mcp_tools 中正确注册（MCP→Mock 降级）"""

    def test_check_order_status_mcp(self):
        from tools.mcp_tools import check_order_status
        result = check_order_status.invoke({"user_id": "test-mcp"})
        assert isinstance(result, str)

    def test_get_payment_url_mcp(self):
        from tools.mcp_tools import get_payment_url
        result = get_payment_url.invoke({"order_id": "ORD-TEST"})
        assert isinstance(result, str)

    def test_apply_coupon_mcp(self):
        from tools.mcp_tools import apply_coupon
        result = apply_coupon.invoke({"user_id": "u1", "draft_id": "d1", "amount": "¥100"})
        assert isinstance(result, str)

    def test_load_trip_draft_mcp(self):
        from tools.mcp_tools import load_trip_draft
        result = load_trip_draft.invoke({"destination": "北京"})
        assert isinstance(result, str)

    def test_create_order_mcp(self):
        from tools.mcp_tools import create_order
        result = create_order.invoke({"draft_id": "test"})
        assert "ORD-" in result


# =============================================================================
# Pipeline 阶段判定逻辑
# =============================================================================


class TestSalesPipeline:
    """阶段判定逻辑——纯函数测试"""

    def test_lead_to_qualified_when_draft_exists(self):
        from agents.sales_agent import _determine_next_stage
        stage = _determine_next_stage("lead", "我想去北京", "好的，帮您安排", has_draft=True)
        assert stage == "qualified"

    def test_lead_stays_when_no_draft(self):
        from agents.sales_agent import _determine_next_stage
        stage = _determine_next_stage("lead", "我想去旅行", "好的", has_draft=False)
        assert stage == "lead"

    def test_strong_buy_to_closing(self):
        from agents.sales_agent import _determine_next_stage
        stage = _determine_next_stage(
            "qualified", "我要预订", "好的", has_draft=True,
        )
        assert stage == "closing"

    def test_rejection_to_lost(self):
        from agents.sales_agent import _determine_next_stage
        stage = _determine_next_stage(
            "negotiation", "太贵了不买了", "好的", has_draft=True,
        )
        assert stage == "lost"

    def test_price_discussion_to_negotiation(self):
        from agents.sales_agent import _determine_next_stage
        stage = _determine_next_stage(
            "qualified", "价格有点贵", "我理解", has_draft=True,
        )
        assert stage == "negotiation"

    def test_order_created_stays_closing(self):
        """v4.1: 仅创建订单（未支付）不应触发 WON，保持 closing 状态"""
        from agents.sales_agent import _determine_next_stage
        stage = _determine_next_stage(
            "closing", "好的我付款", "订单已创建 ORD-ABC12345，回复「支付」完成付款", has_draft=True,
        )
        assert stage == "closing", f"Expected closing, got {stage}"

    def test_payment_success_to_won(self):
        """v4.1: 支付成功后应触发 WON"""
        from agents.sales_agent import _determine_next_stage
        stage = _determine_next_stage(
            "closing", "支付", "支付成功！您的订单 ORD-ABC12345 已确认，行程已锁定。", has_draft=True,
        )
        assert stage == "won", f"Expected won, got {stage}"

    def test_process_payment_tool_to_won(self):
        """v4.1: 调用 process_payment 工具成功后应触发 WON"""
        from agents.sales_agent import _determine_next_stage
        stage = _determine_next_stage(
            "closing", "支付", "正在处理...", has_draft=True,
            tool_results={"process_payment": "支付成功 ✅\n订单编号 ORD-XYZ\n交易流水号 TXN-ABC"}
        )
        assert stage == "won", f"Expected won, got {stage}"


# =============================================================================
# 行程修改检测
# =============================================================================


class TestTripModification:
    """检测用户是否想修改行程"""

    def test_detect_modify_trip(self):
        from agents.sales_agent import _detect_trip_modification
        assert _detect_trip_modification("我想改一下行程") is True
        assert _detect_trip_modification("能不能调整一下酒店") is True
        assert _detect_trip_modification("换个景点吧") is True
        assert _detect_trip_modification("重新设计一下") is True
        assert _detect_trip_modification("不想去长城了") is True

    def test_no_modification_normal_msg(self):
        from agents.sales_agent import _detect_trip_modification
        assert _detect_trip_modification("这个价格怎么样") is False
        assert _detect_trip_modification("我想预订") is False
        assert _detect_trip_modification("好的谢谢") is False


# =============================================================================
# 跟进策略
# =============================================================================


class TestSalesFollowup:
    """跟进时间窗口和消息生成"""

    def test_followup_message_24h(self):
        from agents.sales_agent import SalesAgent
        agent = SalesAgent()
        pipeline = {
            "stage": "qualified", "followup_count": 0,
            "discount_offered": False, "_gentle_nudge": True,
        }
        draft = {"destination": "北京", "days": 3}
        msg = agent._build_followup_message(pipeline, draft)
        assert "北京" in msg
        assert "24" in msg or "行程方案还在" in msg

    def test_followup_message_3d(self):
        from agents.sales_agent import SalesAgent
        agent = SalesAgent()
        pipeline = {
            "stage": "qualified", "followup_count": 0,
            "discount_offered": False, "_offer_discount": True,
        }
        draft = {"destination": "三亚", "days": 5}
        msg = agent._build_followup_message(pipeline, draft)
        assert "三亚" in msg
        assert "优惠" in msg

    def test_followup_auto_lost_returns_empty(self):
        from agents.sales_agent import SalesAgent
        agent = SalesAgent()
        pipeline = {
            "stage": "qualified", "followup_count": 2,
            "_auto_lost": True,
        }
        msg = agent._build_followup_message(pipeline, None)
        assert msg == ""
        assert pipeline["stage"] == "lost"

    def test_stage_to_intent_mapping(self):
        from agents.sales_agent import SalesAgent
        assert SalesAgent._stage_to_intent("lead") == "mid"
        assert SalesAgent._stage_to_intent("qualified") == "mid"
        assert SalesAgent._stage_to_intent("negotiation") == "high"
        assert SalesAgent._stage_to_intent("closing") == "high"
        assert SalesAgent._stage_to_intent("won") == "high"
        assert SalesAgent._stage_to_intent("lost") == "low"


# =============================================================================
# after_sales 条件边（Phase 20 扩展）
# =============================================================================


class TestAfterSales:
    """销售后置条件边——四路分发（含 trip_planner）"""

    def test_need_human_routes_to_handoff(self):
        from graph.conditions.after_sales import after_sales
        state = {"need_human": True}
        assert after_sales(state) == "human_handoff"

    def test_goto_planner_routes_to_trip_planner(self):
        from graph.conditions.after_sales import after_sales
        state = {"need_human": False, "goto_planner": True}
        assert after_sales(state) == "trip_planner"

    def test_won_to_operations_handoff(self):
        """Phase 21: WON 应路由到 operations_handoff（运营接管）而非直接 operations_sync"""
        from graph.conditions.after_sales import after_sales
        state = {"need_human": False, "goto_planner": False, "sales_pipeline_stage": "won"}
        assert after_sales(state) == "operations_handoff"

    def test_lost_to_end(self):
        from graph.conditions.after_sales import after_sales
        state = {"need_human": False, "goto_planner": False, "sales_pipeline_stage": "lost"}
        assert after_sales(state) == "end"

    def test_need_human_always_priority(self):
        """need_human=True 始终优先，忽略其他字段"""
        from graph.conditions.after_sales import after_sales
        state = {
            "need_human": True,
            "goto_planner": True,
            "sales_pipeline_stage": "won",
        }
        assert after_sales(state) == "human_handoff"

    def test_goto_planner_over_won(self):
        """goto_planner 优先于 won"""
        from graph.conditions.after_sales import after_sales
        state = {
            "need_human": False,
            "goto_planner": True,
            "sales_pipeline_stage": "won",
        }
        assert after_sales(state) == "trip_planner"

    def test_legacy_high_intent_to_sync(self):
        """兼容旧版 intent_level=high → operations_sync"""
        from graph.conditions.after_sales import after_sales
        state = {"need_human": False, "intent_level": "high"}
        assert after_sales(state) == "operations_sync"

    def test_legacy_accept_to_sync(self):
        from graph.conditions.after_sales import after_sales
        state = {"need_human": False, "intent_level": "mid", "next_action": "accept"}
        assert after_sales(state) == "operations_sync"

    def test_default_to_end(self):
        from graph.conditions.after_sales import after_sales
        state = {"need_human": False}
        assert after_sales(state) == "end"


# =============================================================================
# 销售节点（Mock Agent）
# =============================================================================


class TestSalesNode:
    """销售节点——Mock SalesAgent 的图节点包装"""

    @patch("graph.nodes.sales_agent.get_sales_agent")
    async def test_node_returns_reply(self, mock_get_agent, sales_state):
        mock_agent = MagicMock()
        mock_agent.run = AsyncMock(return_value={
            "final_reply": "根据您的需求，三亚5日游报价如下...",
            "need_human": False,
            "sales_pipeline_stage": "closing",
            "goto_planner": False,
            "quote": "报价单内容...",
            "intent_level": "high",
            "next_action": "accept",
        })
        mock_get_agent.return_value = mock_agent

        from graph.nodes.sales_agent import sales_agent
        result = await sales_agent(sales_state)

        assert "final_reply" in result
        assert result["final_reply"] == "根据您的需求，三亚5日游报价如下..."
        assert result["sales_pipeline_stage"] == "closing"

    @patch("graph.nodes.sales_agent.get_sales_agent")
    async def test_node_returns_pipeline_stage(self, mock_get_agent, sales_qualified_state):
        """QUALIFIED 阶段应正确传递 pipeline stage"""
        mock_agent = MagicMock()
        mock_agent.run = AsyncMock(return_value={
            "final_reply": "北京三日游的行程您还满意吗？",
            "need_human": False,
            "sales_pipeline_stage": "qualified",
            "goto_planner": False,
            "intent_level": "mid",
            "next_action": "revise",
        })
        mock_get_agent.return_value = mock_agent

        from graph.nodes.sales_agent import sales_agent
        result = await sales_agent(sales_qualified_state)

        assert result["sales_pipeline_stage"] == "qualified"
        assert result["current_branch"] == "sales_agent"

    @patch("graph.nodes.sales_agent.get_sales_agent")
    async def test_node_goto_planner(self, mock_get_agent, sales_qualified_state):
        """用户要修改行程 → goto_planner=True"""
        mock_agent = MagicMock()
        mock_agent.run = AsyncMock(return_value={
            "final_reply": "好的，我帮您转到行程定制。",
            "need_human": False,
            "sales_pipeline_stage": "qualified",
            "goto_planner": True,
            "intent_level": "mid",
            "next_action": "revise",
        })
        mock_get_agent.return_value = mock_agent

        from graph.nodes.sales_agent import sales_agent
        result = await sales_agent(sales_qualified_state)

        assert result["goto_planner"] is True
        assert result["agent_traces"][0]["action"] == "redirected_to_planner"

    @patch("graph.nodes.sales_agent.get_sales_agent")
    async def test_node_need_human(self, mock_get_agent):
        """投诉类销售请求应触发转人工"""
        from langchain_core.messages import HumanMessage

        complaint_state = {
            "messages": [HumanMessage(content="你们的报价太贵了，我要投诉！")],
            "session_id": "test-sales-c",
            "customer_id": "cust-sales-c",
            "channel": "web",
            "language": "zh",
        }

        mock_agent = MagicMock()
        mock_agent.run = AsyncMock(return_value={
            "final_reply": "正在为您转接人工客服...",
            "need_human": True,
            "sales_pipeline_stage": "qualified",
            "goto_planner": False,
            "intent_level": "low",
            "next_action": "give_up",
        })
        mock_get_agent.return_value = mock_agent

        from graph.nodes.sales_agent import sales_agent
        result = await sales_agent(complaint_state)

        assert result["need_human"] is True
        assert result["current_branch"] == "sales_agent"

    @patch("graph.nodes.sales_agent.get_sales_agent")
    async def test_node_won_deal(self, mock_get_agent, sales_qualified_state):
        """成交场景"""
        mock_agent = MagicMock()
        mock_agent.run = AsyncMock(return_value={
            "final_reply": "订单已创建 ORD-ABC12345，请点击支付链接完成支付。",
            "need_human": False,
            "sales_pipeline_stage": "won",
            "goto_planner": False,
            "quote": "报价单",
            "intent_level": "high",
            "next_action": "accept",
        })
        mock_get_agent.return_value = mock_agent

        from graph.nodes.sales_agent import sales_agent
        result = await sales_agent(sales_qualified_state)

        assert result["sales_pipeline_stage"] == "won"
        assert result["agent_traces"][0]["action"] == "closed_deal"


# =============================================================================
# 回归测试：_build_draft_context 从对话历史提取（Phase 21 E2E 发现）
# =============================================================================


class TestDraftContextFromHistory:
    """验证 _build_draft_context 在没有正式 need/draft 时也能从对话中提取"""

    def test_extract_destination_from_messages(self):
        """对话中提到北京，应自动提取 destination=北京"""
        from langchain_core.messages import HumanMessage, AIMessage
        from agents.sales_agent import _build_draft_context

        state = {
            "messages": [
                HumanMessage(content="我想去北京玩3天"),
                AIMessage(content="好的，北京3日游，请问预算多少？"),
                HumanMessage(content="2500以内"),
            ],
        }
        result = _build_draft_context(state)
        assert result is not None, "应从对话历史中提取到 destination"
        assert result.get("destination") == "北京"
        assert result.get("days") == 3

    def test_no_context_returns_none(self):
        """对话中没有目的地信息时返回 None"""
        from langchain_core.messages import HumanMessage, AIMessage
        from agents.sales_agent import _build_draft_context

        state = {
            "messages": [
                HumanMessage(content="你好"),
                AIMessage(content="你好！有什么可以帮您的？"),
            ],
        }
        result = _build_draft_context(state)
        assert result is None, "没有目的地信息时应该返回 None"
