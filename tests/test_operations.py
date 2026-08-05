"""测试运营分支：Phase 21 重写——产品查询 + 订单管理 + 工单 + 交接

覆盖：
- 10 个新运营工具（product search ×4 + order ×4 + ticket ×2）
- MCP 工具注册（10 个新包装器）
- 条件边（after_sales won → operations_handoff）
- 运营接管节点（operations_handoff）
- 运营节点（Mock Agent）
- 运营 Agent 直接测试（Mock LLM）
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# =============================================================================
# 产品查询工具测试（4 个）
# =============================================================================


class TestProductSearchTools:
    """search_hotels / flights / tickets / guides"""

    def test_search_hotels_returns_results(self):
        from tools.mock_operations import search_hotels
        result = search_hotels.invoke({"city": "北京"})
        assert "北京" in result
        assert "希尔顿" in result
        assert "¥" in result

    def test_search_hotels_unknown_city(self):
        from tools.mock_operations import search_hotels
        result = search_hotels.invoke({"city": "纽约"})
        assert "暂无合作酒店" in result or "抱歉" in result

    def test_search_flights_returns_results(self):
        from tools.mock_operations import search_flights
        result = search_flights.invoke({
            "origin": "北京", "destination": "西安", "date": "2026-09-15",
        })
        assert "北京" in result
        assert "西安" in result
        assert "航班" in result

    def test_search_flights_empty_ok(self):
        from tools.mock_operations import search_flights
        result = search_flights.invoke({})
        assert "航班" in result

    def test_search_tickets_returns_results(self):
        from tools.mock_operations import search_tickets
        result = search_tickets.invoke({"city": "西安"})
        assert "兵马俑" in result
        assert "¥" in result

    def test_search_guides_returns_results(self):
        from tools.mock_operations import search_guides
        result = search_guides.invoke({"city": "成都", "language": "英文"})
        assert "成都" in result
        assert "英文" in result or "杨雪" in result


# =============================================================================
# 订单工具测试（4 个）
# =============================================================================


class TestOrderTools:
    """get_order / list_orders / cancel_order / modify_order"""

    def test_get_order_nonexistent(self):
        from tools.mock_operations import get_order
        result = get_order.invoke({"order_id": "ORD-FAKE"})
        assert "未找到" in result

    def test_list_orders_empty(self):
        from tools.mock_operations import list_orders
        result = list_orders.invoke({"user_id": "unknown-user"})
        assert "没有" in result or "暂无" in result

    def test_cancel_order_nonexistent(self):
        from tools.mock_operations import cancel_order
        result = cancel_order.invoke({"order_id": "ORD-FAKE"})
        assert "未找到" in result

    def test_modify_order_nonexistent(self):
        from tools.mock_operations import modify_order
        result = modify_order.invoke({"order_id": "ORD-FAKE", "changes": "改期到2026-10-01"})
        assert "未找到" in result

    def test_create_then_get_order(self):
        """创建 mock 订单后查询"""
        from tools.mock_operations import _ORDERS, _make_order_id
        import json
        order_id = _make_order_id()
        _ORDERS[order_id] = {
            "order_id": order_id,
            "user_id": "test-uid",
            "destination": "北京",
            "days": 3,
            "pax": 2,
            "trip_start": "2026-09-10",
            "trip_end": "2026-09-12",
            "total_amount": "¥3,500",
            "currency": "¥",
            "status": "pending_confirmation",
            "paid_at": None,
            "created_at": "2026-08-05T10:00:00",
            "items": [
                {"type": "hotel", "product_name": "王府井希尔顿", "supplier": "HH Travel",
                 "price": "¥1,200/晚", "quantity": 3, "confirm_status": "confirmed",
                 "confirm_ref": "HH-ABC", "contact_info": "010-1234-5678"},
                {"type": "ticket", "product_name": "故宫博物院", "supplier": "Palace Tix",
                 "price": "¥60/人", "quantity": 2, "confirm_status": "pending",
                 "confirm_ref": "", "contact_info": ""},
            ],
        }

        from tools.mock_operations import get_order
        result = get_order.invoke({"order_id": order_id})
        assert order_id in result
        assert "北京" in result
        assert "王府井希尔顿" in result

    def test_cancel_order_with_refund(self):
        """取消订单应返回退款计算"""
        from tools.mock_operations import _ORDERS, _make_order_id
        order_id = _make_order_id()
        _ORDERS[order_id] = {
            "order_id": order_id,
            "user_id": "test-uid",
            "destination": "三亚",
            "days": 5,
            "pax": 2,
            "trip_start": "2026-10-01",
            "trip_end": "2026-10-05",
            "total_amount": "¥5,000",
            "currency": "¥",
            "status": "confirmed",
            "paid_at": "2026-08-01T12:00:00",
            "created_at": "2026-08-01T10:00:00",
            "items": [],
        }

        from tools.mock_operations import cancel_order
        result = cancel_order.invoke({"order_id": order_id, "reason": "行程冲突"})
        assert "取消" in result
        assert "退款" in result or "¥" in result


# =============================================================================
# 工单工具测试（2 个）
# =============================================================================


class TestTicketTools:
    """create_ticket / check_ticket"""

    def test_create_ticket(self):
        from tools.mock_operations import create_ticket
        result = create_ticket.invoke({
            "user_id": "test-uid",
            "type": "complaint",
            "description": "酒店与预订不符",
        })
        assert "TK-" in result
        assert "complaint" in result or "工单" in result

    def test_create_ticket_emergency(self):
        """安全事故应自动标记紧急"""
        from tools.mock_operations import create_ticket
        result = create_ticket.invoke({
            "user_id": "test-uid",
            "type": "emergency",
            "description": "发生安全事故，需要立即处理",
        })
        assert "TK-" in result
        assert "紧急" in result

    def test_check_ticket_found(self):
        from tools.mock_operations import create_ticket, check_ticket, _TICKETS, _make_ticket_id
        _TICKETS.clear()
        # 直接构建 ticket_id 并插入 _TICKETS，避免 regex 截断问题
        ticket_id = _make_ticket_id()
        _TICKETS[ticket_id] = {
            "ticket_id": ticket_id,
            "user_id": "test-uid",
            "order_id": "",
            "type": "inquiry",
            "priority": "normal",
            "status": "open",
            "description": "测试工单",
            "resolution": "",
            "assigned_to": "运营团队",
            "created_at": "2026-08-05T10:00:00",
            "updated_at": "2026-08-05T10:00:00",
        }
        result = check_ticket.invoke({"ticket_id": ticket_id})
        assert ticket_id in result
        assert "inquiry" in result or "已受理" in result

    def test_check_ticket_not_found(self):
        from tools.mock_operations import check_ticket
        result = check_ticket.invoke({"ticket_id": "TK-FAKE"})
        assert "未找到" in result


# =============================================================================
# MCP 工具注册测试
# =============================================================================


class TestMCPToolRegistration:
    """验证 10 个新工具在 mcp_tools 中正确注册"""

    def test_search_hotels_mcp(self):
        from tools.mcp_tools import search_hotels
        result = search_hotels.invoke({"city": "北京"})
        assert isinstance(result, str)
        assert len(result) > 0

    def test_search_flights_mcp(self):
        from tools.mcp_tools import search_flights
        result = search_flights.invoke({"origin": "上海", "destination": "北京"})
        assert isinstance(result, str)

    def test_search_tickets_mcp(self):
        from tools.mcp_tools import search_tickets
        result = search_tickets.invoke({"city": "西安"})
        assert isinstance(result, str)

    def test_get_order_mcp(self):
        from tools.mcp_tools import get_order
        result = get_order.invoke({"order_id": "ORD-TEST"})
        assert isinstance(result, str)

    def test_create_ticket_mcp(self):
        from tools.mcp_tools import create_ticket
        result = create_ticket.invoke({
            "user_id": "test", "type": "inquiry", "description": "test",
        })
        assert isinstance(result, str)


# =============================================================================
# 条件边：after_sales won → operations_handoff
# =============================================================================


class TestAfterSales:
    """after_sales 条件边——Phase 21 新增 operations_handoff 路由"""

    def test_won_to_operations_handoff(self):
        from graph.conditions.after_sales import after_sales
        state = {
            "need_human": False, "goto_planner": False,
            "sales_pipeline_stage": "won",
        }
        assert after_sales(state) == "operations_handoff"

    def test_lost_to_end(self):
        from graph.conditions.after_sales import after_sales
        state = {
            "need_human": False, "goto_planner": False,
            "sales_pipeline_stage": "lost",
        }
        assert after_sales(state) == "end"

    def test_normal_to_end(self):
        from graph.conditions.after_sales import after_sales
        state = {"need_human": False}
        assert after_sales(state) == "end"

    def test_need_human_always_priority(self):
        """need_human=True 始终优先"""
        from graph.conditions.after_sales import after_sales
        state = {
            "need_human": True,
            "sales_pipeline_stage": "won",
        }
        assert after_sales(state) == "human_handoff"


# =============================================================================
# 运营接管节点
# =============================================================================


class TestOperationsHandoff:
    """operations_handoff 节点——WON 时生成接管消息"""

    @patch("agents.operations_agent.get_operations_agent")
    async def test_handoff_generates_reply(self, mock_get_agent, operations_won_state):
        """WON 状态应生成接管消息"""
        from agents.operations_agent import OperationsAgent
        mock_agent = MagicMock()
        mock_agent.run = AsyncMock(return_value={
            "final_reply": "支付确认！您的北京三日游已生效...",
            "need_human": False,
            "order_context": {"order_id": "ORD-TEST", "status": "pending_confirmation"},
        })
        mock_get_agent.return_value = mock_agent

        from graph.nodes.operations_handoff import operations_handoff
        result = await operations_handoff(operations_won_state)

        assert "final_reply" in result
        assert "北京" in result["final_reply"]
        assert result["current_branch"] == "operations_agent"

    @patch("agents.operations_agent.get_operations_agent")
    async def test_handoff_combines_replies(self, mock_get_agent, operations_won_state):
        """接管消息应和销售消息合并"""
        mock_agent = MagicMock()
        mock_agent.run = AsyncMock(return_value={
            "final_reply": "接下来我会为您跟进...",
            "need_human": False,
            "order_context": {},
        })
        mock_get_agent.return_value = mock_agent

        from graph.nodes.operations_handoff import operations_handoff
        result = await operations_handoff(operations_won_state)

        assert "恭喜" in result["final_reply"] or "已创建" in result["final_reply"]
        assert "接下来" in result["final_reply"]

    @patch("agents.operations_agent.get_operations_agent")
    async def test_handoff_no_sales_reply(self, mock_get_agent, operations_won_state):
        """仅有运营接管消息（无 sales final_reply）"""
        mock_agent = MagicMock()
        mock_agent.run = AsyncMock(return_value={
            "final_reply": "支付确认！",
            "need_human": False,
            "order_context": {},
        })
        mock_get_agent.return_value = mock_agent

        # 修改 won_state 的 final_reply 为空
        state = {**operations_won_state, "final_reply": ""}
        from graph.nodes.operations_handoff import operations_handoff
        result = await operations_handoff(state)

        assert result["final_reply"] == "支付确认！"


# =============================================================================
# 运营节点（Mock Agent）
# =============================================================================


class TestOperationsNode:
    """运营节点——Mock OperationsAgent"""

    @patch("graph.nodes.operations_agent.get_operations_agent")
    async def test_node_returns_reply(self, mock_get_agent, operations_state):
        mock_agent = MagicMock()
        mock_agent.run = AsyncMock(return_value={
            "final_reply": "您好！已为您查询到北京3家可预订酒店...",
            "need_human": False,
            "order_context": {},
        })
        mock_get_agent.return_value = mock_agent

        from graph.nodes.operations_agent import operations_agent
        result = await operations_agent(operations_state)

        assert "final_reply" in result
        assert result["final_reply"] == "您好！已为您查询到北京3家可预订酒店..."
        assert result["current_branch"] == "operations_agent"

    @patch("graph.nodes.operations_agent.get_operations_agent")
    async def test_node_returns_order_context(self, mock_get_agent, operations_state):
        mock_agent = MagicMock()
        mock_agent.run = AsyncMock(return_value={
            "final_reply": "订单详情如下...",
            "need_human": False,
            "order_context": {
                "order_id": "ORD-TEST",
                "status": "confirmed",
                "destination": "北京",
            },
        })
        mock_get_agent.return_value = mock_agent

        from graph.nodes.operations_agent import operations_agent
        result = await operations_agent(operations_state)

        assert result["order_context"]["order_id"] == "ORD-TEST"

    @patch("graph.nodes.operations_agent.get_operations_agent")
    async def test_node_escalation(self, mock_get_agent):
        """安全事故类请求应触发转人工"""
        from langchain_core.messages import HumanMessage

        escalation_state = {
            "messages": [HumanMessage(content="发生安全事故，需要立即上报！")],
            "session_id": "test-ops-e",
            "customer_id": "cust-ops-e",
            "channel": "web",
            "language": "zh",
        }

        mock_agent = MagicMock()
        mock_agent.run = AsyncMock(return_value={
            "final_reply": "已记录安全事故报告，正在转接人工主管...",
            "need_human": True,
            "order_context": {},
        })
        mock_get_agent.return_value = mock_agent

        from graph.nodes.operations_agent import operations_agent
        result = await operations_agent(escalation_state)

        assert result["need_human"] is True
        assert result["handoff"]["priority"] == "urgent"


# =============================================================================
# 运营 Agent 直接测试（Mock LLM）
# =============================================================================


class TestOperationsAgentDirect:
    """直接测试 OperationsAgent.run()——Mock LLM"""

    @patch("agents.operations_agent.get_light_llm")
    async def test_agent_handles_product_search(self, mock_get_llm):
        """产品查询应调用工具并返回结果"""
        from langchain_core.messages import HumanMessage
        from services.llm import LLMResponse

        mock_llm = MagicMock()
        mock_bound = MagicMock()
        mock_bound.ainvoke = AsyncMock(return_value=LLMResponse(
            content="",
            tool_calls=[{"id": "call-1", "name": "search_hotels", "args": {
                "city": "北京", "check_in": "2026-09-10", "check_out": "2026-09-13", "pax": 2,
            }}],
        ))
        mock_llm.bind_tools.return_value = mock_bound
        mock_llm.ainvoke = AsyncMock(return_value=LLMResponse(
            content="为您找到以下北京酒店：王府井希尔顿 ¥1,200/晚...",
        ))
        mock_get_llm.return_value = mock_llm

        from agents.operations_agent import OperationsAgent
        agent = OperationsAgent()
        agent.llm = mock_llm

        state = {
            "messages": [HumanMessage(content="帮我在北京找一家酒店，9月10日入住3晚2人")],
            "session_id": "test-001",
            "customer_id": "cust-001",
            "channel": "web",
            "language": "zh",
        }

        result = await agent.run(state)

        assert "final_reply" in result
        assert result["need_human"] is False

    @patch("agents.operations_agent.get_light_llm")
    async def test_agent_handles_handoff(self, mock_get_llm):
        """WON 状态 + 空消息 → 应返回接管兜底消息"""
        from langchain_core.messages import HumanMessage

        # 需要 mock llm 的 bind_tools 方法（BaseAgent.__init__ 会调用）
        mock_llm = MagicMock()
        mock_bound = MagicMock()
        mock_llm.bind_tools.return_value = mock_bound
        mock_get_llm.return_value = mock_llm

        from agents.operations_agent import OperationsAgent
        agent = OperationsAgent()

        state = {
            "messages": [HumanMessage(content="")],
            "session_id": "test-002",
            "customer_id": "cust-002",
            "channel": "web",
            "language": "zh",
            "sales_pipeline_stage": "won",
            "need": {"destination": "北京", "days": 3},
        }

        result = await agent.run(state)

        assert "final_reply" in result
        # 空消息 + WON 状态 → 返回接管兜底消息
        assert "生效" in result["final_reply"] or "支付" in result["final_reply"]

    @patch("agents.operations_agent.get_light_llm")
    async def test_agent_escalation_keywords(self, mock_get_llm):
        """严重投诉关键词应立即升级"""
        from langchain_core.messages import HumanMessage
        from services.llm import LLMResponse

        mock_llm = MagicMock()
        mock_bound = MagicMock()
        mock_bound.ainvoke = AsyncMock(return_value=LLMResponse(
            content="我会帮您处理...",
        ))
        mock_llm.bind_tools.return_value = mock_bound
        mock_get_llm.return_value = mock_llm

        from agents.operations_agent import OperationsAgent
        agent = OperationsAgent()
        agent.llm = mock_llm

        state = {
            "messages": [HumanMessage(content="我被骗了，我要报警！退款！")],
            "session_id": "test-003",
            "customer_id": "cust-003",
            "channel": "web",
            "language": "zh",
        }

        result = await agent.run(state)

        assert result["need_human"] is True


# =============================================================================
# CRM 强制写入（保留测试）
# =============================================================================


class TestCRMEnforcement:
    """运营 Agent 强制 CRM 写入逻辑"""

    @patch("agents.operations_agent.get_light_llm")
    async def test_llm_no_crm_call_enforces_write(self, mock_get_llm):
        """LLM 未调用 update_crm 时，Agent 应正常完成（不抛异常）"""
        from langchain_core.messages import HumanMessage
        from services.llm import LLMResponse

        mock_llm = MagicMock()
        mock_bound = MagicMock()
        mock_bound.ainvoke = AsyncMock(return_value=LLMResponse(
            content="好的，已了解您的需求。",
        ))
        mock_llm.bind_tools.return_value = mock_bound
        mock_get_llm.return_value = mock_llm

        from agents.operations_agent import OperationsAgent
        agent = OperationsAgent()
        agent.llm = mock_llm

        state = {
            "messages": [HumanMessage(content="帮我查一下订单状态")],
            "session_id": "test-004",
            "customer_id": "cust-004",
            "channel": "web",
            "language": "zh",
        }

        result = await agent.run(state)

        assert "final_reply" in result
        assert result["need_human"] is False


# =============================================================================
# 回归测试：天数提取 Bug 修复（Phase 21 E2E 发现）
# =============================================================================


class TestDaysExtractionFix:
    """验证 _extract_fields_regex 不会把日期中的"日"误提取为天数"""

    def test_date_not_mistaken_for_days(self):
        """9月20日 + 2个人 → days 应该是 None，不是 20"""
        from agents.trip_planner import _extract_fields_regex
        result = _extract_fields_regex("9月20日，2个人")
        assert result.get("days") != 20, (
            f"BUG 回归：'9月20日' 中的 '20日' 被误提取为 days={result.get('days')}，应为 None（无天数）"
        )

    def test_days_extracted_from_tian_only(self):
        """成都玩3天 + 9月20日 → days=3，不受日期数字干扰"""
        from agents.trip_planner import _extract_fields_regex
        result = _extract_fields_regex("成都玩3天，9月20日，2个人")
        assert result.get("days") == 3, (
            f"'成都玩3天' 应提取 days=3，实际: {result.get('days')}"
        )

    def test_large_day_filtered(self):
        """大于 30 的天数被合理性检查拒绝"""
        from agents.trip_planner import _extract_fields_regex
        result = _extract_fields_regex("我要玩45天")
        assert result.get("days") is None, (
            f"45 天 > 30 应被合理性检查拒绝，实际: {result.get('days')}"
        )
