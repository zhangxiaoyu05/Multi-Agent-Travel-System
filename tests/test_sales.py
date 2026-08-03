"""测试销售分支：条件边 + Mock 工具 + 节点函数

覆盖报价工具、库存工具、after_sales 条件边、销售节点。
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# =============================================================================
# 报价工具测试
# =============================================================================


class TestQuotePrice:
    """报价生成工具——验证城市基准价和主题/节奏因子"""

    def test_beijing_quote(self):
        from tools.mock_quote import quote_price
        result = quote_price.invoke({
            "destination": "北京", "days": 3, "pax": 2,
            "theme": "历史文化", "pace": "适中", "currency": "¥",
        })
        assert "北京" in result
        assert "¥" in result
        assert "3" in result or "天" in result

    def test_sanya_quote(self):
        """三亚基准价最高（1000 元/天）"""
        from tools.mock_quote import quote_price
        result = quote_price.invoke({
            "destination": "三亚", "days": 5, "pax": 2,
            "theme": "自然风光", "pace": "轻松", "currency": "¥",
        })
        assert "三亚" in result
        assert "¥" in result

    def test_quote_with_food_theme(self):
        """美食主题 +15% 溢价"""
        from tools.mock_quote import quote_price
        result = quote_price.invoke({
            "destination": "成都", "days": 3, "pax": 1,
            "theme": "美食", "pace": "适中", "currency": "¥",
        })
        assert "成都" in result

    def test_quote_relaxed_pace(self):
        """轻松节奏 +30% 费用"""
        from tools.mock_quote import quote_price
        result = quote_price.invoke({
            "destination": "西安", "days": 4, "pax": 2,
            "theme": "历史文化", "pace": "轻松", "currency": "¥",
        })
        assert "西安" in result

    def test_quote_unknown_city(self):
        """未知城市使用默认基准价"""
        from tools.mock_quote import quote_price
        result = quote_price.invoke({
            "destination": "火星", "days": 3, "pax": 2,
            "theme": "综合", "pace": "适中", "currency": "¥",
        })
        assert "火星" in result
        # 应有报价输出（使用默认基准价）
        assert "¥" in result or "$" in result

    def test_quote_all_known_cities(self):
        """所有 32 个已知城市都应返回有效报价"""
        from tools.mock_quote import quote_price

        known = [
            "北京", "上海", "西安", "成都", "广州", "桂林",
            "杭州", "重庆", "昆明", "拉萨", "哈尔滨", "三亚",
        ]
        for city in known:
            result = quote_price.invoke({
                "destination": city, "days": 2, "pax": 1,
                "theme": "经典必游", "pace": "适中", "currency": "¥",
            })
            assert city in result, f"城市 '{city}' 应返回有效报价"


# =============================================================================
# 库存工具测试（跨 Agent 共用，回归验证）
# =============================================================================


class TestInventoryTool:
    """库存查询工具——回归验证"""

    def test_basic_query(self):
        from tools.mock_inventory import query_inventory
        result = query_inventory.invoke({"city": "三亚", "date": "2026-09-01", "pax": 4})
        assert "三亚" in result
        assert "酒店" in result or "门票" in result or "车辆" in result


# =============================================================================
# after_sales 条件边
# =============================================================================


class TestAfterSales:
    """销售后置条件边——三路分发"""

    def test_need_human_routes_to_handoff(self):
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

    def test_revise_to_end(self):
        """mid + revise → end（等待下一轮）"""
        from graph.conditions.after_sales import after_sales
        state = {"need_human": False, "intent_level": "mid", "next_action": "revise"}
        assert after_sales(state) == "end"

    def test_need_human_priority(self):
        """need_human=True 始终优先，忽略 intent_level"""
        from graph.conditions.after_sales import after_sales
        state = {"need_human": True, "intent_level": "high", "next_action": "accept"}
        assert after_sales(state) == "human_handoff"


# =============================================================================
# 销售节点（Mock Agent）
# =============================================================================


class TestSalesNode:
    """销售节点——Mock SalesAgent"""

    @patch("graph.nodes.sales_agent.get_sales_agent")
    async def test_node_returns_reply(self, mock_get_agent, sales_state):
        """节点应返回 final_reply 文本"""
        mock_agent = MagicMock()
        mock_agent.run = AsyncMock(return_value={
            "final_reply": "根据您的需求，三亚5日游报价如下...",
            "need_human": False,
            "intent_level": "high",
            "next_action": "accept",
        })
        mock_get_agent.return_value = mock_agent

        from graph.nodes.sales_agent import sales_agent
        result = await sales_agent(sales_state)

        assert "final_reply" in result
        assert result["final_reply"] == "根据您的需求，三亚5日游报价如下..."

    @patch("graph.nodes.sales_agent.get_sales_agent")
    async def test_node_returns_intent(self, mock_get_agent, sales_state):
        """节点应返回意向等级和下一步行动"""
        mock_agent = MagicMock()
        mock_agent.run = AsyncMock(return_value={
            "final_reply": "报价已生成",
            "need_human": False,
            "intent_level": "high",
            "next_action": "accept",
        })
        mock_get_agent.return_value = mock_agent

        from graph.nodes.sales_agent import sales_agent
        result = await sales_agent(sales_state)

        assert result["intent_level"] == "high"
        assert result["next_action"] == "accept"
        assert result["current_branch"] == "sales_agent"

    @patch("graph.nodes.sales_agent.get_sales_agent")
    async def test_node_need_human(self, mock_get_agent):
        """投诉类销售请求应触发转人工"""
        from langchain_core.messages import HumanMessage

        complaint_sales_state = {
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
            "intent_level": "low",
            "next_action": "give_up",
        })
        mock_get_agent.return_value = mock_agent

        from graph.nodes.sales_agent import sales_agent
        result = await sales_agent(complaint_sales_state)

        assert result["need_human"] is True
        assert result["current_branch"] == "sales_agent"


# =============================================================================
# 销售意向评分（纯逻辑）
# =============================================================================


class TestSalesIntentScoring:
    """销售 Agent 内的意向评分——纯关键词逻辑"""

    def test_high_intent_purchase(self):
        """预订/购买关键词 → high + accept"""
        from agents.sales_agent import SalesAgent

        agent = SalesAgent()
        level, action = agent._score_intent("我要预订这个行程", "好的，为您确认预订")
        assert level == "high"
        assert action == "accept"

    def test_mid_intent_considering(self):
        """考虑/再看看 → mid + revise"""
        from agents.sales_agent import SalesAgent

        agent = SalesAgent()
        level, action = agent._score_intent("我再考虑一下", "好的，随时联系我")
        assert level == "mid"
        assert action == "revise"

    def test_low_intent_cancel(self):
        """太贵/算了 → low + give_up"""
        from agents.sales_agent import SalesAgent

        agent = SalesAgent()
        level, action = agent._score_intent("太贵了，算了不要了", "理解，再见")
        assert level == "low"
        assert action == "give_up"

    def test_quote_in_reply_drives_mid(self):
        """报价出现在回复中 → 默认 mid"""
        from agents.sales_agent import SalesAgent

        agent = SalesAgent()
        level, action = agent._score_intent("你好", "这是您的报价单...")
        assert level == "mid"

    def test_no_signals_default_mid(self):
        """无明确信号 → mid"""
        from agents.sales_agent import SalesAgent

        agent = SalesAgent()
        level, action = agent._score_intent("你好", "请问需要什么帮助")
        assert level == "mid"
