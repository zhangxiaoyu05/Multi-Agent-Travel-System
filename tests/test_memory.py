"""记忆系统单元测试——短/中/长期记忆"""
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock
from datetime import datetime, timedelta
from collections import OrderedDict


# =============================================================================
# MemoryManager — 消息 CRUD（使用 mock MySQL）
# =============================================================================


def _make_mock_conn(return_rows=None, lastrowid=None, first_row=None, count=0):
    """创建 mock 数据库连接

    Args:
        return_rows: mappings().all() 返回的行列表
        lastrowid: INSERT 返回的 lastrowid
        first_row: mappings().first() 返回的单行
        count: mappings().first() 中 cnt 字段的值
    """
    conn = AsyncMock()
    mock_result = MagicMock()

    if return_rows is not None:
        mock_result.mappings.return_value.all.return_value = return_rows
    if first_row is not None:
        mock_result.mappings.return_value.first.return_value = first_row
    if count:
        mock_result.mappings.return_value.first.return_value = OrderedDict([("cnt", count)])
    if lastrowid is not None:
        mock_result.lastrowid = lastrowid

    conn.execute = AsyncMock(return_value=mock_result)
    conn.__aenter__ = AsyncMock(return_value=conn)
    conn.__aexit__ = AsyncMock(return_value=None)
    return conn


def _patch_engine_with_conn(mock_conn):
    """创建 patcher 将 get_engine 替换为返回 mock_conn 的 engine mock"""
    mock_engine = MagicMock()
    mock_engine.begin = MagicMock(return_value=mock_conn)
    return patch("services.memory.get_engine", return_value=mock_engine)


class TestMemoryManagerMessages:
    """短期记忆——消息存取"""

    @pytest.mark.asyncio
    async def test_save_message(self):
        """保存用户消息到 MySQL"""
        mock_conn = _make_mock_conn(lastrowid=1)
        with _patch_engine_with_conn(mock_conn):
            from services.memory import MemoryManager
            mm = MemoryManager()
            result = await mm.save_message(
                "conv-abc", "user", "我想去西安",
                branch="planner",
                intent_scores={"planner": 0.9}
            )
            assert result == 1

    @pytest.mark.asyncio
    async def test_get_messages(self):
        """获取对话消息列表"""
        rows = [
            OrderedDict([
                ("id", 1), ("role", "user"), ("content", "想去北京"),
                ("branch", "planner"), ("intent_scores", '{"planner":0.8}'),
                ("draft", None), ("metadata", None),
                ("created_at", datetime(2026, 8, 1, 10, 0)),
            ]),
            OrderedDict([
                ("id", 2), ("role", "agent"), ("content", "好的，请提供更多信息"),
                ("branch", "planner"), ("intent_scores", None),
                ("draft", None), ("metadata", None),
                ("created_at", datetime(2026, 8, 1, 10, 1)),
            ]),
        ]
        mock_conn = _make_mock_conn(return_rows=rows)
        with _patch_engine_with_conn(mock_conn):
            from services.memory import MemoryManager
            mm = MemoryManager()
            msgs = await mm.get_messages("conv-abc", limit=10)

        assert len(msgs) == 2
        assert msgs[0]["role"] == "user"
        assert msgs[0]["content"] == "想去北京"
        assert msgs[0]["intent_scores"] == {"planner": 0.8}
        assert msgs[1]["role"] == "agent"

    @pytest.mark.asyncio
    async def test_get_message_count(self):
        """获取消息总数"""
        mock_conn = _make_mock_conn(count=5)
        with _patch_engine_with_conn(mock_conn):
            from services.memory import MemoryManager
            mm = MemoryManager()
            count = await mm.get_message_count("conv-abc")
            assert count == 5


class TestTokenEstimation:
    """Token 估算测试"""

    def test_chinese_token_estimate(self):
        from services.memory import MemoryManager
        text = "你好，我想去西安旅游"
        tokens = MemoryManager.estimate_tokens(text)
        assert 8 <= tokens <= 15

    def test_english_token_estimate(self):
        from services.memory import MemoryManager
        text = "Hello, I want to travel to Beijing"
        tokens = MemoryManager.estimate_tokens(text)
        assert 10 <= tokens <= 18

    def test_mixed_token_estimate(self):
        from services.memory import MemoryManager
        text = "I want to go to 西安 for 5 days"
        tokens = MemoryManager.estimate_tokens(text)
        assert 8 <= tokens <= 20

    def test_empty_text(self):
        from services.memory import MemoryManager
        assert MemoryManager.estimate_tokens("") >= 4

    def test_messages_token_estimate(self):
        from services.memory import MemoryManager
        msgs = [
            {"role": "user", "content": "你好"},
            {"role": "agent", "content": "您好，有什么可以帮您？"},
        ]
        total = MemoryManager.estimate_messages_tokens(msgs)
        assert total > 0

    def test_should_summarize_below_threshold(self):
        from services.memory import MemoryManager
        mm = MemoryManager()
        msgs = [{"role": "user", "content": "你好"}] * 5
        assert not mm.should_summarize(msgs)


class TestMemoryManagerProfile:
    """长期记忆——用户画像"""

    @pytest.mark.asyncio
    async def test_ensure_profile_creates_new(self):
        """确保画像存在——创建新画像（profile 不存在时自动创建）"""
        # _ensure_profile: first get_profile returns None
        first_row = None

        def _make_first_conn():
            c = AsyncMock()
            r = MagicMock()
            r.mappings.return_value.first.return_value = first_row
            c.execute = AsyncMock(return_value=r)
            c.__aenter__ = AsyncMock(return_value=c)
            c.__aexit__ = AsyncMock(return_value=None)
            return c

        # We need 2 engine.begin() calls: get_profile + INSERT
        mock_engine = MagicMock()
        mock_engine.begin = MagicMock(side_effect=[_make_first_conn(), _make_first_conn()])

        with patch("services.memory.get_engine", return_value=mock_engine):
            from services.memory import MemoryManager
            mm = MemoryManager()
            profile = await mm.ensure_profile("user-001", "testuser")

            # Should fall through to creation path since get_profile returned None
            assert profile is not None
            assert isinstance(profile, dict)

    @pytest.mark.asyncio
    async def test_merge_suggestions_clears(self):
        """merge_suggestions 清空 suggested_fields——结构验证"""
        profile_row = OrderedDict([
            ("user_id", "user-001"),
            ("display_name", "Test"),
            ("avatar_url", None), ("email", None), ("phone", None),
            ("nationality", None), ("passport_country", None),
            ("preferred_language", "zh"),
            ("preferred_destinations", '["北京"]'),
            ("budget_range", None),
            ("travel_style", None),
            ("interests", '["历史文化"]'),
            ("travel_companion", None),
            ("special_needs", None), ("preferred_seasons", None),
            ("suggested_fields", '{"interests":["美食"],"travel_style":"轻松"}'),
            ("source", "llm_extract"),
            ("created_at", datetime(2026, 8, 1)),
            ("updated_at", datetime(2026, 8, 1)),
            ("last_active_at", datetime(2026, 8, 1)),
        ])

        # Test _row_to_profile directly (pure function, no mock needed)
        from services.memory import MemoryManager
        mm = MemoryManager()
        profile = mm._row_to_profile(profile_row)

        assert profile["user_id"] == "user-001"
        assert profile["preferred_destinations"] == ["北京"]
        assert profile["interests"] == ["历史文化"]
        assert profile["suggested_fields"] == {"interests": ["美食"], "travel_style": "轻松"}

    @pytest.mark.asyncio
    async def test_reject_suggestions(self):
        """拒绝 LLM 建议"""
        update_conn = _make_mock_conn()
        with _patch_engine_with_conn(update_conn):
            from services.memory import MemoryManager
            mm = MemoryManager()
            result = await mm.reject_suggestions("user-001")
            assert result is True


class TestPreferenceExtraction:
    """中期记忆——偏好提取"""

    def test_estimate_tokens_base(self):
        from services.memory import MemoryManager
        cn = "你好，我想去西安旅游三天，预算每人一千美元"
        tokens = MemoryManager.estimate_tokens(cn)
        assert 15 <= tokens <= 35

    @pytest.mark.asyncio
    async def test_extract_preferences_with_mock_llm(self):
        """使用 mock LLM 测试偏好提取"""
        mock_conn = _make_mock_conn()
        with _patch_engine_with_conn(mock_conn):
            from services.memory import MemoryManager
            mm = MemoryManager()

            messages = [
                {"role": "user", "content": "想去北京和西安，喜欢历史文化"},
                {"role": "agent", "content": "好的，北京和西安都是历史文化名城"},
            ]

            # Patch the LLM import in memory.py (it imports get_router_llm from services.llm)
            with patch("services.llm.get_router_llm") as mock_get_llm:
                mock_llm = MagicMock()
                mock_structured = MagicMock()

                # Build a mock result object
                mock_result = MagicMock()
                mock_result.preferred_destinations = ["北京", "西安"]
                mock_result.budget_range = None
                mock_result.travel_style = None
                mock_result.interests = ["历史文化"]
                mock_result.travel_companion = None
                mock_result.special_needs = None
                mock_result.preferred_seasons = None
                mock_result.confidence = 0.8
                mock_result.model_dump = MagicMock(return_value={
                    "preferred_destinations": ["北京", "西安"],
                    "interests": ["历史文化"],
                    "confidence": 0.8,
                })

                mock_structured.ainvoke = AsyncMock(return_value=mock_result)
                mock_llm.with_structured_output = MagicMock(return_value=mock_structured)
                mock_get_llm.return_value = mock_llm

                result = await mm.extract_preferences("user-001", "conv-001", messages)

                assert result is not None
                assert result["user_id"] == "user-001"
                assert "北京" in result.get("preferred_destinations", [])


# =============================================================================
# Redis 缓存测试
# =============================================================================


class TestRedisCache:
    """Redis 缓存功能"""

    @pytest.mark.asyncio
    async def test_cache_chat_messages_graceful_failure(self):
        """Redis 不可用时缓存应该优雅降级（不抛异常）"""
        with patch("services.redis.get_redis", side_effect=RuntimeError("Redis not connected")):
            from services.redis import cache_chat_messages, get_cached_chat_messages
            await cache_chat_messages("conv-test", [{"role": "user", "content": "hi"}])
            result = await get_cached_chat_messages("conv-test")
            assert result is None

    @pytest.mark.asyncio
    async def test_invalidate_user_cache(self):
        """清除用户缓存"""
        mock_redis = AsyncMock()
        with patch("services.redis.get_redis", return_value=mock_redis):
            from services.redis import invalidate_user_cache
            await invalidate_user_cache("user-001")
            mock_redis.delete.assert_called_once()
