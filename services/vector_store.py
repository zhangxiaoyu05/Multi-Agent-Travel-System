"""轻量向量存储——JSON 持久化 + 百炼 Embedding

纯 Python 实现，零额外依赖（仅使用 Python 标准库 + 已有的 langchain-openai）。
使用百炼 Embedding API 做向量化，本地 JSON 文件持久化。

使用方式：
    from services.vector_store import get_vector_store, search_knowledge

    store = get_vector_store()       # 懒加载，首次自动初始化
    results = search_knowledge("签证需要什么材料？", top_k=3)
"""

import os
import json
import math
from services.embeddings import embed_text, embed_texts

# 向量数据库持久化路径
_VECTOR_DB_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
_VECTOR_FILE = os.path.join(_VECTOR_DB_DIR, "vector_store.json")

# 模块级缓存
_store: dict | None = None  # {"documents": [...], "embeddings": [...]}


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """纯 Python 余弦相似度计算

    Args:
        a: 向量 A
        b: 向量 B

    Returns:
        余弦相似度 (0.0-1.0)
    """
    dot_product = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))

    if norm_a == 0 or norm_b == 0:
        return 0.0

    return dot_product / (norm_a * norm_b)


def get_vector_store() -> dict:
    """获取向量存储实例（懒加载，从 JSON 文件读取）

    Returns:
        {"documents": [...], "embeddings": [...]}
    """
    global _store
    if _store is None:
        os.makedirs(_VECTOR_DB_DIR, exist_ok=True)
        if os.path.exists(_VECTOR_FILE):
            try:
                with open(_VECTOR_FILE, "r", encoding="utf-8") as f:
                    _store = json.load(f)
            except (json.JSONDecodeError, IOError):
                _store = {"documents": [], "embeddings": []}
        else:
            _store = {"documents": [], "embeddings": []}
    return _store


def _save_store():
    """持久化向量存储到 JSON 文件"""
    global _store
    if _store is not None:
        os.makedirs(_VECTOR_DB_DIR, exist_ok=True)
        with open(_VECTOR_FILE, "w", encoding="utf-8") as f:
            json.dump(_store, f, ensure_ascii=False, indent=2)


def search_knowledge(query: str, top_k: int = 3, score_threshold: float = 0.3) -> list[dict]:
    """在知识库中检索与 query 最相关的文档

    流程：
    1. 用百炼 Embedding 向量化查询文本
    2. 与知识库中所有文档向量计算余弦相似度
    3. 排序返回 top_k 个结果

    Args:
        query: 用户问题文本
        top_k: 返回文档数量
        score_threshold: 最低相似度阈值（低于此值的文档不返回）

    Returns:
        [{"content": "文档内容", "score": 0.85, "metadata": {...}}, ...]
    """
    store = get_vector_store()
    documents = store.get("documents", [])
    embeddings = store.get("embeddings", [])

    if not documents:
        return []

    try:
        # Step 1: 向量化查询
        query_vector = embed_text(query)

        # Step 2: 计算所有文档的余弦相似度
        scores = []
        for i, doc_vec in enumerate(embeddings):
            score = _cosine_similarity(query_vector, doc_vec)
            if score >= score_threshold:
                scores.append((i, score))

        # Step 3: 排序取 top-k
        scores.sort(key=lambda x: x[1], reverse=True)
        top_results = scores[:top_k]

        # Step 4: 构建结果
        results = []
        for idx, score in top_results:
            doc = documents[idx]
            results.append({
                "content": doc.get("content", ""),
                "score": round(score, 4),
                "metadata": doc.get("metadata", {}),
            })

        return results

    except Exception as e:
        print(f"[RAG] Vector search error: {e}")
        return []


def add_documents(docs: list[dict]) -> int:
    """向知识库添加文档（自动向量化 + 持久化）

    Args:
        docs: [{"content": "文档内容", "metadata": {"category": "签证", ...}}, ...]

    Returns:
        成功添加的文档数量
    """
    store = get_vector_store()
    documents = store.get("documents", [])
    embeddings = store.get("embeddings", [])

    if not docs:
        return 0

    try:
        # 批量向量化（比逐条调用快）
        contents = [d["content"] for d in docs if d.get("content")]
        if not contents:
            return 0

        vectors = embed_texts(contents)
        added = 0

        for doc in docs:
            content = doc.get("content", "")
            if not content:
                continue

            # 获取对应的向量
            vector = vectors[added] if added < len(vectors) else embed_text(content)

            # 存储
            documents.append({"content": content, "metadata": doc.get("metadata", {})})
            embeddings.append(vector)
            added += 1

        store["documents"] = documents
        store["embeddings"] = embeddings
        _save_store()

        return added

    except Exception as e:
        print(f"[RAG] Add documents error: {e}")
        return 0


def get_collection_stats() -> dict:
    """获取知识库统计信息

    Returns:
        {"count": 文档总数, "path": 存储路径}
    """
    store = get_vector_store()
    return {
        "count": len(store.get("documents", [])),
        "path": _VECTOR_FILE,
    }
