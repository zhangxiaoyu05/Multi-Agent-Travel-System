"""测试意图路由器——节点函数 + 条件边 + IntentResult 模型

Mock LLM 调用，验证路由逻辑的各种场景。
"""

import pytest
from unittest.mock import MagicMock, patch
from pydantic import ValidationError

from graph.nodes.intent_router import intent_router, IntentResult


# =============================================================================
# IntentResult 模型
# =============================================================================


class TestIntentResult:
    """IntentResult Pydantic 模型"""

    def test_valid_result(self):
        r = IntentResult(service=0.8, sales=0.1, operations=0.05, planner=0.05, need_human=False, reasoning="FAQ")
        assert r.service == 0.8
        assert r.planner == 0.05
        assert r.need_human is False

    def test_defaults(self):
        r = IntentResult()
        assert r.service == 0.0
        assert r.sales == 0.0
        assert r.need_human is False
        assert r.reasoning == ""

    def test_out_of_range_score(self):
        """分数超过 1.0 应该被 Pydantic 拒绝"""
        with pytest.raises(ValidationError):
            IntentResult(service=1.5)

    def test_negative_score(self):
        """负数分数应该被 Pydantic 拒绝"""
        with pytest.raises(ValidationError):
            IntentResult(service=-0.1)

    def test_planner_high(self):
        r = IntentResult(service=0.1, sales=0.05, operations=0.05, planner=0.8)
        assert r.planner > r.service
        assert r.planner > r.sales


# =============================================================================
# intent_router 节点——纯逻辑分支（不调 LLM）
# =============================================================================


class TestIntentRouterNode:
    """测试 intent_router 函数在各种边界条件下的行为"""

    def test_empty_messages_returns_default(self):
        """无消息时应返回空 scores，不移交人工"""
        state = {"messages": []}
        result = intent_router(state)
        assert result["intent_scores"] == {}
        assert result["need_human"] is False

    def test_empty_text_returns_service_default(self):
        """空文本消息应兜底到客服"""
        from langchain_core.messages import HumanMessage
        state = {"messages": [HumanMessage(content="")]}
        result = intent_router(state)
        assert result["intent_scores"]["service"] == 0.85
        assert result["intent_scores"]["planner"] == 0.05
        assert result["need_human"] is False

    def test_whitespace_only(self):
        """纯空白消息应兜底到客服"""
        from langchain_core.messages import HumanMessage
        state = {"messages": [HumanMessage(content="   ")]}
        result = intent_router(state)
        assert result["intent_scores"]["service"] == 0.85

    @patch("graph.nodes.intent_router.get_router_llm")
    def test_router_return_keys(self, mock_llm):
        """返回 dict 应包含 intent_scores 和 need_human 两个 key"""
        from langchain_core.messages import HumanMessage

        mock_chain = MagicMock()
        mock_chain.invoke.return_value = IntentResult(
            service=0.1, sales=0.1, operations=0.1, planner=0.7, need_human=False
        )
        mock_llm.return_value.with_structured_output.return_value = mock_chain

        state = {"messages": [HumanMessage(content="帮我规划北京3天行程")]}
        result = intent_router(state)

        assert "intent_scores" in result
        assert "need_human" in result
        assert isinstance(result["intent_scores"], dict)
        assert isinstance(result["need_human"], bool)

    @patch("graph.nodes.intent_router.get_router_llm")
    def test_planner_message_routes_correctly(self, mock_llm):
        """定制意图消息应返回高 planner 分数"""
        from langchain_core.messages import HumanMessage

        mock_chain = MagicMock()
        mock_chain.invoke.return_value = IntentResult(
            service=0.1, sales=0.05, operations=0.05, planner=0.8, need_human=False
        )
        mock_llm.return_value.with_structured_output.return_value = mock_chain

        state = {"messages": [HumanMessage(content="我想去西安玩3天")]}
        result = intent_router(state)

        assert result["intent_scores"]["planner"] > 0.5
        assert result["need_human"] is False

    @patch("graph.nodes.intent_router.get_router_llm")
    def test_complaint_triggers_handoff(self, mock_llm):
        """投诉消息应触发 need_human=True"""
        from langchain_core.messages import HumanMessage

        mock_chain = MagicMock()
        mock_chain.invoke.return_value = IntentResult(
            service=1.0, sales=0.0, operations=0.0, planner=0.0, need_human=True, reasoning="投诉关键词"
        )
        mock_llm.return_value.with_structured_output.return_value = mock_chain

        state = {"messages": [HumanMessage(content="我要投诉！")]}
        result = intent_router(state)

        assert result["need_human"] is True

    @patch("graph.nodes.intent_router.get_router_llm")
    def test_llm_failure_fallsback_to_service(self, mock_llm):
        """LLM 调用异常时应兜底到客服"""
        from langchain_core.messages import HumanMessage

        mock_chain = MagicMock()
        mock_chain.invoke.side_effect = Exception("API timeout")
        mock_llm.return_value.with_structured_output.return_value = mock_chain

        state = {"messages": [HumanMessage(content="任意消息")]}
        result = intent_router(state)

        assert result["intent_scores"]["service"] == 1.0
        assert result["need_human"] is False

    @patch("graph.nodes.intent_router.get_router_llm")
    def test_sales_message_routes_to_sales(self, mock_llm):
        """询价消息应返回高 sales 分数"""
        from langchain_core.messages import HumanMessage

        mock_chain = MagicMock()
        mock_chain.invoke.return_value = IntentResult(
            service=0.1, sales=0.8, operations=0.05, planner=0.05, need_human=False
        )
        mock_llm.return_value.with_structured_output.return_value = mock_chain

        state = {"messages": [HumanMessage(content="三亚5天多少钱？")]}
        result = intent_router(state)

        assert result["intent_scores"]["sales"] > 0.5


# =============================================================================
# route_decision 条件边——纯逻辑，不依赖 LLM
# =============================================================================


class TestRouteDecision:
    """测试路由决策条件边的决策逻辑"""

    def test_need_human_overrides_all(self):
        """无论意图分数如何，need_human=True 时直接转 human_handoff"""
        from graph.conditions.route_decision import route_decision

        state = {
            "need_human": True,
            "intent_scores": {"service": 0.1, "sales": 0.05, "operations": 0.05, "planner": 0.8},
        }
        assert route_decision(state) == "human_handoff"

    def test_highest_score_wins(self):
        """最高分意图对应正确的目标节点"""
        from graph.conditions.route_decision import route_decision

        state = {
            "need_human": False,
            "intent_scores": {"service": 0.1, "sales": 0.05, "operations": 0.05, "planner": 0.8},
        }
        assert route_decision(state) == "trip_planner"

    def test_sales_routing(self):
        from graph.conditions.route_decision import route_decision

        state = {
            "need_human": False,
            "intent_scores": {"service": 0.1, "sales": 0.85, "operations": 0.03, "planner": 0.02},
        }
        assert route_decision(state) == "sales_agent"

    def test_operations_routing(self):
        from graph.conditions.route_decision import route_decision

        state = {
            "need_human": False,
            "intent_scores": {"service": 0.05, "sales": 0.05, "operations": 0.85, "planner": 0.05},
        }
        assert route_decision(state) == "operations_agent"

    def test_low_confidence_fallback(self):
        """所有意图分数 < 0.3 → 兜底到 customer_service"""
        from graph.conditions.route_decision import route_decision

        state = {
            "need_human": False,
            "intent_scores": {"service": 0.2, "sales": 0.1, "operations": 0.1, "planner": 0.25},
        }
        assert route_decision(state) == "customer_service"

    def test_empty_scores_fallback(self):
        """无意图分数时兜底到客服"""
        from graph.conditions.route_decision import route_decision

        state = {"need_human": False, "intent_scores": {}}
        assert route_decision(state) == "customer_service"

    def test_missing_scores_key(self):
        """State 中没有 intent_scores 字段时兜底到客服"""
        from graph.conditions.route_decision import route_decision

        state = {"need_human": False}
        assert route_decision(state) == "customer_service"

    def test_tie_breaker(self):
        """同最高分时 max() 返回第一个遇到的 key（依赖字典迭代顺序）"""
        from graph.conditions.route_decision import route_decision
        # service 和 planner 同分 → 看哪个先被 max() 选到
        state = {
            "need_human": False,
            "intent_scores": {"service": 0.8, "sales": 0.1, "operations": 0.05, "planner": 0.8},
        }
        result = route_decision(state)
        assert result in ("customer_service", "trip_planner")


# =============================================================================
# 行程定制预检（Phase 22 修复：绕过 LLM 惯性误判）
# =============================================================================


class TestTripPlanningPrefilter:
    """验证 _has_trip_planning_intent 正确识别行程定制信号"""

    def test_standalone_destination(self):
        """「我想去拉萨」独立成句应命中"""
        from graph.nodes.intent_router import _has_trip_planning_intent
        assert _has_trip_planning_intent("我想去拉萨") is True
        assert _has_trip_planning_intent("我要去成都") is True
        assert _has_trip_planning_intent("准备去杭州") is True

    def test_destination_with_budget_and_date(self):
        """「我想去拉萨，一个人，预算5000元，8-15到」——多要素强信号应命中"""
        from graph.nodes.intent_router import _has_trip_planning_intent
        assert _has_trip_planning_intent("我想去拉萨，一个人，预算5000元，8-15到") is True

    def test_change_destination(self):
        """「帮我把目的地改为拉萨」应命中"""
        from graph.nodes.intent_router import _has_trip_planning_intent
        assert _has_trip_planning_intent("那帮我把目的地改为拉萨") is True
        assert _has_trip_planning_intent("帮我把目的地换到成都") is True

    def test_explicit_customize(self):
        """「定制」「帮我设计行程」应命中"""
        from graph.nodes.intent_router import _has_trip_planning_intent
        assert _has_trip_planning_intent("定制") is True
        assert _has_trip_planning_intent("帮我设计一个行程") is True
        assert _has_trip_planning_intent("帮我安排一个3天的行程") is True

    def test_destination_with_days(self):
        """「去成都5天」「去拉萨待几天」应命中"""
        from graph.nodes.intent_router import _has_trip_planning_intent
        assert _has_trip_planning_intent("去成都5天") is True
        assert _has_trip_planning_intent("去拉萨待几天") is True

    def test_faq_about_visa_not_planner(self):
        """「我想去拉萨需要什么签证」是 FAQ，不应命中"""
        from graph.nodes.intent_router import _has_trip_planning_intent
        assert _has_trip_planning_intent("我想去拉萨需要什么签证") is False
        assert _has_trip_planning_intent("去拉萨要办边防证吗") is False

    def test_faq_about_process_not_planner(self):
        """「定制流程是什么」「怎样定制行程」是 FAQ，不应命中"""
        from graph.nodes.intent_router import _has_trip_planning_intent
        assert _has_trip_planning_intent("定制流程是什么") is False
        assert _has_trip_planning_intent("怎样定制行程") is False

    def test_greeting_not_planner(self):
        """寒暄不应命中"""
        from graph.nodes.intent_router import _has_trip_planning_intent
        assert _has_trip_planning_intent("你好") is False
        assert _has_trip_planning_intent("你能干什么") is False

    def test_destination_with_how_not_planner(self):
        """「我想去成都怎么走」是 FAQ 问交通，不应命中"""
        from graph.nodes.intent_router import _has_trip_planning_intent
        assert _has_trip_planning_intent("我想去成都怎么走") is False

    def test_prefilter_returns_high_planner_scores(self):
        """预检命中应返回高 planner 分数 + journey_stage=planning"""
        from graph.nodes.intent_router import _prefilter_user_message
        result = _prefilter_user_message("我想去拉萨，一个人，预算5000")
        assert result is not None
        assert result["intent_scores"]["planner"] == 0.85
        assert result["journey_stage"] == "planning"
        assert result["need_human"] is False

    def test_prefilter_non_trip_returns_none(self):
        """非行程消息预检应返回 None（让 LLM 处理）"""
        from graph.nodes.intent_router import _prefilter_user_message
        assert _prefilter_user_message("你好") is not None  # 寒暄拦截
        assert _prefilter_user_message("你能干什么") is not None  # 能力询问拦截
        # 普通消息应返回 None
        result = _prefilter_user_message("今天天气怎么样")
        assert result is None, f"Expected None, got {result}"
