"""真实 CRM API——预留接口

需要对接：
- 内部 CRM 系统（如 Salesforce、HubSpot、自研 CRM）
- 业务系统 REST API 或 GraphQL 端点

实现方式：使用 httpx 调用内部 CRM REST API。

当前骨架直接 raise NotImplementedError。
"""


def update_crm_real(customer_id: str, session_data: str) -> str:
    """真实 CRM 写入——待对接内部系统。

    Args:
        customer_id: 客户 ID
        session_data: 会话数据 JSON 字符串

    Raises:
        NotImplementedError: 尚未实现真实 CRM 对接
    """
    raise NotImplementedError(
        "真实 CRM API 尚未对接。\n\n"
        "需要对接以下系统：\n"
        "1. 内部 CRM REST API —— 客户信息写入\n"
        "2. 会话记录 —— 对话历史归档\n"
        "3. 标签/分群 —— 客户画像更新\n\n"
        f"查询参数：customer_id={customer_id}"
    )
