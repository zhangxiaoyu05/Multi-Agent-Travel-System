"""RAG FAQ 搜索工具——Milvus 向量检索 + 关键词兜底

三层回退策略：
1. Milvus 向量语义搜索（主路径，text-embedding-v4）
2. 关键词匹配（兜底，Milvus 不可用时）
3. 通用回退消息（最终兜底）

使用方式：
    from tools.rag_faq import search_faq
    result = search_faq.invoke({"query": "签证需要什么材料？"})
"""

import logging
from langchain_core.tools import tool

logger = logging.getLogger(__name__)

# =============================================================================
# 关键词兜底库（Milvus 不可用时的 fallback）
# =============================================================================

_FALLBACK_FAQ: dict[str, str] = {
    "签证材料": (
        "【签证政策】\n"
        "中国旅游签证（L签）基本材料：\n"
        "1. 有效期6个月以上的护照\n"
        "2. 签证申请表\n"
        "3. 近期2寸白底照片\n"
        "4. 往返机票订单\n"
        "5. 酒店预订确认\n"
        "6. 行程安排\n"
        "7. 部分国家需提供邀请函\n\n"
        "中国对部分国家实行144小时过境免签政策，覆盖北京、上海、广州、西安等主要城市。"
    ),
    "支付": (
        "【支付方式】\n"
        "在中国旅行推荐：微信支付（WeChat Pay）、支付宝（Alipay），两者均支持境外银行卡绑定。\n"
        "Visa/Mastercard 信用卡在大型酒店和商场可用。\n"
        "建议：出发前绑定国际信用卡到微信或支付宝，可大幅提升支付便利性。"
    ),
    "退改": (
        "【退改政策】\n"
        "- 出发前7天以上取消：全额退款（扣除少量手续费）\n"
        "- 出发前3-7天取消：收取50%费用\n"
        "- 出发前3天内取消：收取100%费用\n"
        "- 因不可抗力（自然灾害、疫情等）取消：可申请全额退款。"
    ),
    "天气": (
        "【天气概况】\n"
        "中国地域辽阔，各地气候差异显著。北京夏季25-35°C、冬季-10~5°C；"
        "西安夏季25-38°C；上海夏季25-35°C（潮湿）；成都四季温和多雨雾。\n"
        "建议出发前3天查询目的地具体天气预报。"
    ),
    "小费": (
        "【小费文化】\n"
        "中国大陆不实行小费制度。酒店行李员可酌情给5-10元人民币。\n"
        "部分高档餐厅可能收取10-15%服务费（会在账单中标注）。"
    ),
    "网络": (
        "【网络与上网】\n"
        "推荐：购买本地SIM卡、租用便携WiFi或开通国际漫游。\n"
        "注意：Google、Facebook等在中国无法直接访问，建议提前安装VPN。\n"
        "推荐下载WeChat作为主要通讯工具。"
    ),
    "交通": (
        "【交通出行】\n"
        "高铁覆盖全国主要城市（300km/h+）；地铁覆盖一线城市（票价2-10元）；"
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
    "健康": (
        "【健康提示】\n"
        "出行前建议：购买旅游保险（含医疗）、携带常用药品、注意饮食卫生喝瓶装水。\n"
        "中国医疗资源丰富，大城市均有国际医院。紧急电话：120（急救）。"
    ),
}


# =============================================================================
# 工具定义
# =============================================================================


@tool
def search_faq(query: str) -> str:
    """搜索 FAQ 知识库回答用户关于旅游（签证、支付、天气、安全等）的常见问题。

    优先使用 Milvus 向量语义检索，不可用时回退到关键词匹配。

    Args:
        query: 用户的中文问题

    Returns:
        格式化的 FAQ 回答文本，或提示无相关结果
    """
    if not query or not query.strip():
        return "请提供您想了解的具体问题，例如：签证需要什么材料？"

    # ---- Step 1: 尝试 Milvus 向量检索 ----
    try:
        from services.vector_store import search_knowledge, get_collection_stats

        stats = get_collection_stats()
        if stats.get("count", 0) > 0:
            results = search_knowledge(query, top_k=3, score_threshold=0.3)

            if results:
                lines = []
                for r in results:
                    category = r.get("metadata", {}).get("category", "")
                    header = f"【{category}】" if category else ""
                    lines.append(f"{header}\n{r['content']}")
                return "\n\n---\n\n".join(lines)
    except Exception as e:
        logger.warning(f"Milvus search unavailable, falling back to keywords: {e}")

    # ---- Step 2: 关键词兜底匹配 ----
    for keyword, answer in _FALLBACK_FAQ.items():
        if keyword in query:
            return answer

    # 英文关键词映射
    fuzzy_map: dict[str, str] = {
        "visa": "签证材料", "payment": "支付", "cancel": "退改", "refund": "退改",
        "weather": "天气", "tip": "小费", "wifi": "网络", "internet": "网络",
        "transport": "交通", "taxi": "交通", "subway": "交通",
        "safety": "安全", "food": "美食", "eat": "美食", "restaurant": "美食",
        "language": "语言", "english": "语言", "health": "健康", "hospital": "健康",
    }
    query_lower = query.lower()
    for en_key, cn_key in fuzzy_map.items():
        if en_key in query_lower:
            return _FALLBACK_FAQ.get(cn_key, "")

    # ---- Step 3: 通用兜底 ----
    return (
        "感谢您的咨询！这个问题我需要更多信息才能准确回答。\n\n"
        "您可以尝试以下方式：\n"
        "1. 更具体地描述您的问题（例如"签证需要什么材料？"）\n"
        "2. 输入「人工」转接人工客服\n"
        "3. 常见问题类别：签证、支付、退改、天气、交通、网络、美食、安全、语言、健康"
    )
