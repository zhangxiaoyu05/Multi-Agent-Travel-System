"""pytest 共享 fixtures（异步版）

为所有测试模块提供可复用的测试状态和 Mock 对象。
"""

import os
import asyncio
import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from langchain_core.messages import HumanMessage, AIMessage

# 确保测试环境始终使用 memory checkpoint（无需 MySQL）
os.environ.setdefault("CHECKPOINT_BACKEND", "memory")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-pytest")


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
def sales_qualified_state() -> dict:
    """销售 QUALIFIED 阶段状态——已有行程方案"""
    return {
        "messages": [HumanMessage(content="这个行程看起来不错，价格怎么样？")],
        "session_id": "test-sales-q-01",
        "customer_id": "cust-sales-q-01",
        "channel": "web",
        "language": "zh",
        "need": {
            "destination": "北京",
            "days": 3,
            "arrival_date": "2026-09-01",
            "pax": 2,
            "budget": "¥5000/人",
            "theme": "历史文化",
            "pace": "适中",
        },
        "draft": {
            "version": 1,
            "itinerary_md": "## 北京三日游\n\n### Day 1\n故宫-天安门-前门大街\n\n### Day 2\n长城-十三陵\n\n### Day 3\n颐和园-圆明园",
            "estimated_cost": "¥4800/人",
            "weather_summary": "晴好，20-28°C",
        },
        "intent_scores": {"service": 0.05, "sales": 0.85, "operations": 0.05, "planner": 0.05},
        "current_branch": "sales",
        "user_profile": {
            "nationality": "USA",
            "budget_range": {"min": 4000, "max": 8000, "currency": "¥"},
        },
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


@pytest.fixture
def operations_with_order_state() -> dict:
    """运营场景——有活跃订单的状态（Phase 21）"""
    return {
        "messages": [HumanMessage(content="我的订单怎么样了？")],
        "session_id": "test-ops-o-01",
        "customer_id": "cust-ops-o-01",
        "channel": "web",
        "language": "zh",
        "has_active_order": True,
        "active_order_id": "ORD-20260805120000-ABC123",
        "intent_scores": {"service": 0.05, "sales": 0.05, "operations": 0.85, "planner": 0.05},
        "current_branch": "operations",
    }


@pytest.fixture
def operations_won_state() -> dict:
    """销售刚成交的状态——用于测试运营接管（Phase 21）"""
    return {
        "messages": [HumanMessage(content="")],
        "session_id": "test-ops-won-01",
        "customer_id": "cust-ops-won-01",
        "channel": "web",
        "language": "zh",
        "sales_pipeline_stage": "won",
        "final_reply": "恭喜！订单已创建 ORD-20260805-A1B2C3，请点击支付链接完成支付。",
        "need": {"destination": "北京", "days": 3, "pax": 2, "budget": "¥5000/人"},
        "draft": {
            "version": 1,
            "itinerary_md": "## 北京三日游\n\n### Day 1\n故宫-天安门\n\n### Day 2\n长城-十三陵\n\n### Day 3\n颐和园-圆明园",
            "estimated_cost": "¥4800/人",
        },
        "intent_scores": {"service": 0.05, "sales": 0.85, "operations": 0.05, "planner": 0.05},
        "current_branch": "sales",
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


# =============================================================================
# API 测试 fixtures
# =============================================================================


@pytest.fixture
def api_app():
    """创建 FastAPI app（不含 lifespan，用于 TestClient）。

    lifespan 中的 MySQL/Redis/Milvus 初始化会被跳过。
    """
    from fastapi import FastAPI
    from fastapi.middleware.cors import CORSMiddleware

    test_app = FastAPI(
        title="Test App",
        version="0.3.0",
        # 跳过 lifespan，避免基础设施连接
    )

    test_app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    return test_app


@pytest.fixture
def auth_token() -> str:
    """生成有效 JWT token（test-user-01）"""
    from api.auth import create_token
    return create_token("test-user-01", "testuser")


@pytest.fixture
def auth_header(auth_token: str) -> dict:
    """Bearer Authorization header"""
    return {"Authorization": f"Bearer {auth_token}"}


@pytest.fixture(autouse=True)
def mock_user_store():
    """Mock UserStore 的所有 import 路径（auth + main + services）。

    auth.py 和 main.py 中的端点函数都在内部 import UserStore，
    需要 patch 所有路径。autouse=True 确保所有 API 测试自动生效。
    """
    mock_store = MagicMock()
    mock_store.get_user_by_username = AsyncMock(return_value=None)
    mock_store.create_user = AsyncMock()
    mock_store.list_conversations = AsyncMock(return_value=[])
    mock_store.create_conversation = AsyncMock()
    mock_store.delete_conversation = AsyncMock(return_value=True)
    mock_store.get_conversation = AsyncMock(return_value=None)
    mock_store.update_conversation_title = AsyncMock()

    mock_cls = MagicMock(return_value=mock_store)

    with patch("api.auth.UserStore", mock_cls), \
         patch("services.user_store.UserStore", mock_cls):
        yield mock_store
