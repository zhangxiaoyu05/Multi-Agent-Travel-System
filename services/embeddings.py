"""Embedding 工厂——阿里百炼 DashScope 原生 API

直接调用 DashScope text-embedding API，避免 OpenAI 兼容模式的不兼容问题。

使用方式：
    from services.embeddings import embed_text, embed_texts

    vec = embed_text("签证需要什么材料？")  # → list[float]
    vecs = embed_texts(["文本1", "文本2"])  # → list[list[float]]
"""

import os
import httpx


# 百炼 DashScope Embedding API 地址
_DASHSCOPE_EMBED_URL = (
    "https://dashscope.aliyuncs.com/api/v1/services/embeddings/text-embedding/text-embedding"
)

# 模块级缓存
_api_key: str | None = None


def _get_api_key() -> str:
    """获取 API Key（懒加载环境变量）"""
    global _api_key
    if _api_key is None:
        from dotenv import load_dotenv
        load_dotenv()
        _api_key = os.getenv("LLM_API_KEY", "sk-placeholder")
    return _api_key


def embed_text(text: str, model: str | None = None) -> list[float]:
    """将单个文本转换为向量

    Args:
        text: 待向量化的文本
        model: 模型名（默认 EMBEDDING_MODEL 环境变量或 text-embedding-v2）

    Returns:
        向量（float 列表，通常 1536 或 1024 维）
    """
    if model is None:
        model = os.getenv("EMBEDDING_MODEL", "text-embedding-v2")

    api_key = _get_api_key()

    try:
        resp = httpx.post(
            _DASHSCOPE_EMBED_URL,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": model,
                "input": {"texts": [text]},
            },
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        return data["output"]["embeddings"][0]["embedding"]
    except Exception as e:
        raise RuntimeError(f"Embedding API error: {e}")


def embed_texts(texts: list[str], model: str | None = None) -> list[list[float]]:
    """批量将文本转换为向量（减少 API 调用次数）

    Args:
        texts: 待向量化的文本列表
        model: 模型名

    Returns:
        向量列表
    """
    if model is None:
        model = os.getenv("EMBEDDING_MODEL", "text-embedding-v2")

    if not texts:
        return []

    api_key = _get_api_key()

    try:
        resp = httpx.post(
            _DASHSCOPE_EMBED_URL,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": model,
                "input": {"texts": texts},
            },
            timeout=60,
        )
        resp.raise_for_status()
        data = resp.json()
        return [item["embedding"] for item in data["output"]["embeddings"]]
    except Exception as e:
        raise RuntimeError(f"Batch embedding API error: {e}")
