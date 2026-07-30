"""知识库摄入脚本——Milvus 向量数据库

将 FAQ 文档和城市指南导入 Milvus 向量数据库。
首次运行或知识库更新后执行此脚本。

使用方式：
    python scripts/ingest_knowledge.py           # 全量导入
    python scripts/ingest_knowledge.py --stats   # 仅查看统计
    python scripts/ingest_knowledge.py --force   # 强制覆盖已有数据
"""

import sys
import os
import time

# 确保项目根目录在 sys.path 中
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from dotenv import load_dotenv
load_dotenv()

from scripts.knowledge_base import FAQ_DOCS, CITY_DOCS
from services.vector_store import (
    init_milvus,
    add_documents,
    get_collection_stats,
    search_knowledge,
)


def ingest(force: bool = False):
    """将知识库文档导入 Milvus

    Args:
        force: True = 先清空已有数据再导入
    """
    # 初始化连接
    print("连接 Milvus...")
    try:
        init_milvus()
    except Exception as e:
        print(f"Milvus 连接失败: {e}")
        print("请确认 docker-compose 已启动: docker-compose up -d")
        return

    stats_before = get_collection_stats()
    print(f"知识库当前状态：{stats_before['count']} 篇文档（backend: {stats_before.get('backend', 'unknown')}）")
    print(f"Milvus 地址：{stats_before.get('host', 'unknown')}")
    print()

    if stats_before["count"] > 0 and not force:
        print("知识库已有数据，跳过导入。使用 --force 强制覆盖。")
        return

    all_docs = FAQ_DOCS + CITY_DOCS
    print(f"准备导入 {len(all_docs)} 篇文档（FAQ: {len(FAQ_DOCS)}, 城市指南: {len(CITY_DOCS)}）")

    # 分批导入（避免 API 限流）
    batch_size = 10
    total = len(all_docs)
    imported = 0

    t_start = time.time()
    for i in range(0, total, batch_size):
        batch = all_docs[i:i + batch_size]
        count = add_documents(batch)
        imported += count
        progress = min(i + batch_size, total)
        print(f"\r导入进度：{progress}/{total} ({imported} 成功)", end="", flush=True)

    elapsed = time.time() - t_start
    print()
    print(f"\n导入完成！耗时 {elapsed:.1f}s，成功导入 {imported} 篇文档")

    stats_after = get_collection_stats()
    print(f"知识库最新状态：{stats_after['count']} 篇文档")


def show_stats():
    """显示知识库统计信息并做测试检索"""
    try:
        init_milvus()
    except Exception as e:
        print(f"Milvus 连接失败: {e}")
        return

    stats = get_collection_stats()
    print(f"知识库统计：")
    print(f"  文档总数：{stats['count']}")
    print(f"  Collection：{stats.get('name', 'N/A')}")
    print(f"  Backend：{stats.get('backend', 'N/A')}")
    print()

    if stats["count"] == 0:
        print("知识库为空，请先运行导入：python scripts/ingest_knowledge.py")
        return

    # 测试检索
    test_queries = [
        "签证需要什么材料？",
        "北京有什么好玩的景点？",
        "如何用微信支付？",
    ]
    print("测试检索：")
    for q in test_queries:
        results = search_knowledge(q, top_k=2)
        print(f"\n  Q: {q}")
        for r in results:
            print(f"    [{r['score']:.3f}] {r['content'][:80]}...")
        if not results:
            print(f"    (无相关结果)")


if __name__ == "__main__":
    if "--stats" in sys.argv:
        show_stats()
    else:
        force = "--force" in sys.argv
        ingest(force=force)
