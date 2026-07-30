"""Redis 连接管理——异步客户端

提供 Redis 连接池和缓存工具函数。

使用方式：
    from services.redis import get_redis, init_redis, close_redis

    await init_redis()           # 应用启动时
    r = get_redis()              # 获取 Redis 实例
    await r.set("key", "value")  # 直接使用
    await close_redis()          # 应用关闭时
"""

import os
import json
import logging
import redis.asyncio as aioredis

logger = logging.getLogger(__name__)

# 模块级单例
_redis: aioredis.Redis | None = None


async def init_redis() -> aioredis.Redis:
    """初始化 Redis 连接池（应用启动时调用一次）

    Returns:
        Redis 实例
    """
    global _redis

    host = os.getenv("REDIS_HOST", "redis")
    port = int(os.getenv("REDIS_PORT", "6379"))
    password = os.getenv("REDIS_PASSWORD", "")
    db = int(os.getenv("REDIS_DB", "0"))

    logger.info(f"Connecting to Redis at {host}:{port}")

    _redis = aioredis.Redis(
        host=host,
        port=port,
        password=password or None,
        db=db,
        decode_responses=True,
        socket_connect_timeout=5,
        socket_keepalive=True,
    )

    # 验证连接
    try:
        await _redis.ping()
        logger.info("Redis connection established")
    except Exception as e:
        logger.warning(f"Redis connection failed (will retry on first use): {e}")

    return _redis


async def close_redis():
    """关闭 Redis 连接（应用关闭时调用）"""
    global _redis
    if _redis:
        await _redis.close()
        _redis = None
        logger.info("Redis connection closed")


def get_redis() -> aioredis.Redis:
    """获取 Redis 实例（未初始化时抛异常）"""
    if _redis is None:
        raise RuntimeError("Redis not initialized. Call init_redis() first.")
    return _redis


# =============================================================================
# 业务缓存工具
# =============================================================================


async def cache_session_history(session_id: str, messages: list, ttl: int | None = None):
    """缓存会话历史到 Redis

    Args:
        session_id: 会话 ID
        messages: 消息列表（JSON 可序列化）
        ttl: 过期时间（秒），默认使用 REDIS_SESSION_TTL
    """
    if ttl is None:
        ttl = int(os.getenv("REDIS_SESSION_TTL", "1800"))

    r = get_redis()
    key = f"session:{session_id}:history"
    await r.setex(key, ttl, json.dumps(messages, ensure_ascii=False, default=str))


async def get_cached_session_history(session_id: str) -> list | None:
    """从 Redis 获取缓存的会话历史

    Returns:
        消息列表，无缓存时返回 None
    """
    try:
        r = get_redis()
        key = f"session:{session_id}:history"
        data = await r.get(key)
        if data:
            return json.loads(data)
    except Exception:
        pass
    return None


async def cache_summary(session_id: str, summary: str, ttl: int | None = None):
    """缓存会话摘要

    Args:
        session_id: 会话 ID
        summary: 摘要文本
        ttl: 过期时间（秒），默认使用 REDIS_SUMMARY_TTL
    """
    if ttl is None:
        ttl = int(os.getenv("REDIS_SUMMARY_TTL", "3600"))

    r = get_redis()
    key = f"session:{session_id}:summary"
    await r.setex(key, ttl, summary)


async def get_cached_summary(session_id: str) -> str | None:
    """从 Redis 获取缓存的会话摘要"""
    try:
        r = get_redis()
        key = f"session:{session_id}:summary"
        data = await r.get(key)
        return data
    except Exception:
        pass
    return None
