"""流体物性独立服务测试。"""

from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch


try:
    from fastapi.testclient import TestClient
except ModuleNotFoundError:  # pragma: no cover - 依赖缺失时自动跳过
    TestClient = None


@unittest.skipIf(TestClient is None, "当前环境未安装 fastapi，跳过独立服务接口测试")
class FluidPropertyServiceTest(unittest.TestCase):
    """验证流体物性服务的 MCP 风格接口。"""

    @classmethod
    def setUpClass(cls) -> None:
        """按文件路径加载服务模块。"""
        module_path = (
            Path(__file__).resolve().parent.parent
            / "tool_services"
            / "fluid_property_service"
            / "app.py"
        )
        spec = importlib.util.spec_from_file_location(
            "test_fluid_property_service_module",
            module_path,
        )
        assert spec is not None
        assert spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        cls.module = module

    def setUp(self) -> None:
        """初始化测试客户端。"""
        self.client = TestClient(self.module.app)

    def test_tools_endpoint_returns_catalog(self) -> None:
        """工具目录应暴露名称、描述和输入模式。"""
        response = self.client.get("/tools")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["tools"][0]["name"], "fluid_property_calc")
        self.assertIn("input_schema", payload["tools"][0])

    def test_invoke_endpoint_returns_engine_payload(self) -> None:
        """工具调用接口应透传引擎结果。"""
        with patch.object(self.module.engine, "structured_search") as mock_structured_search:
            mock_structured_search.return_value = {
                "success": True,
                "results": {"H": 123.4},
                "metadata": {"notes": []},
                "error": None,
                "retrieval_results": [],
                "answer": "流体物性计算成功: {'H': 123.4}",
                "query": "fluid=Water",
            }
            response = self.client.post(
                "/tools/fluid_property_calc/invoke",
                json={"fluid": "Water", "inputs": {"T": 300, "P": 101.325}, "outputs": ["H"]},
            )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["success"])
        self.assertEqual(response.json()["results"]["H"], 123.4)


if __name__ == "__main__":
    unittest.main()
