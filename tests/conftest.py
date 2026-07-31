"""pytest 共享 fixtures

为所有测试模块提供可复用的测试状态和 Mock 对象。
"""

import pytest
from unittest.mock import MagicMock, patch
from langchain_core.messages import HumanMessage, AIMessage


# =============================================================================
# State fixtures
# =============================================================================


@pytest.fixture
def base_state() -> dict:
    """最简初始状态——模拟 /chat 请求注入的 State"""
    return {
        "messages": [HumanMessage(content="你好")],
        "session_id": "test-session-01",
        "customer_id": "cust-test-01",
        "channel": "web",
        "language": "zh",
    }


@pytest.fixture
def planner_state() -> dict:
    """模拟定制流程中的 State——已提取部分需求"""
    return {
        "messages": [HumanMessage(content="我想去西安玩4天，8月20号到，2个人，预算每人1500美元")],
        "session_id": "test-session-02",
        "customer_id": "cust-test-02",
        "channel": "web",
        "language": "zh",
        "need": {
            "destination": "西安",
            "days": 4,
            "arrival_date": "2026-08-20",
            "pax": 2,
            "budget": "1500美元",
        },
        "intent_scores": {"service": 0.1, "sales": 0.05, "operations": 0.05, "planner": 0.8},
        "current_branch": "planner",
    }


@pytest.fixture
def complaint_state() -> dict:
    """模拟投诉场景的 State"""
    return {
        "messages": [HumanMessage(content="我要投诉，导游完全不专业！我要退款！")],
        "session_id": "test-session-03",
        "customer_id": "cust-test-03",
        "channel": "web",
        "language": "zh",
    }


@pytest.fixture
def state_with_draft() -> dict:
    """模拟已有行程草案的 State——准备进行意向评分"""
    return {
        "messages": [HumanMessage(content="行程看起来不错，但我还想加点美食推荐")],
        "session_id": "test-session-04",
        "customer_id": "cust-test-04",
        "channel": "web",
        "language": "zh",
        "need": {
            "destination": "北京",
            "days": 3,
            "arrival_date": "2026-09-01",
            "pax": 1,
            "budget": "3000人民币",
        },
        "draft": {
            "version": 1,
            "itinerary_md": "# 北京三日游\n\n## Day 1\n...",
            "estimated_cost": "3000人民币/人",
        },
        "revision_count": 0,
    }


# =============================================================================
# Mock fixtures
# =============================================================================


@pytest.fixture
def mock_llm_response():
    """创建可配置的 Mock LLM 响应工厂"""
    def _make_response(content: str = "", tool_calls: list | None = None):
        msg = AIMessage(content=content)
        if tool_calls:
            msg.tool_calls = tool_calls
        return msg
    return _make_response


@pytest.fixture
def mock_router_llm():
    """Mock 意图路由器 LLM，返回预定义结果"""
    with patch("graph.nodes.intent_router.get_router_llm") as mock_llm:
        yield mock_llm


@pytest.fixture
def mock_agent_llm():
    """Mock Agent LLM，返回预定义结果"""
    with patch("services.llm.get_agent_llm") as mock_llm:
        yield mock_llm
