"""MCP 风格工具发现测试。"""

from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest


class MCPToolDiscoveryTest(unittest.TestCase):
    """验证 MCP 工具目录发现与工厂构建。"""

    @classmethod
    def setUpClass(cls) -> None:
        """按文件路径加载模块，避免触发完整工程初始化。"""
        module_path = (
            Path(__file__).resolve().parent.parent
            / "graphrag_agent"
            / "mcp"
            / "discovery.py"
        )
        spec = importlib.util.spec_from_file_location(
            "test_mcp_discovery_module",
            module_path,
        )
        assert spec is not None
        assert spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(module)
        except ModuleNotFoundError as exc:  # pragma: no cover - 环境缺依赖时跳过
            raise unittest.SkipTest(f"当前环境缺少依赖，跳过 MCP 发现测试: {exc}") from exc
        cls.module = module

    def test_discover_mcp_tools_from_http_catalog(self) -> None:
        """应能从远程目录读取工具描述。"""
        descriptor = self.module.MCPToolDescriptor(
            name="demo_calc",
            description="示例计算工具",
            input_schema={
                "type": "object",
                "properties": {"value": {"type": "number", "description": "输入值"}},
                "required": ["value"],
            },
            invoke_path="/tools/demo_calc/invoke",
            endpoint="http://127.0.0.1:8011",
        )

        class _FakeClient:
            def __init__(self, endpoint: str) -> None:
                self.endpoint = endpoint

            def list_tools(self):
                return [descriptor]

        original_client = self.module.HttpMCPToolClient
        self.module.HttpMCPToolClient = _FakeClient
        try:
            tools = self.module.discover_mcp_tools(["http://127.0.0.1:8011"])
        finally:
            self.module.HttpMCPToolClient = original_client

        self.assertIn("demo_calc", tools)
        self.assertEqual(
            tools["demo_calc"].invoke_url,
            "http://127.0.0.1:8011/tools/demo_calc/invoke",
        )

    def test_build_dynamic_extra_tool_factories(self) -> None:
        """应能把远程目录转换为本地工具工厂。"""
        descriptor = self.module.MCPToolDescriptor(
            name="demo_calc",
            description="示例计算工具",
            input_schema={
                "type": "object",
                "properties": {"value": {"type": "number", "description": "输入值"}},
            },
            invoke_path="/tools/demo_calc/invoke",
            endpoint="http://127.0.0.1:8011",
        )

        original_discover = self.module.discover_mcp_tools
        self.module.discover_mcp_tools = lambda endpoints=None: {"demo_calc": descriptor}
        try:
            factories = self.module.build_dynamic_extra_tool_factories(["http://127.0.0.1:8011"])
        finally:
            self.module.discover_mcp_tools = original_discover

        self.assertIn("demo_calc", factories)
        instance = factories["demo_calc"]()
        self.assertEqual(instance.name, "demo_calc")
        self.assertTrue(hasattr(instance, "get_tool"))


if __name__ == "__main__":
    unittest.main()
