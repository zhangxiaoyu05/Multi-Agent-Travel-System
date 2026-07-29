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
    """命令行快速测试 LangGraph 图——Phase 3

    发送多条测试消息，验证：
    - 意图路由是否正常
    - 客服 Agent 是否正确调用 FAQ 工具
    - 投诉是否正确触发转人工 + 交接单生成
    - after_service 条件边流转
    - checkpoint 是否正常持久化
    """
    from graph.builder import build_graph

    safe_print("=" * 60)
    safe_print("LangGraph Graph Test —— Phase 3")
    safe_print("=" * 60)

    graph = build_graph()

    # ---- 测试 1：客服 FAQ（签证查询）----
    safe_print("\n>>> Test 1: Customer Service — FAQ (Visa)")
    safe_print("-" * 40)

    result = graph.invoke(
        {
            "messages": [{"role": "user", "content": "签证需要什么材料？"}],
            "session_id": "test-001",
            "customer_id": "cust-001",
            "channel": "web",
            "language": "zh",
        },
        config={"configurable": {"thread_id": "test-001"}},
    )

    safe_print(f"  Intent scores  : {result.get('intent_scores')}")
    safe_print(f"  need_human     : {result.get('need_human')}")
    safe_print(f"  Branch         : {result.get('current_branch')}")
    safe_print(f"  Reply (trunc)  : {result.get('final_reply', '')[:150]}")

    # ---- 测试 2：客服 FAQ（支付查询）----
    safe_print("\n>>> Test 2: Customer Service — FAQ (Payment)")
    safe_print("-" * 40)

    result2 = graph.invoke(
        {
            "messages": [{"role": "user", "content": "在中国旅游怎么支付？"}],
            "session_id": "test-002",
            "customer_id": "cust-002",
            "channel": "web",
            "language": "zh",
        },
        config={"configurable": {"thread_id": "test-002"}},
    )

    safe_print(f"  Intent scores  : {result2.get('intent_scores')}")
    safe_print(f"  need_human     : {result2.get('need_human')}")
    safe_print(f"  Branch         : {result2.get('current_branch')}")
    safe_print(f"  Reply (trunc)  : {result2.get('final_reply', '')[:150]}")

    # ---- 测试 3：投诉 → 人工接管（含交接单）----
    safe_print("\n>>> Test 3: Complaint -> Human Handoff (with summary)")
    safe_print("-" * 40)

    result3 = graph.invoke(
        {
            "messages": [{"role": "user", "content": "我要投诉你们的导游，态度太差了！"}],
            "session_id": "test-003",
            "customer_id": "cust-003",
            "channel": "web",
            "language": "zh",
        },
        config={"configurable": {"thread_id": "test-003"}},
    )

    safe_print(f"  Intent scores  : {result3.get('intent_scores')}")
    safe_print(f"  need_human     : {result3.get('need_human')}")
    safe_print(f"  Branch         : {result3.get('current_branch')}")
    safe_print(f"  Reply (trunc)  : {result3.get('final_reply', '')[:200]}")

    # ---- 测试 4：客服 → 人工接管流转（after_service 条件边）----
    safe_print("\n>>> Test 4: CS -> Handoff flow (after_service edge)")
    safe_print("-" * 40)

    result4 = graph.invoke(
        {
            "messages": [{"role": "user", "content": "我要退款，全部退款！"}],
            "session_id": "test-004",
            "customer_id": "cust-004",
            "channel": "web",
            "language": "zh",
        },
        config={"configurable": {"thread_id": "test-004"}},
    )

    safe_print(f"  Intent scores  : {result4.get('intent_scores')}")
    safe_print(f"  need_human     : {result4.get('need_human')}")
    safe_print(f"  Branch         : {result4.get('current_branch')}")
    safe_print(f"  Reply (trunc)  : {result4.get('final_reply', '')[:200]}")

    # ---- 测试 5：定制意图（占位节点）----
    safe_print("\n>>> Test 5: Trip Planner Intent (placeholder)")
    safe_print("-" * 40)

    result5 = graph.invoke(
        {
            "messages": [{"role": "user", "content": "我想去西安玩3天，有什么推荐？"}],
            "session_id": "test-005",
            "customer_id": "cust-005",
            "channel": "web",
            "language": "zh",
        },
        config={"configurable": {"thread_id": "test-005"}},
    )

    safe_print(f"  Intent scores  : {result5.get('intent_scores')}")
    safe_print(f"  need_human     : {result5.get('need_human')}")
    safe_print(f"  Reply (trunc)  : {result5.get('final_reply', '')[:100]}")

    # ---- 测试 6：Checkpoint 持久化（同 thread 追问）----
    safe_print("\n>>> Test 6: Checkpoint Persistence (same thread)")
    safe_print("-" * 40)

    result6 = graph.invoke(
        {
            "messages": [{"role": "user", "content": "退改政策是什么？"}],
        },
        config={"configurable": {"thread_id": "test-001"}},  # 相同 thread_id！
    )

    safe_print(f"  Intent scores  : {result6.get('intent_scores')}")
    safe_print(f"  Reply (trunc)  : {result6.get('final_reply', '')[:150]}")
    safe_print(f"  Message history: {len(result6.get('messages', []))}")

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
