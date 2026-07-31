"""测试核心 API 端点——/health /chat /chat/stream

覆盖：
- 健康检查（含组件状态）
- 对话接口认证
- SSE 流式输出格式
"""

import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


class TestHealthEndpoint:
    """GET /health"""

    def get_client(self):
        from fastapi.testclient import TestClient
        from api.main import app
        return TestClient(app)

    def test_health_returns_ok(self):
        """/health 返回 200 + 基础字段"""
        client = self.get_client()
        resp = client.get("/health")

        assert resp.status_code == 200
        data = resp.json()
        assert data["version"] == "0.3.0"
        assert "components" in data
        assert "api" in data["components"]
        assert data["components"]["api"] == "ok"


class TestChatEndpoint:
    """POST /chat"""

    @pytest.fixture(autouse=True)
    def _setup(self, mock_user_store, auth_header):
        self.auth_header = auth_header

    def get_client(self):
        from fastapi.testclient import TestClient
        from api.main import app
        return TestClient(app)

    def test_chat_no_token(self):
        """无 token → 401"""
        client = self.get_client()
        resp = client.post("/chat", json={
            "conversation_id": "conv-test",
            "message": "你好",
        })
        assert resp.status_code == 401

    @patch("api.main._graph")
    def test_chat_with_token(self, mock_graph):
        """带 token → 200，返回 ChatResponse"""
        mock_graph.ainvoke = AsyncMock(return_value={
            "final_reply": "您好！有什么可以帮您的？",
            "current_branch": "customer_service",
            "need_human": False,
            "intent_scores": {"service": 0.9},
        })

        client = self.get_client()
        resp = client.post("/chat", headers=self.auth_header, json={
            "conversation_id": "conv-test-01",
            "message": "你好",
            "channel": "web",
            "language": "zh",
        })

        assert resp.status_code == 200
        data = resp.json()
        assert data["reply"] == "您好！有什么可以帮您的？"
        assert data["current_branch"] == "customer_service"
        assert data["need_human"] is False

    @patch("api.main._graph")
    def test_chat_with_draft(self, mock_graph):
        """行程草案正确嵌入响应"""
        mock_graph.ainvoke = AsyncMock(return_value={
            "final_reply": "# 北京三日游\n...",
            "draft": {
                "version": 1,
                "itinerary_md": "# 北京三日游\n\n## Day 1\n...",
                "estimated_cost": "3000 RMB/人",
                "weather_summary": "晴 22-28°C",
            },
            "need_human": False,
        })

        client = self.get_client()
        resp = client.post("/chat", headers=self.auth_header, json={
            "conversation_id": "conv-draft",
            "message": "北京3天行程",
        })

        assert resp.status_code == 200
        data = resp.json()
        assert data["draft"] is not None
        assert data["draft"]["version"] == 1
        assert data["draft"]["itinerary_md"].startswith("# 北京三日游")

    @patch("api.main._graph")
    def test_chat_error_handling(self, mock_graph):
        """graph 异常 → 500"""
        mock_graph.ainvoke = AsyncMock(side_effect=RuntimeError("LLM timeout"))

        client = self.get_client()
        resp = client.post("/chat", headers=self.auth_header, json={
            "conversation_id": "conv-error",
            "message": "触发错误",
        })

        assert resp.status_code == 500


class TestChatStreamEndpoint:
    """POST /chat/stream（SSE）"""

    @pytest.fixture(autouse=True)
    def _setup(self, mock_user_store, auth_header):
        self.auth_header = auth_header

    def get_client(self):
        from fastapi.testclient import TestClient
        from api.main import app
        return TestClient(app)

    def test_stream_no_token(self):
        """无 token → 401"""
        client = self.get_client()
        resp = client.post("/chat/stream", json={
            "conversation_id": "conv-test",
            "message": "你好",
        })
        assert resp.status_code == 401

    def test_stream_content_type(self):
        """SSE 端点返回 text/event-stream"""
        # 使用流式读取，仅验证 content-type
        client = self.get_client()
        with client.stream("POST", "/chat/stream", headers=self.auth_header, json={
            "conversation_id": "conv-sse",
            "message": "你好",
            "channel": "web",
            "language": "zh",
        }) as resp:
            assert resp.status_code == 200
            assert "text/event-stream" in resp.headers.get("content-type", "")
            # 读一行验证 SSE 格式
            first_line = ""
            for line in resp.iter_lines():
                if line.strip():
                    first_line = line.strip()
                    break
            assert first_line.startswith("event:")

    @patch("api.main._graph")
    def test_stream_events(self, mock_graph):
        """流式响应包含 node_start → node_complete → done 事件"""

        async def mock_astream(*args, **kwargs):
            yield {"intent_router": {"intent_scores": {"service": 1.0}}}
            yield {"customer_service": {"final_reply": "这是关于签证的回答..."}}

        mock_graph.astream = mock_astream

        client = self.get_client()
        events = []
        with client.stream("POST", "/chat/stream", headers=self.auth_header, json={
            "conversation_id": "conv-sse-02",
            "message": "签证需要什么材料？",
        }) as resp:
            current_event = None
            for line in resp.iter_lines():
                line = line.strip()
                if line.startswith("event:"):
                    current_event = line.split(":", 1)[1].strip()
                elif line.startswith("data:"):
                    data_str = line.split(":", 1)[1].strip()
                    events.append({"event": current_event, "data": json.loads(data_str)})
                if len(events) >= 5:
                    break

        assert len(events) > 0
        event_types = [e["event"] for e in events]
        assert "node_start" in event_types
        assert "done" in event_types or "node_complete" in event_types

    @patch("api.main._graph")
    def test_stream_error_handling(self, mock_graph):
        """graph 异常 → error 事件"""

        async def mock_error(*args, **kwargs):
            raise RuntimeError("LLM API Error")
            yield  # unreachable

        mock_graph.astream = mock_error

        client = self.get_client()
        with client.stream("POST", "/chat/stream", headers=self.auth_header, json={
            "conversation_id": "conv-error-sse",
            "message": "触发错误",
        }) as resp:
            body_started = False
            for line in resp.iter_lines():
                line = line.strip()
                if line.startswith("event:") and not body_started:
                    # 应该收到 error 事件
                    event_type = line.split(":", 1)[1].strip()
                    assert event_type == "error"
                    break
