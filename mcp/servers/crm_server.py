"""CRM MCP Server —— 客户关系管理记录写入

数据存储:
    - 主存储: MySQL (services/mysql.py)
    - 写入内容: 会话摘要、客户标签、转化状态

启动方式:
    python mcp/servers/crm_server.py
"""

from __future__ import annotations

import sys
import os
import json
import logging
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from mcp.server import MCPServer, tool

logger = logging.getLogger(__name__)
server = MCPServer("crm", version="1.0.0")


def _write_to_mysql(customer_id: str, session_data: str) -> str:
    """写入 CRM 记录到 MySQL"""
    try:
        from services.mysql import get_engine
        from sqlalchemy import text

        engine = get_engine()
        now = datetime.utcnow().isoformat()

        # 解析或构建 session_data
        try:
            data = json.loads(session_data)
        except (json.JSONDecodeError, TypeError):
            data = {"raw": session_data[:500]}

        data["recorded_at"] = now

        with engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO crm_records (customer_id, session_data, created_at, updated_at) "
                    "VALUES (:cid, :data, :now, :now) "
                    "ON DUPLICATE KEY UPDATE session_data = :data2, updated_at = :now2"
                ),
                {
                    "cid": customer_id,
                    "data": json.dumps(data, ensure_ascii=False),
                    "now": now,
                    "data2": json.dumps(data, ensure_ascii=False),
                    "now2": now,
                },
            )

        return (
            f"[CRM] ✅ 客户 {customer_id} 记录已写入\n"
            f"写入时间：{now}\n"
            f"数据摘要：{str(data)[:200]}"
        )

    except ImportError as e:
        logger.warning("MySQL not available for CRM: %s", e)
        return (
            f"[CRM] ⚠️ MySQL 不可用，CRM 记录仅保存在日志中\n"
            f"客户：{customer_id}\n"
            f"时间：{datetime.utcnow().isoformat()}\n"
            f"数据：{session_data[:200]}"
        )
    except Exception as e:
        logger.error("CRM write error: %s", e)
        return f"[CRM] ❌ 写入失败：{e}"


@tool(server, name="update_crm", description="将客户会话数据写入 CRM 系统。用于记录客户交互历史、标签和转化状态。运营 Agent 在每次会话结束时调用。",
      parameters={"customer_id": "string", "session_data": "string"})
def update_crm(customer_id: str, session_data: str) -> str:
    """写入 CRM 记录

    Args:
        customer_id: 客户唯一标识
        session_data: 会话数据（JSON 字符串），可包含 branch/done/intent 等字段

    Returns:
        写入结果确认文本
    """
    # 截断过长数据
    if len(session_data) > 2000:
        session_data = session_data[:2000] + "...(truncated)"
    return _write_to_mysql(customer_id, session_data)


if __name__ == "__main__":
    server.run()
