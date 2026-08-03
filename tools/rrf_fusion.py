"""RRF (Reciprocal Rank Fusion) 倒数排名融合

将多条检索路径的结果合并为统一排名。

公式：
    RRF_score(d) = Σ 1 / (k + rank_i(d))

其中：
    - k = 60（标准常数，平滑低排名项的权重）
    - rank_i(d) = 文档 d 在第 i 条检索路径中的排名（从 1 开始）

优点：
    - 不依赖各路径的原始分数分布（余弦相似度 vs BM25 分数的量纲差异被消除）
    - 简单高效，工业界广泛使用

使用方式：
    from tools.rrf_fusion import rrf_fuse, rrf_fuse_from_results

    fused = rrf_fuse(
        paths=[
            [{"content": "...", "score": 0.9}, {"content": "...", "score": 0.7}],
            [{"content": "...", "score": 0.8}, {"content": "...", "score": 0.6}],
        ],
        top_k=5,
    )
"""

import hashlib


# =============================================================================
# 配置
# =============================================================================

DEFAULT_RRF_K = 60


# =============================================================================
# 文档去重 key
# =============================================================================

def _doc_key(doc: dict) -> str:
    """为文档生成去重 key。

    优先使用 content 的 SHA256 前 32 位，避免全文比较。
    两路检索可能返回同一文档的不同副本（向量路 vs BM25 路），
    需要去重以避免同一文档在 RRF 中获得双重权重。
    """
    content = doc.get("content", "")
    if content:
        return hashlib.sha256(content.encode("utf-8")).hexdigest()[:32]
    # fallback: 用 metadata 中的 category+tags 组合
    meta = doc.get("metadata", {})
    return f"{meta.get('category', '')}:{meta.get('city', '')}:{meta.get('tags', '')}"


# =============================================================================
# RRF 融合
# =============================================================================


def rrf_fuse(
    paths: list[list[dict]],
    top_k: int = 5,
    k: int = DEFAULT_RRF_K,
) -> list[dict]:
    """RRF 多路召回融合。

    对每条路径按原始顺序计算排名（排名从 1 开始），
    累加各路径的 RRF 贡献值，按总分降序返回 Top-K。

    Args:
        paths: 各条检索路径的结果列表（每条路径已按原始分数降序排列）。
               每个元素为 [{"content": str, "score": float, "metadata": dict, "source": str}, ...]
        top_k: 返回结果数量。
        k:     RRF 平滑常数（默认 60）。

    Returns:
        融合后的 Top-K 文档，每项附带 RRF 得分：
        [{"content": str, "score": float, "metadata": dict, "sources": [str, ...]}, ...]
    """
    # 按 (content_hash) 聚合 RRF 得分
    rrf_scores: dict[str, float] = {}
    doc_store: dict[str, dict] = {}       # key → 最佳文档内容
    source_sets: dict[str, set[str]] = {}  # key → 来源路径集合

    for path_idx, path_results in enumerate(paths):
        if not path_results:
            continue
        source_tag = path_results[0].get("source", f"path_{path_idx}") if path_results else f"path_{path_idx}"

        for rank, doc in enumerate(path_results, start=1):
            key = _doc_key(doc)
            contribution = 1.0 / (k + rank)
            rrf_scores[key] = rrf_scores.get(key, 0.0) + contribution

            # 保留 content 较长（更完整）的副本
            if key not in doc_store or len(doc.get("content", "")) > len(doc_store[key].get("content", "")):
                doc_store[key] = doc

            if key not in source_sets:
                source_sets[key] = set()
            source_sets[key].add(source_tag)

    # 按 RRF 得分降序
    ranked = sorted(rrf_scores.items(), key=lambda x: x[1], reverse=True)

    # 构建输出
    results: list[dict] = []
    for key, rrf_score in ranked[:top_k]:
        doc = doc_store[key]
        results.append({
            "content": doc.get("content", ""),
            "score": round(rrf_score, 6),
            "metadata": doc.get("metadata", {}),
            "sources": sorted(source_sets.get(key, [])),
        })

    return results


def rrf_fuse_from_results(
    vector_results: list[dict],
    bm25_results: list[dict],
    top_k: int = 5,
    k: int = DEFAULT_RRF_K,
) -> list[dict]:
    """便捷函数——融合向量 + BM25 两路检索结果。

    Args:
        vector_results: 向量检索结果（来自 vector_store.search_knowledge）
        bm25_results:   BM25 检索结果（来自 bm25_retriever.search）
        top_k:          返回结果数
        k:              RRF 平滑常数

    Returns:
        融合后的 Top-K 文档
    """
    # 标记来源（如果尚未标记）
    for r in vector_results:
        if "source" not in r:
            r["source"] = "vector"
    for r in bm25_results:
        if "source" not in r:
            r["source"] = "bm25"

    return rrf_fuse([vector_results, bm25_results], top_k=top_k, k=k)
