"""向量存储——Milvus + JSON 双模式

自动选择后端：
- Milvus 可用 → 使用 Milvus REST API（生产模式）
- Milvus 不可用 → 使用 JSON 文件 + 余弦相似度（开发/回退模式）

使用方式：
    from services.vector_store import search_knowledge, add_documents, get_collection_stats
"""

import os
import json
import math
import logging
import httpx
from services.embeddings import embed_text, embed_texts, get_embedding_dim

logger = logging.getLogger(__name__)

# =============================================================================
# 配置
# =============================================================================

_JSON_DB_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
_JSON_FILE = os.path.join(_JSON_DB_DIR, "vector_store.json")
_json_store: dict | None = None  # {"documents": [...], "embeddings": [...]}

_backend: str | None = None  # "milvus" | "json" | None (未检测)


def _get_milvus_config():
    return {
        "host": os.getenv("MILVUS_HOST", "milvus-standalone"),
        "port": os.getenv("MILVUS_PORT", "19530"),
        "collection": os.getenv("MILVUS_COLLECTION", "travel_knowledge"),
    }


def _milvus_url(path: str = "") -> str:
    c = _get_milvus_config()
    return f"http://{c['host']}:{c['port']}/api/v1{path}"


# =============================================================================
# 后端检测
# =============================================================================


def _detect_backend() -> str:
    """检测可用的后端：Milvus REST → JSON fallback"""
    global _backend

    if _backend is not None:
        return _backend

    # 尝试 Milvus
    try:
        resp = httpx.get(
            _milvus_url("/collection/list"),
            timeout=5,
        )
        if resp.status_code == 200:
            _backend = "milvus"
            logger.info("Vector backend: Milvus REST API")
            return _backend
    except Exception:
        pass

    # 回退到 JSON
    _backend = "json"
    logger.info("Vector backend: JSON file (Milvus unavailable)")
    return _backend


# =============================================================================
# 初始化
# =============================================================================


def init_milvus():
    """初始化向量存储（自动检测后端）"""
    backend = _detect_backend()

    if backend == "milvus":
        _init_milvus_backend()
    else:
        _init_json_backend()


def _init_milvus_backend():
    """通过 REST API 初始化 Milvus Collection"""
    config = _get_milvus_config()
    dim = get_embedding_dim()
    collection_name = config["collection"]

    try:
        # 检查 Collection 是否存在
        resp = httpx.post(
            _milvus_url("/collection/describe"),
            json={"collectionName": collection_name},
            timeout=10,
        )

        if resp.status_code == 200:
            # 加载到内存
            httpx.post(
                _milvus_url("/collection/load"),
                json={"collectionName": collection_name},
                timeout=10,
            )
            logger.info(f"Milvus collection '{collection_name}' loaded (dim={dim})")
        else:
            # 创建 Collection
            httpx.post(
                _milvus_url("/collection/create"),
                json={
                    "collectionName": collection_name,
                    "dimension": dim,
                    "metricType": "COSINE",
                    "primaryField": "id",
                    "vectorField": "embedding",
                    "schema": {
                        "fields": [
                            {"name": "id", "dataType": "Int64", "isPrimary": True, "autoID": True},
                            {"name": "content", "dataType": "VarChar",
                             "elementTypeParams": {"max_length": "65535"}},
                            {"name": "embedding", "dataType": "FloatVector",
                             "elementTypeParams": {"dim": str(dim)}},
                            {"name": "category", "dataType": "VarChar",
                             "elementTypeParams": {"max_length": "128"}},
                            {"name": "tags", "dataType": "VarChar",
                             "elementTypeParams": {"max_length": "512"}},
                        ]
                    }
                },
                timeout=30,
            )
            # 创建索引
            httpx.post(
                _milvus_url("/index/create"),
                json={
                    "collectionName": collection_name,
                    "indexParams": [{
                        "fieldName": "embedding",
                        "indexName": "embedding_idx",
                        "metricType": "COSINE",
                        "indexType": "HNSW",
                        "params": '{"M": 16, "efConstruction": 200}',
                    }]
                },
                timeout=30,
            )
            # 加载
            httpx.post(
                _milvus_url("/collection/load"),
                json={"collectionName": collection_name},
                timeout=30,
            )
            logger.info(f"Milvus collection '{collection_name}' created (dim={dim})")

    except Exception as e:
        logger.warning(f"Milvus init failed, using JSON fallback: {e}")
        global _backend
        _backend = "json"
        _init_json_backend()


def _init_json_backend():
    """初始化 JSON 文件存储"""
    global _json_store
    os.makedirs(_JSON_DB_DIR, exist_ok=True)
    if os.path.exists(_JSON_FILE):
        try:
            with open(_JSON_FILE, "r", encoding="utf-8") as f:
                _json_store = json.load(f)
        except (json.JSONDecodeError, IOError):
            _json_store = {"documents": [], "embeddings": []}
    else:
        _json_store = {"documents": [], "embeddings": []}


def _save_json():
    """持久化 JSON 存储"""
    global _json_store
    if _json_store is not None:
        os.makedirs(_JSON_DB_DIR, exist_ok=True)
        with open(_JSON_FILE, "w", encoding="utf-8") as f:
            json.dump(_json_store, f, ensure_ascii=False, indent=2)


def close_milvus():
    """释放资源"""
    pass


# =============================================================================
# 检索 API
# =============================================================================


def search_knowledge(query: str, top_k: int = 3, score_threshold: float = 0.3) -> list[dict]:
    """语义检索知识库

    Args:
        query: 用户问题文本
        top_k: 返回文档数量
        score_threshold: 最低相似度阈值

    Returns:
        [{"content": "...", "score": 0.85, "metadata": {...}}, ...]
    """
    backend = _detect_backend()

    if backend == "milvus":
        return _search_milvus(query, top_k, score_threshold)
    else:
        return _search_json(query, top_k, score_threshold)


def _search_milvus(query: str, top_k: int, score_threshold: float) -> list[dict]:
    """Milvus REST API 检索"""
    config = _get_milvus_config()
    try:
        query_vector = embed_text(query)
        resp = httpx.post(
            _milvus_url("/search"),
            json={
                "collectionName": config["collection"],
                "vector": query_vector,
                "limit": top_k * 2,
                "outputFields": ["content", "category", "tags"],
                "params": '{"ef": 64}',
            },
            timeout=30,
        )
        if resp.status_code != 200:
            return []

        data = resp.json()
        results = data.get("results", data if isinstance(data, dict) else [data])
        results = results if isinstance(results, list) else [results]

        hits = []
        for item in results:
            score = item.get("score", item.get("distance", 0))
            if score >= score_threshold:
                hits.append({
                    "content": item.get("content", ""),
                    "score": round(float(score), 4),
                    "metadata": {
                        "category": item.get("category", ""),
                        "tags": item.get("tags", ""),
                    },
                })
        return hits[:top_k]
    except Exception as e:
        logger.error(f"Milvus search error: {e}")
        return _search_json(query, top_k, score_threshold)


def _search_json(query: str, top_k: int, score_threshold: float) -> list[dict]:
    """JSON 文件 + 余弦相似度检索"""
    global _json_store
    if _json_store is None:
        _init_json_backend()

    docs = _json_store.get("documents", [])
    embs = _json_store.get("embeddings", [])

    if not docs:
        return []

    try:
        qv = embed_text(query)
        scored = []
        for i, dv in enumerate(embs):
            dot = sum(x * y for x, y in zip(qv, dv))
            na = math.sqrt(sum(x * x for x in qv))
            nb = math.sqrt(sum(x * x for x in dv))
            if na == 0 or nb == 0:
                continue
            s = dot / (na * nb)
            if s >= score_threshold:
                scored.append((i, s))

        scored.sort(key=lambda x: x[1], reverse=True)
        results = []
        for idx, score in scored[:top_k]:
            doc = docs[idx]
            results.append({
                "content": doc.get("content", ""),
                "score": round(score, 4),
                "metadata": doc.get("metadata", {}),
            })
        return results
    except Exception as e:
        logger.error(f"JSON search error: {e}")
        return []


# =============================================================================
# 写入 API
# =============================================================================


def add_documents(docs: list[dict]) -> int:
    """批量添加文档"""
    backend = _detect_backend()

    if backend == "milvus":
        return _add_milvus(docs)
    else:
        return _add_json(docs)


def _add_milvus(docs: list[dict]) -> int:
    """Milvus REST API 批量插入"""
    config = _get_milvus_config()
    try:
        contents = [d.get("content", "") for d in docs if d.get("content")]
        if not contents:
            return 0
        vectors = embed_texts(contents)

        data_rows = []
        for i, doc in enumerate(docs):
            content = doc.get("content", "")
            if not content or i >= len(vectors):
                continue
            meta = doc.get("metadata", {})
            data_rows.append({
                "content": content,
                "embedding": vectors[i],
                "category": str(meta.get("category", ""))[:128],
                "tags": str(meta.get("tags", ""))[:512],
            })
        if not data_rows:
            return 0

        resp = httpx.post(
            _milvus_url("/entities/insert"),
            json={"collectionName": config["collection"], "data": data_rows},
            timeout=60,
        )
        return len(data_rows) if resp.status_code == 200 else 0
    except Exception as e:
        logger.warning(f"Milvus insert failed, using JSON: {e}")
        return _add_json(docs)


def _add_json(docs: list[dict]) -> int:
    """JSON 文件批量添加"""
    global _json_store
    if _json_store is None:
        _init_json_backend()

    try:
        contents = [d["content"] for d in docs if d.get("content")]
        if not contents:
            return 0
        vectors = embed_texts(contents)

        added = 0
        for doc in docs:
            content = doc.get("content", "")
            if not content or added >= len(vectors):
                continue
            _json_store["documents"].append({
                "content": content,
                "metadata": doc.get("metadata", {}),
            })
            _json_store["embeddings"].append(vectors[added])
            added += 1

        _save_json()
        return added
    except Exception as e:
        logger.error(f"JSON add error: {e}")
        return 0


# =============================================================================
# 统计 API
# =============================================================================


def get_collection_stats() -> dict:
    """获取知识库统计信息"""
    backend = _detect_backend()

    if backend == "milvus":
        config = _get_milvus_config()
        try:
            resp = httpx.post(
                _milvus_url("/collection/describe"),
                json={"collectionName": config["collection"]},
                timeout=5,
            )
            if resp.status_code == 200:
                data = resp.json()
                return {
                    "count": data.get("numEntities", data.get("num_entities", 0)),
                    "name": config["collection"],
                    "host": f"{config['host']}:{config['port']}",
                    "backend": "Milvus REST",
                }
        except Exception:
            pass

    # JSON backend
    global _json_store
    if _json_store is None:
        _init_json_backend()
    count = len(_json_store.get("documents", [])) if _json_store else 0
    return {
        "count": count,
        "name": "vector_store.json",
        "host": "local",
        "backend": "JSON file",
    }
