"""Milvus 向量存储——语义检索后端

基于 Milvus 单机部署的向量检索服务，替代旧版 JSON+余弦相似度方案。
使用 pymilvus SDK 直连，零 LangChain 包装依赖。

使用方式：
    from services.vector_store import search_knowledge, add_documents, get_collection_stats

    results = search_knowledge("签证需要什么材料？", top_k=3)
    n = add_documents([{"content": "...", "metadata": {...}}, ...])
"""

import os
import logging
from pymilvus import (
    connections,
    Collection,
    FieldSchema,
    CollectionSchema,
    DataType,
    utility,
)
from services.embeddings import embed_text, embed_texts, get_embedding_dim

logger = logging.getLogger(__name__)

# =============================================================================
# 配置
# =============================================================================

_COLLECTION_NAME: str | None = None
_COLLECTION: Collection | None = None
_initialized: bool = False


def _get_config():
    """获取 Milvus 配置"""
    return {
        "host": os.getenv("MILVUS_HOST", "milvus-standalone"),
        "port": os.getenv("MILVUS_PORT", "19530"),
        "collection": os.getenv("MILVUS_COLLECTION", "travel_knowledge"),
    }


# =============================================================================
# 连接管理
# =============================================================================


def init_milvus():
    """初始化 Milvus 连接 + 确保 Collection 存在（同步，应用启动时调用一次）"""
    global _COLLECTION, _COLLECTION_NAME, _initialized

    config = _get_config()
    _COLLECTION_NAME = config["collection"]
    dim = get_embedding_dim()

    logger.info(f"Connecting to Milvus at {config['host']}:{config['port']}")

    try:
        # 断开已有连接（如有）
        if connections.has_connection("default"):
            connections.disconnect("default")

        connections.connect(
            alias="default",
            host=config["host"],
            port=config["port"],
            timeout=10,
        )
        logger.info("Milvus connection established")

        # 确保 Collection 存在
        if utility.has_collection(_COLLECTION_NAME):
            _COLLECTION = Collection(_COLLECTION_NAME)
            _COLLECTION.load()
            logger.info(f"Collection '{_COLLECTION_NAME}' loaded (dim={dim}, count={_COLLECTION.num_entities})")
        else:
            _COLLECTION = _create_collection(dim)
            logger.info(f"Collection '{_COLLECTION_NAME}' created (dim={dim})")

        _initialized = True

    except Exception as e:
        logger.warning(f"Milvus connection failed (will retry on first use): {e}")
        _initialized = False


def _create_collection(dim: int) -> Collection:
    """创建知识库 Collection

    Schema:
        id: int64 (主键, 自增)
        content: varchar (文档内容, 最大 65535 字符)
        embedding: float_vector (向量, 维度由 embedding 模型决定)
        category: varchar (分类标签)
        tags: varchar (标签, 逗号分隔)
    """
    config = _get_config()

    fields = [
        FieldSchema(name="id", dtype=DataType.INT64, is_primary=True, auto_id=True),
        FieldSchema(name="content", dtype=DataType.VARCHAR, max_length=65535),
        FieldSchema(name="embedding", dtype=DataType.FLOAT_VECTOR, dim=dim),
        FieldSchema(name="category", dtype=DataType.VARCHAR, max_length=128),
        FieldSchema(name="tags", dtype=DataType.VARCHAR, max_length=512),
    ]

    schema = CollectionSchema(
        fields=fields,
        description="入境定制游知识库——FAQ + 城市指南",
        enable_dynamic_field=False,
    )

    collection = Collection(name=config["collection"], schema=schema)

    # 创建索引：HNSW（高召回、适合中小规模）
    index_params = {
        "metric_type": "COSINE",
        "index_type": "HNSW",
        "params": {"M": 16, "efConstruction": 200},
    }
    collection.create_index(field_name="embedding", index_params=index_params)
    collection.load()

    return collection


def close_milvus():
    """断开 Milvus 连接（应用关闭时调用）"""
    global _COLLECTION, _initialized
    try:
        if connections.has_connection("default"):
            connections.disconnect("default")
        _COLLECTION = None
        _initialized = False
        logger.info("Milvus connection closed")
    except Exception:
        pass


def _get_collection() -> Collection:
    """获取 Collection 实例（自动重连）"""
    global _COLLECTION, _initialized
    if not _initialized or _COLLECTION is None:
        init_milvus()
    if _COLLECTION is None:
        raise RuntimeError("Milvus not available. Check Milvus connection settings.")
    return _COLLECTION


# =============================================================================
# 检索 API
# =============================================================================


def search_knowledge(query: str, top_k: int = 3, score_threshold: float = 0.3) -> list[dict]:
    """语义检索知识库

    流程：
    1. 用 text-embedding-v4 向量化查询
    2. Milvus HNSW 索引检索 top_k 个最相似文档
    3. 过滤低于阈值的低分结果

    Args:
        query: 用户问题文本
        top_k: 返回文档数量
        score_threshold: 最低相似度阈值（COSINE 距离, 0.3 ≈ 相关性很低）

    Returns:
        [{"content": "文档内容", "score": 0.85, "metadata": {...}}, ...]
    """
    try:
        collection = _get_collection()
        query_vector = embed_text(query)

        search_params = {"metric_type": "COSINE", "params": {"ef": 64}}
        results = collection.search(
            data=[query_vector],
            anns_field="embedding",
            param=search_params,
            limit=top_k * 2,  # 请求 2x 以便过滤后仍有足够结果
            output_fields=["content", "category", "tags"],
        )

        hits = []
        for result in results[0]:
            score = result.distance  # COSINE 相似度 [0, 1]
            if score >= score_threshold:
                entity = result.entity
                hits.append({
                    "content": entity.get("content", ""),
                    "score": round(score, 4),
                    "metadata": {
                        "category": entity.get("category", ""),
                        "tags": entity.get("tags", ""),
                    },
                })

        return hits[:top_k]

    except Exception as e:
        logger.error(f"Milvus search error: {e}")
        return []


# =============================================================================
# 写入 API
# =============================================================================


def add_documents(docs: list[dict]) -> int:
    """向知识库批量添加文档（自动向量化）

    Args:
        docs: [{"content": "文档内容", "metadata": {"category": "签证", "tags": "..."}}, ...]

    Returns:
        成功添加的文档数
    """
    if not docs:
        return 0

    try:
        collection = _get_collection()

        # 批量向量化
        contents = [d.get("content", "") for d in docs if d.get("content")]
        if not contents:
            return 0

        vectors = embed_texts(contents)

        # 准备插入数据
        insert_contents = []
        insert_vectors = []
        insert_categories = []
        insert_tags = []

        for i, doc in enumerate(docs):
            content = doc.get("content", "")
            if not content or i >= len(vectors):
                continue
            meta = doc.get("metadata", {})
            insert_contents.append(content)
            insert_vectors.append(vectors[i])
            insert_categories.append(str(meta.get("category", ""))[:128])
            insert_tags.append(str(meta.get("tags", ""))[:512])

        if not insert_contents:
            return 0

        # 批量插入
        collection.insert([insert_contents, insert_vectors, insert_categories, insert_tags])
        collection.flush()

        return len(insert_contents)

    except Exception as e:
        logger.error(f"Milvus add_documents error: {e}")
        return 0


# =============================================================================
# 统计 API
# =============================================================================


def get_collection_stats() -> dict:
    """获取知识库统计信息

    Returns:
        {"count": 文档数, "name": Collection 名称, "host": Milvus 地址}
    """
    config = _get_config()
    try:
        collection = _get_collection()
        return {
            "count": collection.num_entities,
            "name": config["collection"],
            "host": f"{config['host']}:{config['port']}",
            "backend": "Milvus",
        }
    except Exception:
        return {
            "count": 0,
            "name": config["collection"],
            "host": f"{config['host']}:{config['port']}",
            "backend": "Milvus (disconnected)",
        }
