"""MySQL Checkpoint Saver——LangGraph 持久化后端

基于 SQLAlchemy 异步 + MySQL 8.0 实现 LangGraph 的 BaseCheckpointSaver 接口。
替代 MemorySaver，服务重启不丢失会话状态。

使用方式：
    from services.checkpoint import MySQLSaver

    saver = MySQLSaver()
    await saver.setup()                    # 自动建表
    graph = builder.compile(checkpointer=saver)

参考：langgraph.checkpoint.base.BaseCheckpointSaver
"""

import logging
from typing import Optional, Iterator, Any
from langgraph.checkpoint.base import (
    BaseCheckpointSaver,
    CheckpointTuple,
    Checkpoint,
    CheckpointMetadata,
)
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.checkpoint.serde.types import ChannelProtocol

from sqlalchemy import text
from services.mysql import get_engine

logger = logging.getLogger(__name__)

# 序列化器：LangGraph 内置的 JSON+MsgPack 混合序列化
_serializer = JsonPlusSerializer()


class MySQLSaver(BaseCheckpointSaver):
    """MySQL 异步 Checkpoint Saver

    实现 LangGraph 的 BaseCheckpointSaver 接口，
    将每次图执行的状态持久化到 MySQL。

    表结构见 scripts/migrate_mysql.sql:
    - checkpoints: 检查点主表
    - checkpoint_writes: 待合并的 channel 写入
    """

    def __init__(self):
        super().__init__(serde=_serializer)

    async def setup(self):
        """确保表存在（幂等，容器首次启动时已通过 migrate_mysql.sql 创建）"""
        engine = get_engine()
        async with engine.begin() as conn:
            await conn.execute(text("""
                CREATE TABLE IF NOT EXISTS checkpoints (
                    thread_id       VARCHAR(255)    NOT NULL,
                    checkpoint_ns   VARCHAR(255)    NOT NULL DEFAULT '',
                    checkpoint_id   VARCHAR(255)    NOT NULL,
                    parent_checkpoint_id VARCHAR(255),
                    type            VARCHAR(255),
                    checkpoint      LONGBLOB        NOT NULL,
                    metadata        LONGBLOB,
                    created_at      TIMESTAMP       NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (thread_id, checkpoint_ns, checkpoint_id),
                    INDEX idx_thread (thread_id)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """))
            await conn.execute(text("""
                CREATE TABLE IF NOT EXISTS checkpoint_writes (
                    thread_id       VARCHAR(255)    NOT NULL,
                    checkpoint_ns   VARCHAR(255)    NOT NULL DEFAULT '',
                    checkpoint_id   VARCHAR(255)    NOT NULL,
                    task_id         VARCHAR(255)    NOT NULL,
                    idx             INT             NOT NULL,
                    channel         VARCHAR(255)    NOT NULL,
                    type            VARCHAR(255),
                    value           LONGBLOB,
                    PRIMARY KEY (thread_id, checkpoint_ns, checkpoint_id, task_id, idx)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """))
        logger.info("MySQL checkpoint tables verified")

    # =========================================================================
    # BaseCheckpointSaver 接口实现
    # =========================================================================

    def get_tuple(self, config: dict) -> Optional[CheckpointTuple]:
        """同步获取检查点（LangGraph 内部调用）

        注意：此方法在 LangGraph 的异步执行中被事件循环线程调用，
        因此创建独立的同步连接执行查询。
        """
        import asyncio
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop is not None:
            # 在已有事件循环中运行协程
            import concurrent.futures
            future = asyncio.run_coroutine_threadsafe(
                self._aget_tuple(config), loop
            )
            return future.result(timeout=10)
        else:
            # 无事件循环，直接同步执行
            return asyncio.run(self._aget_tuple(config))

    def list(
        self,
        config: Optional[dict],
        *,
        filter: Optional[dict] = None,
        before: Optional[dict] = None,
        limit: Optional[int] = None,
    ) -> Iterator[CheckpointTuple]:
        """列出检查点历史"""
        import asyncio
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop is not None:
            import concurrent.futures
            future = asyncio.run_coroutine_threadsafe(
                self._alist(config, filter=filter, before=before, limit=limit),
                loop
            )
            return iter(future.result(timeout=10))
        else:
            return iter(asyncio.run(
                self._alist(config, filter=filter, before=before, limit=limit)
            ))

    def put(
        self,
        config: dict,
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata,
        new_versions: dict,
    ) -> dict:
        """保存检查点"""
        import asyncio
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop is not None:
            import concurrent.futures
            future = asyncio.run_coroutine_threadsafe(
                self._aput(config, checkpoint, metadata, new_versions),
                loop
            )
            return future.result(timeout=10)
        else:
            return asyncio.run(
                self._aput(config, checkpoint, metadata, new_versions)
            )

    def put_writes(
        self,
        config: dict,
        writes: list,
        task_id: str,
    ) -> None:
        """保存待处理写入"""
        import asyncio
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop is not None:
            import concurrent.futures
            future = asyncio.run_coroutine_threadsafe(
                self._aput_writes(config, writes, task_id),
                loop
            )
            future.result(timeout=10)
        else:
            asyncio.run(self._aput_writes(config, writes, task_id))

    def delete_thread(self, thread_id: str) -> None:
        """删除整个会话的检查点"""
        import asyncio
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop is not None:
            import concurrent.futures
            future = asyncio.run_coroutine_threadsafe(
                self._adelete_thread(thread_id),
                loop
            )
            future.result(timeout=10)
        else:
            asyncio.run(self._adelete_thread(thread_id))

    # =========================================================================
    # 异步实现
    # =========================================================================

    async def _aget_tuple(self, config: dict) -> Optional[CheckpointTuple]:
        """异步获取检查点"""
        thread_id = config["configurable"]["thread_id"]
        checkpoint_ns = config.get("configurable", {}).get("checkpoint_ns", "")
        checkpoint_id = config.get("configurable", {}).get("checkpoint_id")

        engine = get_engine()
        async with engine.begin() as conn:
            if checkpoint_id:
                result = await conn.execute(
                    text("""
                        SELECT thread_id, checkpoint_ns, checkpoint_id,
                               parent_checkpoint_id, type, checkpoint, metadata
                        FROM checkpoints
                        WHERE thread_id = :tid AND checkpoint_ns = :ns
                          AND checkpoint_id = :cid
                    """),
                    {"tid": thread_id, "ns": checkpoint_ns, "cid": checkpoint_id}
                )
            else:
                result = await conn.execute(
                    text("""
                        SELECT thread_id, checkpoint_ns, checkpoint_id,
                               parent_checkpoint_id, type, checkpoint, metadata
                        FROM checkpoints
                        WHERE thread_id = :tid AND checkpoint_ns = :ns
                        ORDER BY created_at DESC
                        LIMIT 1
                    """),
                    {"tid": thread_id, "ns": checkpoint_ns}
                )

            row = result.fetchone()
            if not row:
                return None

            # 反序列化
            checkpoint = _serializer.loads_typed((row[5], row[4]))
            metadata = {}
            if row[6]:
                meta_val = _serializer.loads_typed((row[6], row[4]))
                if isinstance(meta_val, dict):
                    metadata = meta_val

            parent_config = None
            if row[3]:
                parent_config = {
                    "configurable": {
                        "thread_id": row[0],
                        "checkpoint_ns": row[1],
                        "checkpoint_id": row[3],
                    }
                }

            return CheckpointTuple(
                config={
                    "configurable": {
                        "thread_id": row[0],
                        "checkpoint_ns": row[1],
                        "checkpoint_id": row[2],
                    }
                },
                checkpoint=checkpoint,
                metadata=metadata,
                parent_config=parent_config,
            )

    async def _alist(
        self,
        config: Optional[dict],
        *,
        filter: Optional[dict] = None,
        before: Optional[dict] = None,
        limit: Optional[int] = None,
    ) -> list[CheckpointTuple]:
        """异步列出检查点历史"""
        if not config:
            return []

        thread_id = config["configurable"]["thread_id"]
        checkpoint_ns = config.get("configurable", {}).get("checkpoint_ns", "")

        query = """
            SELECT thread_id, checkpoint_ns, checkpoint_id,
                   parent_checkpoint_id, type, checkpoint, metadata
            FROM checkpoints
            WHERE thread_id = :tid AND checkpoint_ns = :ns
        """
        params = {"tid": thread_id, "ns": checkpoint_ns}

        if before and "checkpoint_id" in before.get("configurable", {}):
            query += " AND checkpoint_id < :before_id"
            params["before_id"] = before["configurable"]["checkpoint_id"]

        query += " ORDER BY created_at DESC"

        if limit:
            query += f" LIMIT {int(limit)}"

        engine = get_engine()
        async with engine.begin() as conn:
            result = await conn.execute(text(query), params)
            rows = result.fetchall()

        tuples = []
        for row in rows:
            checkpoint = _serializer.loads_typed((row[5], row[4]))
            metadata = {}
            if row[6]:
                meta_val = _serializer.loads_typed((row[6], row[4]))
                if isinstance(meta_val, dict):
                    metadata = meta_val

            parent_config = None
            if row[3]:
                parent_config = {
                    "configurable": {
                        "thread_id": row[0],
                        "checkpoint_ns": row[1],
                        "checkpoint_id": row[3],
                    }
                }

            tuples.append(CheckpointTuple(
                config={
                    "configurable": {
                        "thread_id": row[0],
                        "checkpoint_ns": row[1],
                        "checkpoint_id": row[2],
                    }
                },
                checkpoint=checkpoint,
                metadata=metadata,
                parent_config=parent_config,
            ))

        return tuples

    async def _aput(
        self,
        config: dict,
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata,
        new_versions: dict,
    ) -> dict:
        """异步保存检查点"""
        thread_id = config["configurable"]["thread_id"]
        checkpoint_ns = config.get("configurable", {}).get("checkpoint_ns", "")
        checkpoint_id = checkpoint["id"]

        parent_checkpoint_id = config.get("configurable", {}).get("checkpoint_id")

        # 序列化
        type_, checkpoint_blob = _serializer.dumps_typed(checkpoint)
        _, metadata_blob = _serializer.dumps_typed(metadata)

        engine = get_engine()
        async with engine.begin() as conn:
            await conn.execute(
                text("""
                    INSERT INTO checkpoints
                        (thread_id, checkpoint_ns, checkpoint_id,
                         parent_checkpoint_id, type, checkpoint, metadata)
                    VALUES (:tid, :ns, :cid, :pid, :type, :cp, :meta)
                    ON DUPLICATE KEY UPDATE
                        parent_checkpoint_id = VALUES(parent_checkpoint_id),
                        type = VALUES(type),
                        checkpoint = VALUES(checkpoint),
                        metadata = VALUES(metadata)
                """),
                {
                    "tid": thread_id,
                    "ns": checkpoint_ns,
                    "cid": checkpoint_id,
                    "pid": parent_checkpoint_id,
                    "type": type_,
                    "cp": checkpoint_blob,
                    "meta": metadata_blob,
                }
            )

        return {
            "configurable": {
                "thread_id": thread_id,
                "checkpoint_ns": checkpoint_ns,
                "checkpoint_id": checkpoint_id,
            }
        }

    async def _aput_writes(
        self,
        config: dict,
        writes: list,
        task_id: str,
    ) -> None:
        """异步保存待处理写入"""
        thread_id = config["configurable"]["thread_id"]
        checkpoint_ns = config.get("configurable", {}).get("checkpoint_ns", "")
        checkpoint_id = config.get("configurable", {}).get("checkpoint_id", "")

        engine = get_engine()
        async with engine.begin() as conn:
            for idx, (channel, value) in enumerate(writes):
                type_, blob = _serializer.dumps_typed(value)
                await conn.execute(
                    text("""
                        INSERT INTO checkpoint_writes
                            (thread_id, checkpoint_ns, checkpoint_id,
                             task_id, idx, channel, type, value)
                        VALUES (:tid, :ns, :cid, :task, :idx, :ch, :type, :val)
                        ON DUPLICATE KEY UPDATE
                            type = VALUES(type),
                            value = VALUES(value)
                    """),
                    {
                        "tid": thread_id,
                        "ns": checkpoint_ns,
                        "cid": checkpoint_id,
                        "task": task_id,
                        "idx": idx,
                        "ch": channel,
                        "type": type_,
                        "val": blob,
                    }
                )

    async def _adelete_thread(self, thread_id: str) -> None:
        """异步删除整个会话的检查点"""
        engine = get_engine()
        async with engine.begin() as conn:
            await conn.execute(
                text("DELETE FROM checkpoint_writes WHERE thread_id = :tid"),
                {"tid": thread_id}
            )
            await conn.execute(
                text("DELETE FROM checkpoints WHERE thread_id = :tid"),
                {"tid": thread_id}
            )
        logger.info(f"Deleted checkpoint data for thread: {thread_id}")
