"""测试 AgentState 及相关数据结构

验证 State 字段定义、嵌套 TypedDict、消息累积行为。
"""

import pytest
from langchain_core.messages import HumanMessage, AIMessage

from graph.state import AgentState, TripNeed, TripDraft


# =============================================================================
# TripNeed / TripDraft 嵌套结构
# =============================================================================


class TestTripNeed:
    """出行需求 TypedDict 的字段和行为"""

    def test_empty_need(self):
        need: TripNeed = {}
        assert need.get("destination") is None
        assert need.get("days") is None

    def test_partial_need(self):
        need: TripNeed = {"destination": "西安", "days": 4}
        assert need["destination"] == "西安"
        assert need["days"] == 4
        assert need.get("pax") is None  # 未填

    def test_full_need(self):
        need: TripNeed = {
            "destination": "北京",
            "days": 3,
            "arrival_date": "2026-08-01",
            "pax": 2,
            "budget": "$2000",
            "theme": "历史文化",
            "pace": "轻松",
            "special_requests": "需要轮椅",
        }
        assert need["destination"] == "北京"
        assert need["theme"] == "历史文化"
        assert need["special_requests"] == "需要轮椅"

    def test_merge_partial_fields(self):
        """模拟多轮对话中逐步填充 need"""
        need: TripNeed = {"destination": "成都"}
        # 第二轮补充
        need2: TripNeed = {**need, "days": 5, "pax": 3}
        assert need2["destination"] == "成都"
        assert need2["days"] == 5
        assert need2["pax"] == 3


class TestTripDraft:
    """行程草案 TypedDict 的字段和行为"""

    def test_empty_draft(self):
        draft: TripDraft = {}
        assert draft.get("version") is None
        assert draft.get("itinerary_md") is None

    def test_v1_draft(self):
        draft: TripDraft = {
            "version": 1,
            "itinerary_md": "# 西安四日游\n\n## Day 1\n兵马俑...",
            "estimated_cost": "¥3500/人",
            "weather_summary": "晴 22-35°C",
        }
        assert draft["version"] == 1
        assert "兵马俑" in draft["itinerary_md"]

    def test_revision_increment(self):
        """修订后版本号递增"""
        draft: TripDraft = {"version": 1, "itinerary_md": "v1 行程"}
        draft2: TripDraft = {**draft, "version": 2, "itinerary_md": "v2 修订版行程"}
        assert draft2["version"] == 2
        assert draft2["version"] > draft["version"]


# =============================================================================
# AgentState 主状态
# =============================================================================


class TestAgentState:
    """AgentState 的字段默认值和消息管理"""

    def test_state_construction(self, base_state):
        """基本 state 构造——包含消息和会话字段"""
        state = base_state
        assert len(state["messages"]) == 1
        assert state["messages"][0].content == "你好"
        assert state["session_id"] == "test-session-01"
        assert state["customer_id"] == "cust-test-01"

    def test_messages_accumulate(self):
        """验证 messages 字段的多轮累积（模拟 LangGraph add_messages reducer）"""
        msgs = [HumanMessage(content="问：西安天气如何？")]
        msgs.append(AIMessage(content="答：西安晴，22-35°C"))
        msgs.append(HumanMessage(content="追问：适合户外活动吗？"))
        msgs.append(AIMessage(content="答：非常适合，建议避开正午高温"))

        assert len(msgs) == 4
        assert msgs[0].content.startswith("问：")
        assert msgs[-1].content.startswith("答：")
        assert all(isinstance(m, (HumanMessage, AIMessage)) for m in msgs)

    def test_state_field_defaults(self, base_state):
        """未设置的 State 字段应返回合理的默认值"""
        assert base_state.get("need_human") is None
        assert base_state.get("revision_count") is None
        assert base_state.get("current_branch") is None
        # channel 和 language 已设置
        assert base_state["channel"] == "web"
        assert base_state["language"] == "zh"

    def test_state_with_intent_scores(self, planner_state):
        """验证 planner 场景的 intent_scores 结构"""
        scores = planner_state["intent_scores"]
        assert scores["planner"] == 0.8
        assert scores["service"] < scores["planner"]
        assert isinstance(scores, dict)
        assert all(k in scores for k in ["service", "sales", "operations", "planner"])
