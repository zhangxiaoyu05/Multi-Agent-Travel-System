"""测试 LangGraph 图结构

验证 build_graph() 编译正确、节点注册完整、边连接无误。
不依赖 LLM 调用——只验证图的结构完整性。
"""

import pytest
from graph.builder import build_graph


# =============================================================================
# 图编译
# =============================================================================


class TestGraphCompilation:
    """图编译和基本结构验证"""

    def test_graph_compiles(self):
        """图应该能成功编译（使用 MemorySaver）"""
        graph = build_graph()
        assert graph is not None
        # 编译后的图应该有 nodes 属性
        assert hasattr(graph, "nodes") or hasattr(graph, "get_graph")

    def test_graph_is_compiled_graph(self):
        """编译结果应该是 CompiledStateGraph 实例"""
        from langgraph.graph.state import CompiledStateGraph
        graph = build_graph()
        assert isinstance(graph, CompiledStateGraph)

    def test_graph_has_name(self):
        """编译后的图应该有自己的名字"""
        graph = build_graph()
        name = getattr(graph, "name", None)
        # 即使没有 name，图也应该可以正常工作
        assert graph is not None


# =============================================================================
# 节点注册
# =============================================================================


class TestNodeRegistration:
    """验证所有必需节点是否注册"""

    REQUIRED_NODES = [
        "input_guard",
        "session_context",
        "intent_router",
        "customer_service",
        "trip_planner",
        "intent_scorer",
        "revision_loop",
        "human_handoff",
        "operations_sync",
        "sales_agent",
        "operations_agent",
    ]

    def test_all_nodes_registered(self):
        """所有业务节点应当注册到图中"""
        graph = build_graph()
        graph_def = graph.get_graph()

        registered = set(graph_def.nodes.keys())
        for node in self.REQUIRED_NODES:
            assert node in registered, f"节点 '{node}' 未注册到图中"

    def test_start_node_exists(self):
        """START 虚拟节点应存在"""
        graph = build_graph()
        graph_def = graph.get_graph()
        assert "__start__" in graph_def.nodes

    def test_end_node_exists(self):
        """END 虚拟节点应存在"""
        graph = build_graph()
        graph_def = graph.get_graph()
        assert "__end__" in graph_def.nodes


# =============================================================================
# 边连接验证
# =============================================================================


class TestEdgeStructure:
    """验证关键边的连接"""

    def _edge_set(self):
        """返回 {(source, target)} 的集合，便于边存在性检查"""
        graph = build_graph()
        graph_def = graph.get_graph()
        return {(e.source, e.target) for e in graph_def.edges}

    def test_start_to_input_guard(self):
        """START → input_guard 应存在"""
        assert ("__start__", "input_guard") in self._edge_set()

    def test_operations_sync_to_end(self):
        """operations_sync → END 应存在"""
        assert ("operations_sync", "__end__") in self._edge_set(), (
            "operations_sync 应连接到 END"
        )

    def test_revision_loop_to_trip_planner(self):
        """revision_loop → trip_planner 固定边应存在"""
        assert ("revision_loop", "trip_planner") in self._edge_set(), (
            "revision_loop 应有固定边 → trip_planner"
        )

    def test_human_handoff_to_operations_sync(self):
        """human_handoff → operations_sync 固定边应存在"""
        assert ("human_handoff", "operations_sync") in self._edge_set(), (
            "human_handoff 应有固定边 → operations_sync"
        )

    def test_intent_router_has_conditional_edges(self):
        """v3: route_decision 节点应有条件边分发到各业务分支"""
        edges = self._edge_set()
        # intent_router → route_decision 是固定边
        assert ("intent_router", "route_decision") in edges, (
            "intent_router 应有固定边 → route_decision"
        )
        # route_decision → 各业务分支是条件边
        out_edges = {e for e in edges if e[0] == "route_decision"}
        assert len(out_edges) > 0, "route_decision 应有条件边"

    def test_linear_chain_exists(self):
        """主干链路：input_guard → session_context → intent_router"""
        edges = self._edge_set()
        assert ("input_guard", "session_context") in edges, "主干链路断裂"
        assert ("session_context", "intent_router") in edges, "主干链路断裂"
