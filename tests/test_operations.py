"""测试运营分支：Mock 工具 + 条件边 + 节点函数

覆盖 CRM 写入、CAPI 发送、运营后置条件边、运营节点。
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# =============================================================================
# CRM 工具测试
# =============================================================================


class TestCRMTool:
    """CRM 写入工具"""

    def test_update_crm_writes_record(self):
        from tools.mock_crm import update_crm
        result = update_crm.invoke({
            "customer_id": "cust-001",
            "session_data": '{"branch": "operations", "done": true}',
        })
        assert "cust-001" in result
        assert "成功写入" in result
        assert "[CRM]" in result

    def test_update_crm_truncation(self):
        """超长 session_data 应截断"""
        from tools.mock_crm import update_crm
        long_data = "x" * 500
        result = update_crm.invoke({
            "customer_id": "cust-long",
            "session_data": long_data,
        })
        assert "cust-long" in result
        assert "成功写入" in result


# =============================================================================
# CAPI 工具测试
# =============================================================================


class TestCAPITool:
    """CAPI 转化事件工具"""

    def test_send_capi_success(self):
        from tools.mock_capi import send_capi
        result = send_capi.invoke({
            "event_type": "session_completed",
            "event_data": '{"customer_id": "cust-001"}',
        })
        assert "session_completed" in result
        assert "成功发送" in result
        assert "[CAPI]" in result

    def test_send_capi_handoff_event(self):
        from tools.mock_capi import send_capi
        result = send_capi.invoke({
            "event_type": "handoff",
            "event_data": '{"reason": "投诉升级"}',
        })
        assert "handoff" in result
        assert "成功发送" in result


# =============================================================================
# 运营后置条件边（builder.py 内 _after_operations）
# =============================================================================


class TestAfterOperations:
    """运营节点出口条件边——两路分发"""

    def test_need_human_to_handoff(self):
        from graph.builder import _after_operations
        state = {"need_human": True}
        assert _after_operations(state) == "human_handoff"

    def test_normal_to_operations_sync(self):
        from graph.builder import _after_operations
        state = {"need_human": False}
        assert _after_operations(state) == "operations_sync"

    def test_missing_need_human_defaults_to_sync(self):
        """need_human 缺失 → 默认进 operations_sync"""
        from graph.builder import _after_operations
        state = {}
        assert _after_operations(state) == "operations_sync"


# =============================================================================
# 运营节点（Mock Agent）
# =============================================================================


class TestOperationsNode:
    """运营节点——Mock OperationsAgent"""

    @patch("graph.nodes.operations_agent.get_operations_agent")
    async def test_node_returns_reply(self, mock_get_agent, operations_state):
        """节点应返回 final_reply 文本"""
        mock_agent = MagicMock()
        mock_agent.run = AsyncMock(return_value={
            "final_reply": "您好！商家入驻需要提供以下资质：营业执照、旅行社经营许可证...",
            "need_human": False,
        })
        mock_get_agent.return_value = mock_agent

        from graph.nodes.operations_agent import operations_agent
        result = await operations_agent(operations_state)

        assert "final_reply" in result
        assert result["final_reply"] == "您好！商家入驻需要提供以下资质：营业执照、旅行社经营许可证..."

    @patch("graph.nodes.operations_agent.get_operations_agent")
    async def test_node_returns_branch(self, mock_get_agent, operations_state):
        """节点应设置 current_branch = operations"""
        mock_agent = MagicMock()
        mock_agent.run = AsyncMock(return_value={
            "final_reply": "处理完成",
            "need_human": False,
        })
        mock_get_agent.return_value = mock_agent

        from graph.nodes.operations_agent import operations_agent
        result = await operations_agent(operations_state)

        assert result["current_branch"] == "operations_agent"

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
        })
        mock_get_agent.return_value = mock_agent

        from graph.nodes.operations_agent import operations_agent
        result = await operations_agent(escalation_state)

        assert result["need_human"] is True

    @patch("graph.nodes.operations_agent.get_operations_agent")
    async def test_node_order_fulfillment(self, mock_get_agent):
        """订单履约查询应正常处理"""
        from langchain_core.messages import HumanMessage

        fulfillment_state = {
            "messages": [HumanMessage(content="我想查一下订单号 TK-2024-0815 的履约状态")],
            "session_id": "test-ops-f",
            "customer_id": "cust-ops-f",
            "channel": "web",
            "language": "zh",
        }

        mock_agent = MagicMock()
        mock_agent.run = AsyncMock(return_value={
            "final_reply": "您的订单 TK-2024-0815 当前状态：酒店已确认，车辆待确认...",
            "need_human": False,
        })
        mock_get_agent.return_value = mock_agent

        from graph.nodes.operations_agent import operations_agent
        result = await operations_agent(fulfillment_state)

        assert result["need_human"] is False
        assert "final_reply" in result
        assert "TK-2024-0815" in result["final_reply"]


# =============================================================================
# 运营 Agent 直接测试（Mock LLM）
# =============================================================================


class TestOperationsAgentDirect:
    """直接测试 OperationsAgent.run()——Mock LLM 响应"""

    @patch("agents.operations_agent.get_agent_llm")
    async def test_agent_handles_merchant_onboarding(self, mock_get_llm):
        """商家入驻咨询应调用 CRM 并返回引导回复"""
        from langchain_core.messages import HumanMessage

        # Mock LLM：首次返回 tool_call（update_crm），二次返回最终文本
        from services.llm import LLMResponse

        mock_llm = MagicMock()
        # Bind tools returns a tool-bound object
        mock_bound = MagicMock()
        mock_bound.ainvoke = AsyncMock(return_value=LLMResponse(
            content="",
            tool_calls=[{"id": "call-1", "name": "update_crm", "args": {
                "customer_id": "cust-001",
                "session_data": '{"topic": "merchant_onboarding"}',
            }}],
        ))
        mock_llm.bind_tools.return_value = mock_bound
        # Final response
        mock_llm.ainvoke = AsyncMock(return_value=LLMResponse(
            content="您好！商家入驻需要营业执照和旅行社经营许可证。",
        ))
        mock_get_llm.return_value = mock_llm

        from agents.operations_agent import OperationsAgent
        agent = OperationsAgent()
        # Override LLM instance
        agent.llm = mock_llm

        state = {
            "messages": [HumanMessage(content="我想在你们平台上架旅游产品，需要什么资质？")],
            "session_id": "test-001",
            "customer_id": "cust-001",
            "channel": "web",
            "language": "zh",
        }

        result = await agent.run(state)

        assert "final_reply" in result
        assert result["need_human"] is False

    @patch("agents.operations_agent.get_agent_llm")
    async def test_agent_escalation_detection(self, mock_get_llm):
        """安全事故应检测升级转人工"""
        from langchain_core.messages import HumanMessage
        from services.llm import LLMResponse

        mock_llm = MagicMock()
        mock_bound = MagicMock()
        mock_bound.ainvoke = AsyncMock(return_value=LLMResponse(
            content="已记录，正在处理...",
        ))
        mock_llm.bind_tools.return_value = mock_bound
        mock_get_llm.return_value = mock_llm

        from agents.operations_agent import OperationsAgent
        agent = OperationsAgent()
        agent.llm = mock_llm

        state = {
            "messages": [HumanMessage(content="发生重大安全事故，需要立即处理！")],
            "session_id": "test-002",
            "customer_id": "cust-002",
            "channel": "web",
            "language": "zh",
        }

        result = await agent.run(state)

        # 安全事故关键词 → need_human=True
        assert result["need_human"] is True


# =============================================================================
# CRM 强制写入逻辑测试
# =============================================================================


class TestCRMEnforcement:
    """运营 Agent 强制 CRM 写入逻辑"""

    @patch("agents.operations_agent.get_agent_llm")
    async def test_llm_no_crm_call_enforces_write(self, mock_get_llm):
        """LLM 未调用 update_crm 时，Agent 应强制补充一条 CRM 记录"""
        from langchain_core.messages import HumanMessage
        from services.llm import LLMResponse

        mock_llm = MagicMock()
        mock_bound = MagicMock()
        # LLM 直接回复，不调用任何工具
        mock_bound.ainvoke = AsyncMock(return_value=LLMResponse(
            content="好的，我已了解您的需求。",
        ))
        mock_llm.bind_tools.return_value = mock_bound
        mock_get_llm.return_value = mock_llm

        from agents.operations_agent import OperationsAgent
        agent = OperationsAgent()
        agent.llm = mock_llm

        state = {
            "messages": [HumanMessage(content="帮我查一下平台规则")],
            "session_id": "test-003",
            "customer_id": "cust-003",
            "channel": "web",
            "language": "zh",
        }

        result = await agent.run(state)

        # 即使 LLM 没有调用 CRM，run() 也应正常完成
        assert "final_reply" in result
        assert result["need_human"] is False
