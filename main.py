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


def test_graph(quick: bool = False):
    """命令行快速测试 LangGraph 图——Phase 6

    发送多条测试消息，验证：
    - 意图路由 + 客服 FAQ + 投诉转人工（Phase 3 回归）
    - 定制需求提取 + 必填项检查 + 追问
    - 完整信息 → 工具调用 + 行程草案生成
    - 意向评分 + 修订循环
    - checkpoint 持久化（多轮需求收集）
    - 终态写入（operations_sync 节点）
    - 销售询价 + 报价生成 + 意向评估（Phase 6）
    - 运营工单 + CRM 写入（Phase 6）

    Args:
        quick: True = 只跑快速测试（跳过行程生成，~15s）；False = 全量测试（~3min）
    """
    import time
    from graph.builder import build_graph

    t_start = time.time()

    safe_print("=" * 60)
    mode_label = "Quick" if quick else "Full"
    safe_print(f"LangGraph Graph Test —— Phase 6 ({mode_label})")
    safe_print("=" * 60)

    graph = build_graph()

    # ---- 测试 1：定制——信息不全需追问（快：~3s）----
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

    # =========================================================================
    # 慢速测试：含 qwen-plus 长篇行程生成，每个 ~50s
    # =========================================================================
    if quick:
        safe_print("\n>>> Test 2-4,7: SKIPPED (slow — qwen-plus itinerary generation ~50s each)")
        safe_print("    Use 'python main.py test' for full suite.")
    else:
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

    # =========================================================================
    # 快速测试：客服 + 投诉（每个 < 10s）
    # =========================================================================

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

    # ---- 测试 7：操作同步确认（慢：~50s，跳过）----
    if quick:
        safe_print("\n>>> Test 7: SKIPPED")
    else:
        safe_print("\n>>> Test 7: Operations Sync — Trip Confirmed")
        safe_print("-" * 40)

        result7 = graph.invoke(
            {
                "messages": [{"role": "user", "content": "帮我规划北京3天，8月10号到，1个人，预算3000人民币"}],
                "session_id": "test-p5-07",
                "customer_id": "cust-p5-07",
                "channel": "web",
                "language": "zh",
            },
            config={"configurable": {"thread_id": "test-p5-07"}},
        )

        safe_print(f"  Branch         : {result7.get('current_branch')}")
        safe_print(f"  Draft version  : {result7.get('draft', {}).get('version', 'N/A')}")
        safe_print(f"  Intent level   : {result7.get('intent_level')}")
        safe_print(f"  Next action    : {result7.get('next_action')}")
        safe_print(f"  Final reply OK : {'Yes' if result7.get('final_reply') else 'No'}")
        safe_print(f"  [Phase 5] operations_sync should have run (CRM + CAPI written)")

    # ---- 测试 8：终态写入——转人工走 operations_sync（快：~1s）----
    safe_print("\n>>> Test 8: Operations Sync — Handoff → CRM")
    safe_print("-" * 40)

    result8 = graph.invoke(
        {
            "messages": [{"role": "user", "content": "我要投诉！你们的服务太差了，我要退款！"}],
            "session_id": "test-p5-08",
            "customer_id": "cust-p5-08",
            "channel": "web",
            "language": "zh",
        },
        config={"configurable": {"thread_id": "test-p5-08"}},
    )

    safe_print(f"  need_human     : {result8.get('need_human')}")
    safe_print(f"  Reply length   : {len(result8.get('final_reply', ''))} chars")
    safe_print(f"  [Phase 5] handoff should have gone through operations_sync")

    # =========================================================================
    # Phase 6 测试：销售 + 运营
    # =========================================================================

    # ---- 测试 9：销售——询价 + 报价生成（快：~5s）----
    safe_print("\n>>> Test 9: Sales — Pricing Inquiry → Quote (Phase 6)")
    safe_print("-" * 40)

    result9 = graph.invoke(
        {
            "messages": [{"role": "user", "content": "我想去三亚玩5天，2个人，每人预算2000美元，能给我报个价吗？"}],
            "session_id": "test-p6-09",
            "customer_id": "cust-p6-09",
            "channel": "web",
            "language": "zh",
        },
        config={"configurable": {"thread_id": "test-p6-09"}},
    )

    safe_print(f"  Intent scores  : {result9.get('intent_scores')}")
    safe_print(f"  Branch         : {result9.get('current_branch')}")
    safe_print(f"  Intent level   : {result9.get('intent_level')}")
    safe_print(f"  Next action    : {result9.get('next_action')}")
    safe_print(f"  need_human     : {result9.get('need_human')}")
    safe_print(f"  Reply (trunc)  : {result9.get('final_reply', '')[:200]}")

    # ---- 测试 10：销售——高意向购买（快：~5s）----
    safe_print("\n>>> Test 10: Sales — High Intent Purchase (Phase 6)")
    safe_print("-" * 40)

    result10 = graph.invoke(
        {
            "messages": [{"role": "user", "content": "这个报价不错，我要预订，怎么支付？"}],
        },
        config={"configurable": {"thread_id": "test-p6-09"}},  # 复用 session
    )

    safe_print(f"  Branch         : {result10.get('current_branch')}")
    safe_print(f"  Intent level   : {result10.get('intent_level')}")
    safe_print(f"  Next action    : {result10.get('next_action')}")
    safe_print(f"  need_human     : {result10.get('need_human')}")
    safe_print(f"  Reply (trunc)  : {result10.get('final_reply', '')[:200]}")
    safe_print(f"  [Phase 6] High intent → should route to operations_sync")

    # ---- 测试 11：运营——商家入驻咨询（快：~3s）----
    safe_print("\n>>> Test 11: Operations — Merchant Onboarding (Phase 6)")
    safe_print("-" * 40)

    result11 = graph.invoke(
        {
            "messages": [{"role": "user", "content": "我是旅行社的，想在你们平台上架产品，需要什么资质？"}],
            "session_id": "test-p6-11",
            "customer_id": "cust-p6-11",
            "channel": "web",
            "language": "zh",
        },
        config={"configurable": {"thread_id": "test-p6-11"}},
    )

    safe_print(f"  Intent scores  : {result11.get('intent_scores')}")
    safe_print(f"  Branch         : {result11.get('current_branch')}")
    safe_print(f"  need_human     : {result11.get('need_human')}")
    safe_print(f"  Reply (trunc)  : {result11.get('final_reply', '')[:200]}")
    safe_print(f"  [Phase 6] ops → should route through operations_sync (CRM written)")

    # ---- 测试 12：运营——订单履约查询（快：~3s）----
    safe_print("\n>>> Test 12: Operations — Order Fulfillment Query (Phase 6)")
    safe_print("-" * 40)

    result12 = graph.invoke(
        {
            "messages": [{"role": "user", "content": "我想查一下订单号 TK-2024-0815 的履约状态，酒店和车辆都确认好了吗？"}],
            "session_id": "test-p6-12",
            "customer_id": "cust-p6-12",
            "channel": "web",
            "language": "zh",
        },
        config={"configurable": {"thread_id": "test-p6-12"}},
    )

    safe_print(f"  Branch         : {result12.get('current_branch')}")
    safe_print(f"  need_human     : {result12.get('need_human')}")
    safe_print(f"  Reply (trunc)  : {result12.get('final_reply', '')[:200]}")
    safe_print(f"  [Phase 6] ops fulfillment → should go through operations_sync")

    elapsed = time.time() - t_start
    test_count = "8" if quick else "12"
    safe_print("\n" + "=" * 60)
    safe_print(f"[OK] All {test_count} tests completed in {elapsed:.1f}s")
    safe_print("=" * 60)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "test":
        quick = "--quick" in sys.argv
        test_graph(quick=quick)
    else:
        import uvicorn
        uvicorn.run(
            "api.main:app",
            host="0.0.0.0",
            port=8000,
            reload=True,
            log_level="info",
        )
