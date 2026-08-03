"""MCP (Model Context Protocol) 工具标准化层

轻量级 JSON-RPC 2.0 over stdio 实现，不依赖 mcp 官方 SDK。

架构：
    Agent ─→ MCPClient (services/mcp_client.py)
                │
                ├──→ Weather MCP Server   (stdio subprocess)
                ├──→ Calendar MCP Server  (stdio subprocess)
                ├──→ Inventory MCP Server (stdio subprocess)
                ├──→ Quote MCP Server     (stdio subprocess)
                ├──→ CRM MCP Server       (stdio subprocess)
                └──→ CAPI MCP Server      (stdio subprocess)

每个 MCP Server 是独立的 Python 进程，通过 stdin/stdout 进行 JSON-RPC 通信。
Server 崩溃不影响 Agent 主进程。
"""
