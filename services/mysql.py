"""MySQL 连接管理——SQLAlchemy 异步引擎

提供 MySQL 连接池和会话生命周期管理。

使用方式：
    from services.mysql import get_engine, init_mysql, close_mysql

    await init_mysql()           # 应用启动时
    engine = get_engine()        # 获取 AsyncEngine
    await close_mysql()          # 应用关闭时
"""

import os
import logging
from sqlalchemy.ext.asyncio import create_async_engine, AsyncEngine, async_sessionmaker, AsyncSession

logger = logging.getLogger(__name__)

# 模块级单例
_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker | None = None


def _build_database_url() -> str:
    """从环境变量构建 MySQL 连接 URL"""
    host = os.getenv("MYSQL_HOST", "mysql")
    port = os.getenv("MYSQL_PORT", "3306")
    user = os.getenv("MYSQL_USER", "travel")
    password = os.getenv("MYSQL_PASSWORD", "travel123")
    database = os.getenv("MYSQL_DATABASE", "travel_agent")

    return f"mysql+aiomysql://{user}:{password}@{host}:{port}/{database}?charset=utf8mb4"


async def init_mysql() -> AsyncEngine:
    """初始化 MySQL 连接池（应用启动时调用一次）

    Returns:
        AsyncEngine 实例
    """
    global _engine, _session_factory

    url = _build_database_url()
    logger.info(f"Connecting to MySQL at {url.split('@')[1].split('/')[0]}")

    _engine = create_async_engine(
        url,
        pool_size=10,
        max_overflow=20,
        pool_recycle=3600,
        pool_pre_ping=True,
        echo=False,
    )

    _session_factory = async_sessionmaker(
        _engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    # 验证连接
    try:
        async with _engine.begin() as conn:
            await conn.execute(
                __import__("sqlalchemy").text("SELECT 1")
            )
        logger.info("MySQL connection established")
    except Exception as e:
        logger.warning(f"MySQL connection failed (retrying on first use): {e}")

    return _engine


async def close_mysql():
    """关闭 MySQL 连接池（应用关闭时调用）"""
    global _engine, _session_factory
    if _engine:
        await _engine.dispose()
        _engine = None
        _session_factory = None
        logger.info("MySQL connection pool disposed")


def get_engine() -> AsyncEngine:
    """获取 AsyncEngine（未初始化时抛异常）"""
    if _engine is None:
        raise RuntimeError("MySQL not initialized. Call init_mysql() first.")
    return _engine


def get_session_factory() -> async_sessionmaker:
    """获取 AsyncSession 工厂"""
    if _session_factory is None:
        raise RuntimeError("MySQL not initialized. Call init_mysql() first.")
    return _session_factory


async def get_session() -> AsyncSession:
    """获取一个 AsyncSession 上下文管理器

    使用方式：
        async with await get_session() as session:
            ...
    """
    factory = get_session_factory()
    return factory()
