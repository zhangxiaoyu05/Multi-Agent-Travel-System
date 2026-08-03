"""MCP Server 基类 —— JSON-RPC 2.0 over stdio

每个 MCP Server 继承此类，只需注册工具处理函数即可。

协议（JSON-RPC 2.0）：
    请求:  {"jsonrpc": "2.0", "id": N, "method": "...", "params": {...}}
    响应:  {"jsonrpc": "2.0", "id": N, "result": {...}}
    错误:  {"jsonrpc": "2.0", "id": N, "error": {"code": ..., "message": "..."}}

支持的方法：
    - tools/list: 列出所有注册的工具及其 inputSchema
    - tools/call: 调用指定工具

使用方式：
    # weather_server.py
    from mcp.server import MCPServer, tool

    server = MCPServer("weather")

    @tool(server, name="get_weather", description="查询天气",
          parameters={"city": "string", "date": "string"})
    def get_weather(city: str, date: str) -> str:
        return f"{city} {date} 晴..."

    if __name__ == "__main__":
        server.run()
"""

from __future__ import annotations

import sys
import json
import logging
import traceback
from typing import Any, Callable

logger = logging.getLogger(__name__)


class MCPServer:
    """MCP JSON-RPC 服务器基类。

    读取 stdin 的 JSON-RPC 请求，路由到注册的方法处理函数，
    将结果写入 stdout。日志写入 stderr。
    """

    def __init__(self, name: str, version: str = "1.0.0"):
        self.name = name
        self.version = version
        self._tools: dict[str, dict] = {}       # tool_name → {handler, schema}
        self._server_info = {
            "name": name,
            "version": version,
        }

    # =========================================================================
    # 工具注册
    # =========================================================================

    def register_tool(
        self,
        name: str,
        handler: Callable,
        description: str = "",
        parameters: dict[str, str] | None = None,
    ):
        """注册一个工具。

        Args:
            name: 工具名称（唯一标识）
            handler: 处理函数，接收 **kwargs，返回 str
            description: 工具功能描述
            parameters: 参数名 → 类型映射，如 {"city": "string", "date": "string"}
        """
        props = {}
        required = []
        if parameters:
            for pname, ptype in parameters.items():
                props[pname] = {"type": ptype}
                required.append(pname)

        self._tools[name] = {
            "handler": handler,
            "schema": {
                "name": name,
                "description": description,
                "inputSchema": {
                    "type": "object",
                    "properties": props,
                    "required": required,
                },
            },
        }

    # =========================================================================
    # JSON-RPC 方法路由
    # =========================================================================

    def _handle_request(self, request: dict) -> dict:
        """路由 JSON-RPC 请求到对应方法"""
        req_id = request.get("id")
        method = request.get("method", "")
        params = request.get("params", {})

        try:
            if method == "initialize":
                result = self._handle_initialize(params)
            elif method == "tools/list":
                result = self._handle_list_tools()
            elif method == "tools/call":
                result = self._handle_call_tool(params)
            else:
                return self._error(req_id, -32601, f"未知方法: {method}")

            return {"jsonrpc": "2.0", "id": req_id, "result": result}

        except Exception as e:
            logger.error("Error handling %s: %s\n%s", method, e, traceback.format_exc())
            return self._error(req_id, -32603, str(e))

    # =========================================================================
    # 方法实现
    # =========================================================================

    def _handle_initialize(self, params: dict) -> dict:
        return {
            "protocolVersion": "2024-11-05",
            "serverInfo": self._server_info,
            "capabilities": {"tools": {}},
        }

    def _handle_list_tools(self) -> dict:
        return {
            "tools": [t["schema"] for t in self._tools.values()],
        }

    def _handle_call_tool(self, params: dict) -> dict:
        tool_name = params.get("name", "")
        arguments = params.get("arguments", {})

        tool = self._tools.get(tool_name)
        if not tool:
            raise ValueError(f"未知工具: {tool_name}")

        result = tool["handler"](**arguments)
        return {
            "content": [
                {"type": "text", "text": str(result)},
            ],
        }

    @staticmethod
    def _error(req_id: Any, code: int, message: str) -> dict:
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "error": {"code": code, "message": message},
        }

    # =========================================================================
    # 主循环
    # =========================================================================

    def run(self):
        """启动 stdio JSON-RPC 主循环。

        从 stdin 逐行读取 JSON 请求，处理后写入 stdout。
        日志输出到 stderr（不干扰 stdout 的 JSON-RPC 通信）。

        Windows 兼容：stdout 强制使用 UTF-8 编码，避免 emoji/中文乱码。
        """
        # 修复 Windows GBK 编码问题：stdout 使用 UTF-8
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8")
        elif hasattr(sys.stdout, "buffer"):
            sys.stdout = open(sys.stdout.fileno(), mode="w", encoding="utf-8", buffering=1)

        logger.info("MCP Server [%s] v%s starting on stdio", self.name, self.version)

        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue

            try:
                request = json.loads(line)
            except json.JSONDecodeError:
                logger.warning("Invalid JSON: %s", line[:100])
                continue

            response = self._handle_request(request)
            sys.stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
            sys.stdout.flush()

        logger.info("MCP Server [%s] shutting down (stdin closed)", self.name)


# =============================================================================
# 装饰器语法糖
# =============================================================================

def tool(server: MCPServer, *, name: str, description: str = "",
         parameters: dict[str, str] | None = None):
    """装饰器：将函数注册为 MCP 工具。

    Usage:
        @tool(server, name="get_weather", description="查询天气",
              parameters={"city": "string", "date": "string"})
        def get_weather(city, date):
            return f"{city} {date} 晴天"
    """
    def decorator(func):
        server.register_tool(name, func, description, parameters)
        return func
    return decorator
