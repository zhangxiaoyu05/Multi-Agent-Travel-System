"""pytest 共享 fixtures（异步版）

为所有测试模块提供可复用的测试状态和 Mock 对象。
"""

import asyncio
import pytest
from unittest.mock import MagicMock, patch
from langchain_core.messages import HumanMessage, AIMessage


# =============================================================================
# State fixtures
# =============================================================================


@pytest.fixture
def base_state() -> dict:
    """最简初始状态"""
    return {
        "messages": [HumanMessage(content="你好")],
        "session_id": "test-session-01",
        "customer_id": "cust-test-01",
        "channel": "web",
        "language": "zh",
    }


@pytest.fixture
def planner_state() -> dict:
    """定制流程状态——已提取部分需求"""
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
    """投诉场景状态"""
    return {
        "messages": [HumanMessage(content="我要投诉，导游完全不专业！我要退款！")],
        "session_id": "test-session-03",
        "customer_id": "cust-test-03",
        "channel": "web",
        "language": "zh",
    }


@pytest.fixture
def state_with_draft() -> dict:
    """已有行程草案的状态"""
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


@pytest.fixture
def sales_state() -> dict:
    """销售咨询场景状态"""
    return {
        "messages": [HumanMessage(content="我想去三亚玩5天，2个人，每人预算2000美元，能报个价吗？")],
        "session_id": "test-sales-01",
        "customer_id": "cust-sales-01",
        "channel": "web",
        "language": "zh",
        "need": {
            "destination": "三亚",
            "days": 5,
            "pax": 2,
            "budget": "$2000",
        },
        "intent_scores": {"service": 0.05, "sales": 0.85, "operations": 0.05, "planner": 0.05},
        "current_branch": "sales",
    }


@pytest.fixture
def operations_state() -> dict:
    """运营咨询场景状态"""
    return {
        "messages": [HumanMessage(content="我是旅行社的，想在你们平台上架产品，需要什么资质？")],
        "session_id": "test-ops-01",
        "customer_id": "cust-ops-01",
        "channel": "web",
        "language": "zh",
        "intent_scores": {"service": 0.1, "sales": 0.0, "operations": 0.85, "planner": 0.05},
        "current_branch": "operations",
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
    """Mock get_router_llm 返回 BailianLLM"""
    with patch("graph.nodes.intent_router.get_router_llm") as mock_llm:
        yield mock_llm


@pytest.fixture
def mock_agent_llm():
    """Mock get_agent_llm 返回 BailianLLM"""
    with patch("services.llm.get_agent_llm") as mock_llm:
        yield mock_llm


# =============================================================================
# Utility helpers
# =============================================================================


def make_mock_agent(return_value: dict) -> MagicMock:
    """创建带 async run() 方法的 Mock Agent。

    Usage:
        mock_agent = make_mock_agent({"final_reply": "回复", "need_human": False})
        mock_get_agent.return_value = mock_agent
    """
    from unittest.mock import AsyncMock
    mock = MagicMock()
    mock.run = AsyncMock(return_value=return_value)
    return mock


def run_async(coro):
    """Helper: 在同步测试中运行异步节点函数"""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    import concurrent.futures
    with concurrent.futures.ThreadPoolExecutor() as executor:
        future = executor.submit(asyncio.run, coro)
        return future.result()
