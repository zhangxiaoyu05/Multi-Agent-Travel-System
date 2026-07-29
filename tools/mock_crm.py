"""Mock CRM 写入工具

模拟将客户交互数据写入 CRM 系统。
Phase 8 替换为真实 CRM API 调用。
"""

from langchain.tools import tool


@tool
def update_crm(customer_id: str, session_data: str) -> str:
    """写入/更新 CRM 客户记录。

    将会话摘要、出行需求、意向等级等信息持久化到客户关系管理系统。

    Args:
        customer_id: 客户唯一标识
        session_data: 会话数据摘要（JSON 字符串）

    Returns:
        CRM 写入结果描述
    """
    # Mock: 假装写入成功
    return (
        f"[CRM] 客户 {customer_id} 记录已更新。\n"
        f"写入内容摘要：{session_data[:200]}...\n"
        f"状态：✅ 成功写入 CRM"
    )
