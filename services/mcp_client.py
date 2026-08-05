"""MCP Client —— 管理 MCP Server 子进程，提供工具发现和调用

每个 MCP Server 作为独立的 asyncio 子进程运行，通过 stdin/stdout 进行 JSON-RPC 通信。
Client 负责：
    1. 启动/停止 Server 子进程
    2. 发送 JSON-RPC 请求并接收响应
    3. 工具发现（tools/list）
    4. 工具调用（tools/call）
    5. Server 崩溃自动重启

使用方式：
    from services.mcp_client import get_mcp_client

    client = get_mcp_client()
    await client.start_all()
    tools = await client.list_all_tools()
    result = await client.call_tool("get_weather", {"city": "北京", "date": "2026-08-15"})
"""

from __future__ import annotations

import os
import sys
import json
import asyncio
import logging
from typing import Any

logger = logging.getLogger(__name__)

# =============================================================================
# MCP Server 配置
# =============================================================================

# 每个 Server 的启动配置
# command: Python 解释器路径（None = 当前解释器）
# script: 相对于项目根目录的脚本路径
MCP_SERVER_CONFIG: dict[str, dict] = {
    "weather": {
        "script": "mcp/servers/weather_server.py",
        "description": "天气查询 (Open-Meteo)",
    },
    "calendar": {
        "script": "mcp/servers/calendar_server.py",
        "description": "日历/节假日查询",
    },
    "inventory": {
        "script": "mcp/servers/inventory_server.py",
        "description": "酒店/门票/车辆库存",
    },
    "quote": {
        "script": "mcp/servers/quote_server.py",
        "description": "行程报价引擎",
    },
    "crm": {
        "script": "mcp/servers/crm_server.py",
        "description": "CRM 客户记录写入",
    },
    "capi": {
        "script": "mcp/servers/capi_server.py",
        "description": "CAPI 转化事件上报",
    },
}


# =============================================================================
# JSON-RPC 请求/响应
# =============================================================================

class MCPToolError(Exception):
    """MCP 工具调用错误"""
    pass


class MCPServerConnection:
    """单个 MCP Server 的 stdio 连接。

    管理一个子进程，通过 stdin/stdout 进行 JSON-RPC 通信。
    """

    def __init__(self, server_name: str, script_path: str, project_root: str):
        self.name = server_name
        self.script_path = script_path
        self.project_root = project_root
        self._process: asyncio.subprocess.Process | None = None
        self._lifecycle_lock = asyncio.Lock()  # 保护 start/stop 操作
        self._request_lock = asyncio.Lock()    # 保护 stdin/stdout 请求通信（独立，避免死锁）
        self._request_id = 0
        self._tools_cache: list[dict] | None = None

    # =========================================================================
    # 生命周期
    # =========================================================================

    async def start(self):
        """启动 MCP Server 子进程"""
        async with self._lifecycle_lock:
            if self._process is not None and self._process.returncode is None:
                return  # 已经在运行

            script = os.path.join(self.project_root, self.script_path)
            python = sys.executable

            logger.info("Starting MCP server [%s]: %s %s", self.name, python, script)

            try:
                self._process = await asyncio.create_subprocess_exec(
                    python, script,
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=self.project_root,
                )
                # 发送 initialize 请求
                result = await self._send_request("initialize", {
                    "protocolVersion": "2024-11-05",
                    "clientInfo": {"name": "tour-agent", "version": "1.0.0"},
                })
                logger.info("MCP server [%s] initialized: %s", self.name, result)
                self._tools_cache = None  # 清空缓存，强制重新发现
            except Exception:
                logger.error("Failed to start MCP server [%s]", self.name, exc_info=True)
                self._process = None
                raise

    async def stop(self):
        """停止 MCP Server 子进程"""
        async with self._lifecycle_lock:
            if self._process is None:
                return
            proc = self._process
            self._process = None
            try:
                if proc.stdin:
                    proc.stdin.close()
                proc.terminate()
                try:
                    await asyncio.wait_for(proc.wait(), timeout=5)
                except asyncio.TimeoutError:
                    proc.kill()
                    await proc.wait()
                logger.info("MCP server [%s] stopped", self.name)
            except Exception:
                logger.warning("Error stopping MCP server [%s]", self.name, exc_info=True)

    async def restart(self):
        """重启 MCP Server"""
        await self.stop()
        await self.start()

    @property
    def is_running(self) -> bool:
        return self._process is not None and self._process.returncode is None

    # =========================================================================
    # JSON-RPC 通信
    # =========================================================================

    async def _send_request(self, method: str, params: dict) -> Any:
        """发送 JSON-RPC 请求并等待响应"""
        if self._process is None or self._process.returncode is not None:
            raise MCPToolError(f"MCP server [{self.name}] is not running")

        async with self._request_lock:
            self._request_id += 1
            req_id = self._request_id
            request = {
                "jsonrpc": "2.0",
                "id": req_id,
                "method": method,
                "params": params,
            }
            request_line = json.dumps(request, ensure_ascii=False) + "\n"

            try:
                self._process.stdin.write(request_line.encode("utf-8"))
                await self._process.stdin.drain()
            except (BrokenPipeError, ConnectionResetError) as e:
                logger.warning("MCP server [%s] pipe broken, attempting restart", self.name)
                await self.restart()
                raise MCPToolError(f"MCP server [{self.name}] connection lost, restarted: {e}")

            # 读取响应（单行 JSON）
            try:
                response_line = await asyncio.wait_for(
                    self._process.stdout.readline(), timeout=30
                )
            except asyncio.TimeoutError:
                raise MCPToolError(f"MCP server [{self.name}] request timeout")

            if not response_line:
                raise MCPToolError(f"MCP server [{self.name}] stdout closed unexpectedly")

            try:
                response = json.loads(response_line.decode("utf-8"))
            except json.JSONDecodeError:
                raise MCPToolError(
                    f"MCP server [{self.name}] returned invalid JSON: {response_line[:100]!r}"
                )

            if "error" in response:
                err = response["error"]
                raise MCPToolError(f"MCP [{self.name}] error {err.get('code')}: {err.get('message')}")

            return response.get("result")

    # =========================================================================
    # 工具 API
    # =========================================================================

    async def list_tools(self) -> list[dict]:
        """获取该 Server 提供的所有工具列表"""
        if self._tools_cache is not None:
            return self._tools_cache
        result = await self._send_request("tools/list", {})
        self._tools_cache = result.get("tools", [])
        return self._tools_cache

    async def call_tool(self, tool_name: str, arguments: dict) -> str:
        """调用该 Server 的指定工具

        Args:
            tool_name: 工具名称
            arguments: 工具参数字典

        Returns:
            工具执行结果的文本内容

        Raises:
            MCPToolError: 工具不存在或调用失败
        """
        result = await self._send_request("tools/call", {
            "name": tool_name,
            "arguments": arguments,
        })
        # 提取文本内容
        contents = result.get("content", [])
        texts = []
        for c in contents:
            if c.get("type") == "text":
                texts.append(c.get("text", ""))
        return "\n".join(texts)


# =============================================================================
# 全局 Client
# =============================================================================

class MCPClient:
    """MCP 客户端 —— 管理所有 MCP Server 连接。

    单例模式，应用启动时创建，关闭时停止所有 Server。
    """

    def __init__(self, project_root: str | None = None):
        if project_root is None:
            # 默认项目根目录：mcp 包的父目录
            project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.project_root = project_root
        self._connections: dict[str, MCPServerConnection] = {}
        self._tool_index: dict[str, str] = {}  # tool_name → server_name
        self._started = False

    # =========================================================================
    # 生命周期
    # =========================================================================

    async def start_all(self, server_names: list[str] | None = None):
        """启动所有（或指定）MCP Server

        Args:
            server_names: 要启动的 server 名称列表，None = 全部
        """
        if server_names is None:
            server_names = list(MCP_SERVER_CONFIG.keys())

        logger.info("Starting MCP servers: %s", server_names)

        tasks = []
        for name in server_names:
            config = MCP_SERVER_CONFIG.get(name)
            if config is None:
                logger.warning("Unknown MCP server: %s", name)
                continue
            conn = MCPServerConnection(name, config["script"], self.project_root)
            self._connections[name] = conn
            tasks.append(conn.start())

        # 并行启动所有 server
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for name, result in zip(server_names, results):
            if isinstance(result, Exception):
                logger.error("Failed to start MCP server [%s]: %s", name, result)

        # 构建工具索引
        await self._build_tool_index()
        self._started = True

        running = sum(1 for c in self._connections.values() if c.is_running)
        logger.info("MCP client started: %d/%d servers running", running, len(self._connections))

    async def stop_all(self):
        """停止所有 MCP Server"""
        logger.info("Stopping all MCP servers...")
        tasks = [conn.stop() for conn in self._connections.values()]
        await asyncio.gather(*tasks, return_exceptions=True)
        self._connections.clear()
        self._tool_index.clear()
        self._started = False

    async def restart_server(self, server_name: str):
        """重启指定的 MCP Server"""
        conn = self._connections.get(server_name)
        if conn:
            await conn.restart()
            await self._build_tool_index()

    # =========================================================================
    # 工具发现
    # =========================================================================

    async def _build_tool_index(self):
        """构建全局工具名 → server 名索引"""
        self._tool_index.clear()
        for name, conn in self._connections.items():
            if not conn.is_running:
                continue
            try:
                tools = await conn.list_tools()
                for t in tools:
                    self._tool_index[t["name"]] = name
            except Exception as e:
                logger.warning("Failed to list tools from [%s]: %s", name, e)

        logger.info("MCP tool index: %d tools from %d servers",
                     len(self._tool_index), len(self._connections))

    async def list_all_tools(self) -> list[dict]:
        """获取所有 Server 的所有工具（扁平列表）"""
        all_tools = []
        for name, conn in self._connections.items():
            if not conn.is_running:
                continue
            try:
                tools = await conn.list_tools()
                for t in tools:
                    t["_server"] = name  # 标记来源 server
                all_tools.extend(tools)
            except Exception as e:
                logger.warning("Failed to list tools from [%s]: %s", name, e)
        return all_tools

    # =========================================================================
    # 工具调用
    # =========================================================================

    async def call_tool(self, tool_name: str, arguments: dict) -> str:
        """调用任意已注册的工具

        自动查找工具所属的 MCP Server 并转发调用。

        Args:
            tool_name: 工具名称
            arguments: 参数字典

        Returns:
            工具执行结果文本

        Raises:
            MCPToolError: 工具未找到或调用失败
        """
        server_name = self._tool_index.get(tool_name)
        if server_name is None:
            # 尝试重新构建索引
            await self._build_tool_index()
            server_name = self._tool_index.get(tool_name)
            if server_name is None:
                raise MCPToolError(f"Tool not found: {tool_name}")

        conn = self._connections.get(server_name)
        if conn is None:
            raise MCPToolError(f"MCP server [{server_name}] not connected")

        if not conn.is_running:
            logger.warning("MCP server [%s] not running, attempting restart...", server_name)
            await conn.restart()
            await self._build_tool_index()

        try:
            return await conn.call_tool(tool_name, arguments)
        except MCPToolError:
            raise
        except Exception as e:
            raise MCPToolError(f"Error calling {tool_name}: {e}")

    def get_langchain_tools(self, tool_names: list[str] | None = None):
        """将 MCP 工具转为 LangChain @tool 兼容格式。

        返回 LangChain Tool 列表，可直接传给 Agent 的 bind_tools()。

        Args:
            tool_names: 要转换的工具名列表，None = 全部

        Returns:
            LangChain Tool 对象列表
        """
        from langchain_core.tools import tool as lc_tool

        tools = []
        for tname, sname in self._tool_index.items():
            if tool_names is not None and tname not in tool_names:
                continue
            conn = self._connections.get(sname)
            if conn is None:
                continue

            # 查找工具schema
            # 创建一个闭包来捕获 tool_name
            def _make_tool_func(name: str):
                async def _call(**kwargs):
                    return await self.call_tool(name, kwargs)
                return _call

            tool_func = _make_tool_func(tname)

            # 设置工具元数据
            tool_func.__name__ = tname
            tool_func.__doc__ = f"MCP tool: {tname}"

            # 创建 LangChain Tool
            lc_tool_obj = lc_tool(tool_func)
            # 注意：需要进一步设置 schema，这里先返回基本形式
            tools.append(lc_tool_obj)

        return tools


# =============================================================================
# 全局单例
# =============================================================================

_client: MCPClient | None = None


def get_mcp_client(project_root: str | None = None) -> MCPClient:
    """获取全局 MCP Client 单例"""
    global _client
    if _client is None:
        _client = MCPClient(project_root)
    return _client


async def reset_mcp_client():
    """重置 MCP Client（测试用）"""
    global _client
    if _client:
        await _client.stop_all()
    _client = None
