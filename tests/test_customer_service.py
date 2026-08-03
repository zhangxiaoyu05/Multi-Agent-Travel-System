"""测试客服分支：条件边 + 工具纯逻辑 + 节点函数

不依赖 LLM——测试条件路由逻辑和工具关键词匹配。
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# =============================================================================
# after_service 条件边
# =============================================================================


class TestAfterService:
    """客服后置条件边的三路分发逻辑"""

    def test_need_human_routes_to_handoff(self):
        from graph.conditions.after_service import after_service
        state = {"need_human": True}
        assert after_service(state) == "human_handoff"

    def test_has_reply_routes_to_end(self):
        from graph.conditions.after_service import after_service
        state = {"need_human": False, "final_reply": "这是客服的回复"}
        assert after_service(state) == "end"

    def test_no_reply_reroutes(self):
        from graph.conditions.after_service import after_service
        state = {"need_human": False, "final_reply": ""}
        assert after_service(state) == "intent_router"

    def test_missing_final_reply(self):
        """没有 final_reply 字段 → 重新路由"""
        from graph.conditions.after_service import after_service
        state = {"need_human": False}
        assert after_service(state) == "intent_router"

    def test_need_human_takes_priority_over_reply(self):
        """即使有 final_reply，need_human=True 时依然转人工"""
        from graph.conditions.after_service import after_service
        state = {"need_human": True, "final_reply": "回复内容"}
        assert after_service(state) == "human_handoff"


# =============================================================================
# check_handoff 工具——纯关键词逻辑
# =============================================================================


class TestCheckHandoff:
    """转人工评估工具的关键词匹配"""

    def test_complaint_keyword(self):
        from tools.mock_handoff import check_handoff
        result = check_handoff.invoke({"message": "我要投诉你们"})
        assert "需要转人工" in result

    def test_refund_keyword(self):
        from tools.mock_handoff import check_handoff
        result = check_handoff.invoke({"message": "我要全额退款"})
        assert "需要转人工" in result
        assert "强烈投诉" in result  # 强信号

    def test_strong_signal_leader_keyword(self):
        from tools.mock_handoff import check_handoff
        result = check_handoff.invoke({"message": "找你们领导"})
        assert "需要转人工" in result

    def test_long_message_handoff(self):
        from tools.mock_handoff import check_handoff
        long_msg = "详细的投诉内容" + "x" * 500
        result = check_handoff.invoke({"message": long_msg})
        assert "需要转人工" in result

    def test_normal_question_no_handoff(self):
        from tools.mock_handoff import check_handoff
        result = check_handoff.invoke({"message": "签证需要什么材料"})
        assert "无需转人工" in result

    def test_greeting_no_handoff(self):
        from tools.mock_handoff import check_handoff
        result = check_handoff.invoke({"message": "你好"})
        assert "无需转人工" in result


# =============================================================================
# RAG FAQ 工具测试（关键词兜底路径，不依赖 Milvus）
# =============================================================================


class TestRagFaq:
    """RAG FAQ 工具——关键词匹配兜底逻辑"""

    def test_visa_keyword(self):
        from tools.rag_faq import search_faq
        result = search_faq.invoke({"query": "签证需要什么材料"})
        assert "签证" in result or "护照" in result

    def test_payment_keyword(self):
        from tools.rag_faq import search_faq
        result = search_faq.invoke({"query": "中国支付方式有哪些"})
        assert "微信" in result or "支付宝" in result or "支付" in result

    def test_refund_keyword(self):
        from tools.rag_faq import search_faq
        result = search_faq.invoke({"query": "怎么退改"})
        assert "退改" in result or "取消" in result

    def test_weather_keyword(self):
        from tools.rag_faq import search_faq
        result = search_faq.invoke({"query": "北京天气怎么样"})
        assert "天气" in result or "°C" in result

    def test_english_fallback(self):
        """英文查询应通过 fuzzy_map 匹配到对应中文 FAQ"""
        from tools.rag_faq import search_faq
        result = search_faq.invoke({"query": "visa requirements"})
        assert "签证" in result or "护照" in result

    def test_empty_query(self):
        from tools.rag_faq import search_faq
        result = search_faq.invoke({"query": ""})
        assert "请提供" in result

    def test_no_match_fallback(self):
        from tools.rag_faq import search_faq
        # 新 RAG 管道（双路+RRF）对任何查询都会尝试检索最佳匹配，
        # 这是预期行为——即使无精确匹配也会返回最相关的知识库内容。
        # 验证不会崩溃且返回非空结果即可。
        result = search_faq.invoke({"query": "如何制造一台量子计算机"})
        # 应该返回格式化的知识库内容或兜底消息
        assert len(result) > 0
        assert "参考资料" in result or "感谢您的咨询" in result or "人工" in result

    def test_food_keyword(self):
        from tools.rag_faq import search_faq
        result = search_faq.invoke({"query": "有什么好吃的美食推荐"})
        assert "美食" in result or "推荐" in result


# =============================================================================
# 客服 Agent 节点（Mock LLM）
# =============================================================================


class TestCustomerServiceNode:
    """客服节点——Mock LLM 调用，验证返回结构和字段"""

    @patch("graph.nodes.customer_service.get_customer_service_agent")
    async def test_node_returns_reply(self, mock_get_agent, base_state):
        """节点应返回 final_reply 文本"""
        mock_agent = MagicMock()
        mock_agent.run = AsyncMock(return_value={"final_reply": "您好，这是关于签证的回答...", "need_human": False})
        mock_get_agent.return_value = mock_agent

        from graph.nodes.customer_service import customer_service
        result = await customer_service(base_state)

        assert "final_reply" in result
        assert result["final_reply"] == "您好，这是关于签证的回答..."

    @patch("graph.nodes.customer_service.get_customer_service_agent")
    async def test_node_detects_complaint(self, mock_get_agent, complaint_state):
        """投诉消息应返回 need_human=True"""
        mock_agent = MagicMock()
        mock_agent.run = AsyncMock(return_value={"final_reply": "正在转接人工", "need_human": True})
        mock_get_agent.return_value = mock_agent

        from graph.nodes.customer_service import customer_service
        result = await customer_service(complaint_state)

        assert result["need_human"] is True


# =============================================================================
# 人工接管节点
# =============================================================================


class TestHumanHandoff:
    """人工接管节点——生成交接单"""

    def test_generates_handoff_summary(self, complaint_state):
        from graph.nodes.human_handoff import human_handoff
        complaint_state["current_branch"] = "service"
        complaint_state["intent_scores"] = {"service": 0.9, "sales": 0.0, "operations": 0.0, "planner": 0.1}

        result = human_handoff(complaint_state)

        assert result["need_human"] is True
        assert "final_reply" in result
        # 交接单应包含客户信息
        assert "cust-test-03" in result["final_reply"]

    def test_handoff_with_trip_need(self, planner_state):
        from graph.nodes.human_handoff import human_handoff
        planner_state["need_human"] = True

        result = human_handoff(planner_state)

        assert result["need_human"] is True
        assert "final_reply" in result
        # 交接单应包含出行需求
        assert "西安" in result["final_reply"] or "4" in result["final_reply"]


# =============================================================================
# 操作同步节点
# =============================================================================


class TestOperationsSync:
    """终态写入节点——验证透传逻辑"""

    def test_preserves_final_reply(self):
        from graph.nodes.operations_sync import operations_sync
        state = {"customer_id": "cust-test", "final_reply": "完成回复"}
        result = operations_sync(state)
        assert result["final_reply"] == "完成回复"

    def test_handles_minimal_state(self):
        from graph.nodes.operations_sync import operations_sync
        state = {"customer_id": "unknown"}
        result = operations_sync(state)
        assert "final_reply" in result
