"""RAG FAQ 检索工具——Phase 7

基于 Chroma 向量检索的 FAQ 查询工具。
优先使用语义向量搜索，无结果时回退到关键词匹配。

依赖：
- services/vector_store.py：Chroma 向量数据库
- services/embeddings.py：百炼 Embedding
- scripts/ingest_knowledge.py：知识库导入脚本（首次使用前运行）
"""

from langchain.tools import tool
from services.vector_store import search_knowledge, get_collection_stats


# =============================================================================
# 关键词回退字典（当向量库未初始化或无相关结果时使用）
# =============================================================================

_FALLBACK_FAQ: dict[str, str] = {
    "签证": (
        "【签证政策】\n"
        "中国对部分国家实行 144 小时过境免签政策，覆盖北京、上海、广州、西安等主要城市。\n"
        "日本、新加坡、文莱公民可享受 15 天免签入境。\n"
        "入境时需出示：有效期 6 个月以上的护照、离境机票订单、酒店预订确认单。\n"
        "具体请查阅中国驻当地使领馆最新公告，政策可能随时调整。"
    ),
    "支付": (
        "【支付方式】\n"
        "在中国旅行推荐：微信支付（WeChat Pay）、支付宝（Alipay），两者均支持境外银行卡绑定。\n"
        "Visa/Mastercard 信用卡在大型酒店和商场可用。\n"
        "建议：出发前绑定国际信用卡到微信或支付宝，可大幅提升支付便利性。"
    ),
    "退改": (
        "【退改政策】\n"
        "- 出发前 7 天以上取消：全额退款（扣除少量手续费）\n"
        "- 出发前 3-7 天取消：收取 50% 费用\n"
        "- 出发前 3 天内取消：收取 100% 费用\n"
        "- 因不可抗力（自然灾害、疫情等）取消：可申请全额退款。"
    ),
    "天气": (
        "【天气概况】\n"
        "中国地域辽阔，各地气候差异显著。北京夏季 25-35°C、冬季 -10~5°C；"
        "西安夏季 25-38°C；上海夏季 25-35°C（潮湿）；成都四季温和多雨雾。\n"
        "建议出发前 3 天查询目的地具体天气预报。"
    ),
    "小费": (
        "【小费文化】\n"
        "中国大陆不实行小费制度。酒店行李员可酌情给 5-10 元人民币。\n"
        "部分高档餐厅可能收取 10-15% 服务费（会在账单中标注）。"
    ),
    "网络": (
        "【网络与上网】\n"
        "推荐：购买本地 SIM 卡、租用便携 WiFi 或国际漫游。\n"
        "注意：Google、Facebook 等在中国无法直接访问，建议提前安装 VPN。\n"
        "推荐下载 WeChat 作为主要通讯工具。"
    ),
    "交通": (
        "【交通出行】\n"
        "高铁覆盖全国主要城市（300km/h+）；地铁覆盖一线城市（票价 2-10 元）；"
        "滴滴出行（Didi）支持英文界面和境外信用卡。\n"
        "建议下载：12306（火车票）、滴滴出行、高德地图。"
    ),
    "安全": (
        "【安全提示】\n"
        "中国是世界上最安全的旅游目的地之一，暴力犯罪率极低。\n"
        "注意保管财物、去正规银行换汇。紧急电话：110（报警）、120（急救）、119（火警）。\n"
        "建议购买旅行保险，覆盖医疗和财物损失。"
    ),
    "美食": (
        "【美食推荐】\n"
        "北京烤鸭、西安肉夹馍/羊肉泡馍、上海小笼包/生煎、成都火锅/麻婆豆腐、广州早茶点心。\n"
        "建议尝试当地小吃街/夜市，体验最地道的美食文化。"
    ),
    "语言": (
        "【语言沟通】\n"
        "主要城市酒店、机场基本有英文服务。小商铺、出租车可能只讲中文。\n"
        "推荐：Google Translate（拍照翻译）、有道翻译。\n"
        "准备酒店名片（中文地址），打车时出示给司机。"
    ),
}


# =============================================================================
# RAG FAQ 工具
# =============================================================================


@tool
def search_faq(query: str) -> str:
    """搜索 FAQ 知识库（RAG 向量检索 + 关键词兜底）。

    使用语义向量搜索在知识库中查找最相关的 FAQ 答案。
    如果向量库未初始化或结果不相关，自动回退到关键词匹配。
    覆盖签证、支付、退改、天气、小费、网络、交通、安全、美食、语言、文化、城市指南等。

    Args:
        query: 用户的问题文本

    Returns:
        最相关的 FAQ 答案文本。如果未找到匹配，返回兜底提示。
    """
    # Step 1: 尝试 RAG 向量检索
    try:
        stats = get_collection_stats()
        if stats["count"] > 0:
            results = search_knowledge(query, top_k=3, score_threshold=0.3)

            if results:
                # 合并检索到的文档
                lines = []
                for i, r in enumerate(results, 1):
                    category = r.get("metadata", {}).get("category", "")
                    header = f"【{category}】" if category else f"【参考信息 {i}】"
                    lines.append(f"{header}\n{r['content']}")

                return "\n\n---\n\n".join(lines)
    except Exception:
        pass  # RAG 不可用，回退到关键词

    # Step 2: 关键词匹配回退
    query_lower = query.lower()

    # 中文关键词匹配
    for key, answer in _FALLBACK_FAQ.items():
        if key in query:
            return answer

    # 英文关键词匹配
    fuzzy_map: dict[str, str] = {
        "visa": "签证", "payment": "支付", "cancel": "退改", "refund": "退改",
        "weather": "天气", "tip": "小费", "wifi": "网络", "internet": "网络",
        "transport": "交通", "taxi": "交通", "subway": "交通",
        "safety": "安全", "food": "美食", "eat": "美食", "restaurant": "美食",
        "language": "语言", "english": "语言",
    }
    for en_key, cn_key in fuzzy_map.items():
        if en_key in query_lower:
            return _FALLBACK_FAQ.get(cn_key, "")

    # Step 3: 完全兜底
    return (
        "您的问题已记录。建议：\n"
        "1. 尝试用更具体的关键词描述您的问题\n"
        "2. 输入「人工」转接人工客服\n"
        "3. 常见问题类别：签证、支付、退改、天气、交通、网络、美食、安全、语言、城市指南"
    )
