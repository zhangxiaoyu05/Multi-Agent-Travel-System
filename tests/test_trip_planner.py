"""测试定制 Agent 分支：条件边 + Mock 工具 + 节点函数

覆盖需求检查、修订决策、天气/日历/库存工具。
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# =============================================================================
# requirements_complete 条件边
# =============================================================================


class TestRequirementsComplete:
    """必填项检查条件边"""

    def test_all_filled_with_draft(self):
        """必填项齐全 + 有草案 → intent_scorer"""
        from graph.conditions.requirements_complete import requirements_complete

        state = {
            "need": {
                "destination": "西安",
                "days": 4,
                "arrival_date": "2026-08-20",
                "pax": 2,
                "budget": "$1500",
            },
            "draft": {"version": 1, "itinerary_md": "# 行程..."},
        }
        assert requirements_complete(state) == "intent_scorer"

    def test_missing_budget(self):
        """缺少一项必填 → end（等待下一轮）"""
        from graph.conditions.requirements_complete import requirements_complete

        state = {
            "need": {
                "destination": "西安",
                "days": 4,
                "arrival_date": "2026-08-20",
                "pax": 2,
                # budget 缺失
            },
        }
        assert requirements_complete(state) == "end"

    def test_filled_but_no_draft(self):
        """必填齐全但无草案 → end"""
        from graph.conditions.requirements_complete import requirements_complete

        state = {
            "need": {
                "destination": "西安",
                "days": 4,
                "arrival_date": "2026-08-20",
                "pax": 2,
                "budget": "$1500",
            },
            "draft": {},
        }
        assert requirements_complete(state) == "end"

    def test_empty_need(self):
        from graph.conditions.requirements_complete import requirements_complete
        state = {"need": {}, "draft": {}}
        assert requirements_complete(state) == "end"

    def test_missing_state_keys(self):
        """State 中完全没有 need/draft → end"""
        from graph.conditions.requirements_complete import requirements_complete
        state = {}
        assert requirements_complete(state) == "end"

    def test_partial_destination_only(self):
        """只提供了目的地 → end"""
        from graph.conditions.requirements_complete import requirements_complete
        state = {
            "need": {"destination": "北京"},
            "draft": {},
        }
        assert requirements_complete(state) == "end"


# =============================================================================
# revision_decision 条件边
# =============================================================================


class TestRevisionDecision:
    """修订决策条件边——三路分发"""

    def test_high_intent_to_sync(self):
        from graph.conditions.revision_decision import revision_decision
        state = {"intent_level": "high", "next_action": "revise", "revision_count": 0}
        assert revision_decision(state) == "operations_sync"

    def test_accept_to_sync(self):
        from graph.conditions.revision_decision import revision_decision
        state = {"intent_level": "mid", "next_action": "accept", "revision_count": 1}
        assert revision_decision(state) == "operations_sync"

    def test_revise_within_limit(self):
        from graph.conditions.revision_decision import revision_decision
        state = {"intent_level": "mid", "next_action": "revise", "revision_count": 0}
        assert revision_decision(state) == "revision_loop"

    def test_revise_at_limit(self):
        """修订次数 = 3 → 超限转人工"""
        from graph.conditions.revision_decision import revision_decision
        state = {"intent_level": "mid", "next_action": "revise", "revision_count": 3}
        assert revision_decision(state) == "human_handoff"

    def test_revise_exceeded_limit(self):
        """修订次数 > 3 → 转人工"""
        from graph.conditions.revision_decision import revision_decision
        state = {"intent_level": "mid", "next_action": "revise", "revision_count": 5}
        assert revision_decision(state) == "human_handoff"

    def test_give_up_to_handoff(self):
        from graph.conditions.revision_decision import revision_decision
        state = {"intent_level": "low", "next_action": "give_up", "revision_count": 0}
        assert revision_decision(state) == "human_handoff"

    def test_defaults_accept(self):
        """无 intent_level/next_action → 默认 accept → operations_sync"""
        from graph.conditions.revision_decision import revision_decision
        state = {}
        assert revision_decision(state) == "operations_sync"


# =============================================================================
# Mock 天气工具
# =============================================================================


class TestWeatherTool:
    """天气查询工具——验证已知城市的返回数据"""

    def test_beijing(self):
        from tools.mock_weather import get_weather
        result = get_weather.invoke({"city": "北京", "date": "2026-08-15"})
        assert "北京" in result
        assert "2026-08-15" in result
        assert "°C" in result

    def test_xian(self):
        from tools.mock_weather import get_weather
        result = get_weather.invoke({"city": "西安", "date": "2026-08-20"})
        assert "西安" in result
        assert "防晒" in result  # 西安特殊的备注

    def test_unknown_city(self):
        """未知城市返回通用天气预报"""
        from tools.mock_weather import get_weather
        result = get_weather.invoke({"city": "火星", "date": "2026-09-01"})
        assert "暂无精确数据" in result
        assert "°C" in result  # 仍有通用数据

    def test_all_known_cities(self):
        """所有 12 个已知城市都应返回非通用数据"""
        from tools.mock_weather import get_weather

        known = ["北京", "西安", "上海", "成都", "广州", "桂林",
                 "杭州", "重庆", "昆明", "拉萨", "哈尔滨", "三亚"]
        for city in known:
            result = get_weather.invoke({"city": city, "date": "2026-08-01"})
            assert "暂无精确数据" not in result, f"城市 '{city}' 应返回精确天气数据"


# =============================================================================
# Mock 日历工具
# =============================================================================


class TestCalendarTool:
    """日历查询工具"""

    def test_returns_date_info(self):
        from tools.mock_calendar import query_calendar
        result = query_calendar.invoke({"date": "2026-08-15"})
        assert "2026-08-15" in result

    def test_returns_crowd_info(self):
        from tools.mock_calendar import query_calendar
        result = query_calendar.invoke({"date": "2026-08-15"})
        assert "人流量" in result


# =============================================================================
# Mock 库存工具
# =============================================================================


class TestInventoryTool:
    """库存查询工具"""

    def test_basic_query(self):
        from tools.mock_inventory import query_inventory
        result = query_inventory.invoke({"city": "西安", "date": "2026-08-20", "pax": 2})
        assert "西安" in result
        assert "2026-08-20" in result
        assert "2" in result  # 人数

    def test_returns_availability(self):
        from tools.mock_inventory import query_inventory
        result = query_inventory.invoke({"city": "北京", "date": "2026-09-01", "pax": 4})
        assert "酒店" in result or "门票" in result or "车辆" in result


# =============================================================================
# 定制节点（Mock Agent）
# =============================================================================


class TestTripPlannerNode:
    """定制节点——Mock TripPlannerAgent"""

    @patch("graph.nodes.trip_planner.get_trip_planner_agent")
    async def test_node_calls_agent(self, mock_get_agent, planner_state):
        """节点应调用 Agent.run() 并返回结果"""
        mock_agent = MagicMock()
        mock_agent.run = AsyncMock(return_value={
            "final_reply": "已为您生成西安四日游行程",
            "need": planner_state["need"],
            "draft": {"version": 1, "itinerary_md": "# 西安四日游..."},
        })
        mock_get_agent.return_value = mock_agent

        from graph.nodes.trip_planner import trip_planner
        result = await trip_planner(planner_state)

        mock_agent.run.assert_called_once()
        assert "final_reply" in result

    @patch("graph.nodes.trip_planner.get_trip_planner_agent")
    async def test_node_returns_need_and_draft(self, mock_get_agent, planner_state):
        """成功生成后应同时返回 need 和 draft"""
        mock_agent = MagicMock()
        mock_agent.run = AsyncMock(return_value={
            "final_reply": "行程已生成",
            "need": planner_state["need"],
            "draft": {"version": 1, "itinerary_md": "# 行程"},
        })
        mock_get_agent.return_value = mock_agent

        from graph.nodes.trip_planner import trip_planner
        result = await trip_planner(planner_state)

        assert "need" in result
        assert "draft" in result


# =============================================================================
# 修订计数器节点
# =============================================================================


class TestRevisionLoop:
    """修订计数器——纯逻辑"""

    def test_increment_from_zero(self):
        from graph.nodes.revision_loop import revision_loop
        state = {"revision_count": 0}
        result = revision_loop(state)
        assert result["revision_count"] == 1

    def test_increment_from_two(self):
        from graph.nodes.revision_loop import revision_loop
        state = {"revision_count": 2}
        result = revision_loop(state)
        assert result["revision_count"] == 3

    def test_default_start_count(self):
        """没有 revision_count 时从 0 开始"""
        from graph.nodes.revision_loop import revision_loop
        state = {}
        result = revision_loop(state)
        assert result["revision_count"] == 1


# =============================================================================
# 意向评分节点
# =============================================================================


class TestIntentScorer:
    """意向评分节点——Mock LLM"""

    @patch("graph.nodes.intent_scorer.get_router_llm")
    def test_returns_level_and_action(self, mock_llm, state_with_draft):
        from langchain_core.messages import HumanMessage
        state_with_draft["messages"] = [HumanMessage(content="行程不错，就按这个来吧")]

        mock_chain = MagicMock()
        mock_result = type("ScorerResult", (), {
            "intent_level": "high",
            "next_action": "accept",
            "reasoning": "客户满意",
        })
        mock_chain.invoke.return_value = mock_result
        mock_llm.return_value.with_structured_output.return_value = mock_chain

        from graph.nodes.intent_scorer import intent_scorer
        result = intent_scorer(state_with_draft)

        assert result["intent_level"] == "high"
        assert result["next_action"] == "accept"

    @patch("graph.nodes.intent_scorer.get_router_llm")
    def test_llm_failure_fallback(self, mock_llm, state_with_draft):
        """LLM 调用异常应兜底到 high + accept（正常结束）"""
        mock_chain = MagicMock()
        mock_chain.invoke.side_effect = Exception("timeout")
        mock_llm.return_value.with_structured_output.return_value = mock_chain

        from graph.nodes.intent_scorer import intent_scorer
        result = intent_scorer(state_with_draft)

        assert result["intent_level"] == "high"
        assert result["next_action"] == "accept"


# =============================================================================
# 入参保护节点
# =============================================================================


class TestInputGuard:
    """入参保护——纯逻辑测试"""

    def test_normal_message_passes(self, base_state):
        from graph.nodes.input_guard import input_guard
        result = input_guard(base_state)
        msgs = result["messages"]
        assert msgs[0].content == "你好"

    def test_phone_number_masked(self):
        from langchain_core.messages import HumanMessage
        from graph.nodes.input_guard import input_guard

        state = {"messages": [HumanMessage(content="联系我 13912345678 谢谢")]}
        result = input_guard(state)
        assert "13912345678" not in result["messages"][-1].content
        assert "[PHONE]" in result["messages"][-1].content

    def test_long_message_truncated(self):
        from langchain_core.messages import HumanMessage
        from graph.nodes.input_guard import input_guard

        long_text = "长文本" * 1500  # ~6000 chars
        state = {"messages": [HumanMessage(content=long_text)]}
        result = input_guard(state)
        assert len(result["messages"][-1].content) <= 4003  # 4000 + "..."
        assert result["messages"][-1].content.endswith("...")

    def test_empty_messages(self):
        from graph.nodes.input_guard import input_guard
        state = {"messages": []}
        result = input_guard(state)
        assert result == {}


# =============================================================================
# 会话初始化节点
# =============================================================================


class TestSessionContext:
    """会话初始化——纯逻辑"""

    def test_sets_defaults(self):
        from graph.nodes.session_context import session_context
        state = {}
        result = session_context(state)
        assert result["language"] == "zh"
        assert result["need_human"] is False
        assert result["revision_count"] == 0
        assert result["need"] == {}
        assert result["draft"] == {}

    def test_preserves_existing_values(self):
        from graph.nodes.session_context import session_context
        state = {"language": "en", "revision_count": 2}
        result = session_context(state)
        assert result["language"] == "en"
        assert result["revision_count"] == 2  # 保留已有值


# =============================================================================
# 销售条件边
# =============================================================================


class TestAfterSales:
    """销售后置条件边"""

    def test_need_human_to_handoff(self):
        from graph.conditions.after_sales import after_sales
        state = {"need_human": True}
        assert after_sales(state) == "human_handoff"

    def test_high_intent_to_sync(self):
        from graph.conditions.after_sales import after_sales
        state = {"need_human": False, "intent_level": "high"}
        assert after_sales(state) == "operations_sync"

    def test_accept_to_sync(self):
        from graph.conditions.after_sales import after_sales
        state = {"need_human": False, "intent_level": "mid", "next_action": "accept"}
        assert after_sales(state) == "operations_sync"

    def test_low_intent_to_end(self):
        from graph.conditions.after_sales import after_sales
        state = {"need_human": False, "intent_level": "low"}
        assert after_sales(state) == "end"
