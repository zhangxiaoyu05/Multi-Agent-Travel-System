"""本地快速调试入口

用法：
    python main.py           # 启动 FastAPI 服务（http://localhost:8000）
    python main.py test      # 命令行快速测试 LangGraph 图
"""

import sys
import os
from dotenv import load_dotenv

# 确保加载 .env
load_dotenv()

# Windows GBK 终端编码兼容
if sys.platform == "win32":
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")


def safe_print(*args, **kwargs):
    """安全打印，忽略无法编码的字符"""
    for arg in args:
        try:
            print(arg, **kwargs)
        except UnicodeEncodeError:
            print(str(arg).encode("ascii", errors="replace").decode("ascii"), **kwargs)


def test_graph():
    """命令行快速测试 LangGraph 图——Phase 4

    发送多条测试消息，验证：
    - 意图路由 + 客服 FAQ + 投诉转人工（Phase 3 回归）
    - 定制需求提取 + 必填项检查 + 追问
    - 完整信息 → 工具调用 + 行程草案生成
    - 意向评分 + 修订循环
    - checkpoint 持久化（多轮需求收集）
    """
    from graph.builder import build_graph

    safe_print("=" * 60)
    safe_print("LangGraph Graph Test —— Phase 4")
    safe_print("=" * 60)

    graph = build_graph()

    # ---- 测试 1：定制——信息不全需追问 ----
    safe_print("\n>>> Test 1: Planner — Missing Fields (ask follow-up)")
    safe_print("-" * 40)

    result1 = graph.invoke(
        {
            "messages": [{"role": "user", "content": "我想去西安玩几天"}],
            "session_id": "test-p4-01",
            "customer_id": "cust-p4-01",
            "channel": "web",
            "language": "zh",
        },
        config={"configurable": {"thread_id": "test-p4-01"}},
    )

    safe_print(f"  Intent scores  : {result1.get('intent_scores')}")
    safe_print(f"  Branch         : {result1.get('current_branch')}")
    safe_print(f"  need_human     : {result1.get('need_human')}")
    safe_print(f"  Need collected : { {k:v for k,v in result1.get('need',{}).items() if v} }")
    safe_print(f"  Draft version  : {result1.get('draft', {}).get('version', 'N/A')}")
    safe_print(f"  Reply (trunc)  : {result1.get('final_reply', '')[:200]}")

    # ---- 测试 2：定制——完整信息生成草案 ----
    safe_print("\n>>> Test 2: Planner — Full Info → Generate Itinerary")
    safe_print("-" * 40)

    result2 = graph.invoke(
        {
            "messages": [{"role": "user", "content": "我想去西安玩4天，8月15号到，2个人，预算每人1500美元，喜欢历史文化，轻松节奏"}],
            "session_id": "test-p4-02",
            "customer_id": "cust-p4-02",
            "channel": "web",
            "language": "zh",
        },
        config={"configurable": {"thread_id": "test-p4-02"}},
    )

    safe_print(f"  Intent scores  : {result2.get('intent_scores')}")
    safe_print(f"  Branch         : {result2.get('current_branch')}")
    safe_print(f"  need_human     : {result2.get('need_human')}")
    safe_print(f"  Need collected : { {k:v for k,v in result2.get('need',{}).items() if v} }")
    safe_print(f"  Draft version  : {result2.get('draft', {}).get('version', 'N/A')}")
    safe_print(f"  Intent level   : {result2.get('intent_level')}")
    safe_print(f"  Next action    : {result2.get('next_action')}")
    safe_print(f"  Reply (trunc)  : {result2.get('final_reply', '')[:200]}")

    # ---- 测试 3：多轮收集——同一 thread 补全信息 ----
    safe_print("\n>>> Test 3: Planner — Multi-turn info collection")
    safe_print("-" * 40)

    # 3a: 第一轮——只说目的地
    _ = graph.invoke(
        {
            "messages": [{"role": "user", "content": "想去成都"}],
            "session_id": "test-p4-03",
            "customer_id": "cust-p4-03",
            "channel": "web",
            "language": "zh",
        },
        config={"configurable": {"thread_id": "test-p4-03"}},
    )

    # 3b: 第二轮——补全大部分信息
    result3b = graph.invoke(
        {
            "messages": [{"role": "user", "content": "5天，8月20号到，3个人，预算每人1000美元，喜欢美食"}],
        },
        config={"configurable": {"thread_id": "test-p4-03"}},
    )

    safe_print(f"  Intent scores  : {result3b.get('intent_scores')}")
    safe_print(f"  Branch         : {result3b.get('current_branch')}")
    safe_print(f"  Need collected : { {k:v for k,v in result3b.get('need',{}).items() if v} }")
    safe_print(f"  Draft version  : {result3b.get('draft', {}).get('version', 'N/A')}")
    safe_print(f"  Intent level   : {result3b.get('intent_level')}")
    safe_print(f"  Reply (trunc)  : {result3b.get('final_reply', '')[:200]}")

    # ---- 测试 4：修订循环——用户要求修改行程 ----
    safe_print("\n>>> Test 4: Planner — Revision Loop")
    safe_print("-" * 40)

    result4 = graph.invoke(
        {
            "messages": [{"role": "user", "content": "能不能多加点美食推荐的环节？"}],
        },
        config={"configurable": {"thread_id": "test-p4-02"}},  # 复用 test-p4-02 的 session
    )

    safe_print(f"  Branch         : {result4.get('current_branch')}")
    safe_print(f"  Draft version  : {result4.get('draft', {}).get('version', 'N/A')}")
    safe_print(f"  Revision count : {result4.get('revision_count')}")
    safe_print(f"  Intent level   : {result4.get('intent_level')}")
    safe_print(f"  Next action    : {result4.get('next_action')}")
    safe_print(f"  Reply (trunc)  : {result4.get('final_reply', '')[:200]}")

    # ---- 测试 5：客服 FAQ（Phase 3 回归）----
    safe_print("\n>>> Test 5: CS — FAQ Regression")
    safe_print("-" * 40)

    result5 = graph.invoke(
        {
            "messages": [{"role": "user", "content": "签证需要什么材料？"}],
            "session_id": "test-p4-05",
            "customer_id": "cust-p4-05",
            "channel": "web",
            "language": "zh",
        },
        config={"configurable": {"thread_id": "test-p4-05"}},
    )

    safe_print(f"  Intent scores  : {result5.get('intent_scores')}")
    safe_print(f"  need_human     : {result5.get('need_human')}")
    safe_print(f"  Reply (trunc)  : {result5.get('final_reply', '')[:150]}")

    # ---- 测试 6：投诉转人工（Phase 3 回归）----
    safe_print("\n>>> Test 6: CS — Complaint → Handoff (Regression)")
    safe_print("-" * 40)

    result6 = graph.invoke(
        {
            "messages": [{"role": "user", "content": "我要投诉，导游完全不专业！"}],
            "session_id": "test-p4-06",
            "customer_id": "cust-p4-06",
            "channel": "web",
            "language": "zh",
        },
        config={"configurable": {"thread_id": "test-p4-06"}},
    )

    safe_print(f"  need_human     : {result6.get('need_human')}")
    safe_print(f"  Reply (trunc)  : {result6.get('final_reply', '')[:150]}")

    safe_print("\n" + "=" * 60)
    safe_print("[OK] All 6 tests completed!")
    safe_print("=" * 60)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "test":
        test_graph()
    else:
        import uvicorn
        uvicorn.run(
            "api.main:app",
            host="0.0.0.0",
            port=8000,
            reload=True,
            log_level="info",
        )
