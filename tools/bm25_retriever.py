"""BM25 关键词检索器——无外部依赖的纯 Python 实现

中英文混合分词策略：
- 英文/数字：按空格切分 + 小写化 + 去除标点
- 中文：字符级 bigram + unigram（无需 jieba 等分词库）

BM25 公式：
    score(q, d) = Σ IDF(qi) × (tf(qi,d) × (k1+1)) / (tf(qi,d) + k1 × (1-b + b×|d|/avgdl))
    IDF(qi) = log((N - n(qi) + 0.5) / (n(qi) + 0.5) + 1)

使用方式：
    from tools.bm25_retriever import get_bm25_retriever
    bm25 = get_bm25_retriever()
    results = bm25.search("签证需要什么材料？", top_k=5)
"""

import math
import re
import logging

logger = logging.getLogger(__name__)

# =============================================================================
# 分词
# =============================================================================

# 中文 Unicode 范围
_CJK_RE = re.compile(r"[一-鿿㐀-䶿豈-﫿]")

# 标点/特殊字符（用于英文 token 清洗）
_PUNCT_RE = re.compile(r"[^\w一-鿿㐀-䶿]")

# 停用词（高频且无区分度的词/字）
_STOP_WORDS = {
    "的", "了", "在", "是", "我", "有", "和", "就", "不", "人", "都", "一",
    "一个", "这", "他", "也", "与", "及", "或", "等", "你", "吗", "呢",
    "啊", "吧", "哦", "嗯", "么", "啦", "哇", "呀", "the", "a", "an",
    "is", "are", "was", "were", "be", "been", "being", "have", "has",
    "had", "do", "does", "did", "will", "would", "could", "should",
    "may", "might", "can", "shall", "to", "of", "in", "for", "on",
    "with", "at", "by", "from", "as", "into", "through", "during",
    "before", "after", "above", "below", "between", "under", "again",
    "further", "then", "once", "here", "there", "when", "where", "why",
    "how", "all", "both", "each", "few", "more", "most", "other",
    "some", "such", "only", "own", "same", "so", "than", "too",
    "very", "just", "because", "but", "however", "also", "it", "its",
}


def tokenize(text: str) -> list[str]:
    """中英文混合分词。

    中文 → 字符级 unigram + bigram
    英文 → 空格分词 + 小写化 → 去停用词

    Args:
        text: 待分词文本

    Returns:
        token 列表
    """
    if not text:
        return []

    tokens: list[str] = []

    # Step 1: 按空格初步切分
    segments = text.split()

    for seg in segments:
        # 提取中文部分
        cjk_chars: list[str] = _CJK_RE.findall(seg)
        # 提取非中文部分（英文/数字）
        non_cjk = _CJK_RE.sub(" ", seg).strip()

        # 中文 → unigram + bigram
        if len(cjk_chars) >= 1:
            for ch in cjk_chars:
                if ch not in _STOP_WORDS:
                    tokens.append(ch)
            for i in range(len(cjk_chars) - 1):
                bigram = cjk_chars[i] + cjk_chars[i + 1]
                tokens.append(bigram)

        # 英文/数字 → 小写化 → 去标点 → 去停用词
        if non_cjk:
            sub_tokens = non_cjk.lower().split()
            for t in sub_tokens:
                t = _PUNCT_RE.sub("", t)
                if t and t not in _STOP_WORDS and len(t) >= 2:
                    tokens.append(t)

    return tokens


# =============================================================================
# BM25Retriever
# =============================================================================


class BM25Retriever:
    """BM25 检索器。

    索引构建后，search() 返回按 BM25 得分降序排列的结果。
    """

    def __init__(self, k1: float = 1.5, b: float = 0.75):
        """
        Args:
            k1: 词频饱和参数（默认 1.5，范围 [1.2, 2.0]）
            b:  文档长度归一化参数（默认 0.75，范围 [0, 1]）
        """
        self.k1 = k1
        self.b = b

        # 索引数据
        self._doc_texts: list[str] = []      # 原始文本
        self._doc_meta: list[dict] = []      # metadata
        self._doc_tokens: list[list[str]] = []  # 分词后的 token 列表
        self._doc_len: list[int] = []        # 每篇文档的 token 数
        self._avgdl: float = 0.0             # 平均文档长度
        self._idf: dict[str, float] = {}     # token → IDF 值
        self._built: bool = False

    # -------------------------------------------------------------------------
    # 索引构建
    # -------------------------------------------------------------------------

    def index(self, documents: list[dict]) -> int:
        """构建 BM25 索引。

        Args:
            documents: [{"content": "...", "metadata": {...}}, ...]

        Returns:
            索引的文档数量
        """
        if not documents:
            self._built = True
            return 0

        self._doc_texts = [d.get("content", "") for d in documents]
        self._doc_meta = [d.get("metadata", {}) for d in documents]
        self._doc_tokens = [tokenize(text) for text in self._doc_texts]
        self._doc_len = [len(tokens) for tokens in self._doc_tokens]
        self._avgdl = sum(self._doc_len) / max(len(self._doc_tokens), 1)

        # 构建 IDF
        n = len(self._doc_tokens)
        df: dict[str, int] = {}
        for tokens in self._doc_tokens:
            seen: set[str] = set()
            for token in tokens:
                if token not in seen:
                    df[token] = df.get(token, 0) + 1
                    seen.add(token)

        self._idf = {}
        for token, freq in df.items():
            self._idf[token] = math.log((n - freq + 0.5) / (freq + 0.5) + 1)

        self._built = True
        logger.info(
            "BM25 index built: %d docs, avg_len=%.1f, vocab=%d",
            n, self._avgdl, len(self._idf),
        )
        return n

    # -------------------------------------------------------------------------
    # 检索
    # -------------------------------------------------------------------------

    def search(self, query: str, top_k: int = 10) -> list[dict]:
        """BM25 检索。

        Args:
            query:  用户查询文本
            top_k:  返回结果数

        Returns:
            [{"content": "...", "score": 0.85, "metadata": {...}, "source": "bm25"}, ...]
            得分已归一化到 [0, 1] 区间
        """
        if not self._built:
            return []

        query_tokens = tokenize(query)
        if not query_tokens:
            return []

        scored: list[tuple[int, float]] = []
        for idx, doc_tokens in enumerate(self._doc_tokens):
            score = self._score(query_tokens, doc_tokens, idx)
            if score > 0:
                scored.append((idx, score))

        # 按得分降序
        scored.sort(key=lambda x: x[1], reverse=True)

        # 不归一化——保留原始 BM25 分数以便后续阈值过滤
        results: list[dict] = []
        for idx, raw_score in scored[:top_k]:
            results.append({
                "content": self._doc_texts[idx],
                "score": round(raw_score, 4),
                "metadata": self._doc_meta[idx],
                "source": "bm25",
            })

        return results

    def _score(self, query_tokens: list[str], doc_tokens: list[str], doc_idx: int) -> float:
        """计算单个文档的 BM25 得分。"""
        dl = self._doc_len[doc_idx]
        score = 0.0

        for token in query_tokens:
            idf = self._idf.get(token, 0.0)
            if idf == 0.0:
                continue

            tf = doc_tokens.count(token)
            if tf == 0:
                continue

            numerator = tf * (self.k1 + 1)
            denominator = tf + self.k1 * (1 - self.b + self.b * dl / max(self._avgdl, 1.0))
            score += idf * numerator / denominator

        return score

    @property
    def doc_count(self) -> int:
        return len(self._doc_texts)


# =============================================================================
# 模块级单例
# =============================================================================

_bm25_instance: BM25Retriever | None = None


def get_bm25_retriever() -> BM25Retriever:
    """获取 BM25 检索器单例。

    首次调用时自动从知识库文档构建索引。
    """
    global _bm25_instance
    if _bm25_instance is None:
        _bm25_instance = BM25Retriever()
        try:
            from scripts.knowledge_base import FAQ_DOCS, CITY_DOCS
            docs = FAQ_DOCS + CITY_DOCS
            _bm25_instance.index(docs)
        except Exception as e:
            logger.warning("BM25 index build failed: %s", e)
    return _bm25_instance


def reset_bm25() -> None:
    """重置 BM25 索引（测试用）。"""
    global _bm25_instance
    _bm25_instance = None
