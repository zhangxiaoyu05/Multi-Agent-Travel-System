"""测试对话管理 CRUD——列表 / 创建 / 删除 / 历史消息

所有端点需要认证（JWT Bearer token）。
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


class TestConversationEndpoints:
    """GET/POST/DELETE /conversations + /conversations/{id}/messages"""

    @pytest.fixture(autouse=True)
    def _setup(self, mock_user_store, auth_header):
        self.mock_store = mock_user_store
        self.auth_header = auth_header

    def get_client(self):
        from fastapi.testclient import TestClient
        from api.main import app
        return TestClient(app)

    # ---- 列表 ----

    def test_list_empty(self, mock_user_store):
        """无对话时返回空列表"""
        mock_user_store.list_conversations = AsyncMock(return_value=[])

        client = self.get_client()
        resp = client.get("/conversations", headers=self.auth_header)

        assert resp.status_code == 200
        assert resp.json() == []

    def test_list_with_data(self, mock_user_store):
        """有对话时正确返回并按时间排序"""
        mock_user_store.list_conversations = AsyncMock(return_value=[
            {"conversation_id": "conv-02", "title": "北京行程",
             "created_at": "2026-08-01", "updated_at": "2026-08-01"},
            {"conversation_id": "conv-01", "title": "签证咨询",
             "created_at": "2026-07-20", "updated_at": "2026-07-20"},
        ])

        client = self.get_client()
        resp = client.get("/conversations", headers=self.auth_header)

        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2
        assert data[0]["conversation_id"] == "conv-02"

    def test_list_unauthorized(self):
        """无 token → 401"""
        client = self.get_client()
        resp = client.get("/conversations")
        assert resp.status_code == 401

    # ---- 创建 ----

    def test_create_success(self, mock_user_store):
        """创建对话成功"""
        mock_user_store.create_conversation = AsyncMock()

        client = self.get_client()
        resp = client.post("/conversations", headers=self.auth_header, json={
            "title": "新行程咨询",
        })

        assert resp.status_code == 200
        data = resp.json()
        assert data["conversation_id"].startswith("conv-")
        assert data["title"] == "新行程咨询"

        mock_user_store.create_conversation.assert_called_once()

    def test_create_default_title(self, mock_user_store):
        """不传标题时使用默认值"""
        mock_user_store.create_conversation = AsyncMock()

        client = self.get_client()
        resp = client.post("/conversations", headers=self.auth_header, json={})

        assert resp.status_code == 200
        assert resp.json()["title"] == "新对话"

    # ---- 删除 ----

    def test_delete_success(self, mock_user_store):
        """删除自己的对话成功"""
        mock_user_store.delete_conversation = AsyncMock(return_value=True)

        client = self.get_client()
        resp = client.delete("/conversations/conv-01", headers=self.auth_header)

        assert resp.status_code == 200
        assert resp.json() == {"ok": True}

    def test_delete_not_found(self, mock_user_store):
        """删除不存在或他人的对话 → 404"""
        mock_user_store.delete_conversation = AsyncMock(return_value=False)

        client = self.get_client()
        resp = client.delete("/conversations/conv-999", headers=self.auth_header)

        assert resp.status_code == 404
        assert "不存在或无权删除" in resp.json()["detail"]

    # ---- 历史消息 ----

    @patch("api.main._graph")
    def test_get_messages_with_history(self, mock_graph, mock_user_store):
        """有消息历史时正确返回"""
        from langchain_core.messages import HumanMessage, AIMessage

        mock_user_store.get_conversation = AsyncMock(return_value={
            "conversation_id": "conv-01",
            "user_id": "test-user-01",
            "title": "测试对话",
        })

        mock_state = MagicMock()
        mock_state.values = {
            "messages": [
                HumanMessage(content="签证需要什么？"),
                AIMessage(content="签证需要护照、照片..."),
            ]
        }
        mock_graph.aget_state = AsyncMock(return_value=mock_state)

        client = self.get_client()
        resp = client.get("/conversations/conv-01/messages", headers=self.auth_header)

        assert resp.status_code == 200
        data = resp.json()
        assert data["conversation_id"] == "conv-01"
        assert len(data["messages"]) == 2
        assert data["messages"][0]["role"] == "user"
        assert data["messages"][1]["role"] == "agent"

    @patch("api.main._graph")
    def test_get_messages_not_owner(self, mock_graph, mock_user_store):
        """不能查看他人的对话 → 404"""
        mock_user_store.get_conversation = AsyncMock(return_value={
            "conversation_id": "conv-01",
            "user_id": "other-user",
            "title": "别人的对话",
        })

        client = self.get_client()
        resp = client.get("/conversations/conv-01/messages", headers=self.auth_header)

        assert resp.status_code == 404
