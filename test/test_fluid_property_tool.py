"""流体物性工具测试。"""

from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import types
import unittest


class FluidPropertyToolTest(unittest.TestCase):
    """验证流体物性计算工具的核心行为。"""

    @classmethod
    def setUpClass(cls) -> None:
        """按文件路径加载模块，避免测试时触发完整工程初始化。"""
        fake_langchain_core = types.ModuleType("langchain_core")
        fake_tools_module = types.ModuleType("langchain_core.tools")

        class _FakeBaseTool:
            """最小化 BaseTool 替身，满足模块导入即可。"""

            pass

        fake_tools_module.BaseTool = _FakeBaseTool
        sys.modules.setdefault("langchain_core", fake_langchain_core)
        sys.modules["langchain_core.tools"] = fake_tools_module

        module_path = (
            Path(__file__).resolve().parent.parent
            / "graphrag_agent"
            / "search"
            / "tool"
            / "fluid_property_tool.py"
        )
        spec = importlib.util.spec_from_file_location(
            "test_fluid_property_tool_module",
            module_path,
        )
        assert spec is not None
        assert spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        cls.module = module

    def test_calculate_converts_units_and_returns_expected_keys(self) -> None:
        """应正确做工程单位换算并输出结果。"""
        seen_calls = []

        def fake_props_si(output: str, key1: str, value1: float, key2: str, value2: float, fluid: str) -> float:
            seen_calls.append((output, key1, value1, key2, value2, fluid))
            fake_values = {
                "Hmass": 2000000.0,
                "Smass": 200000.0,
            }
            return fake_values[output]

        original_loader = self.module._load_props_si
        self.module._load_props_si = lambda: fake_props_si
        try:
            tool = self.module.FluidPropertyTool()
            response = tool.calculate(
                {
                    "fluid": "Water",
                    "inputs": {"T": 300.0, "P": 101.325},
                    "outputs": ["H", "S"],
                }
            )
        finally:
            self.module._load_props_si = original_loader

        self.assertTrue(response["success"])
        self.assertEqual(response["error"], None)
        self.assertEqual(response["results"]["H"], 2000.0)
        self.assertEqual(response["results"]["S"], 200.0)
        self.assertEqual(seen_calls[:2], [
            ("Hmass", "T", 300.0, "P", 101325.0, "Water"),
            ("Smass", "T", 300.0, "P", 101325.0, "Water"),
        ])
        self.assertIn(
            ("Phase", "T", 300.0, "P", 101325.0, "Water"),
            seen_calls,
        )
        self.assertIn(
            ("T", "P", 101325.0, "Q", 0, "Water"),
            seen_calls,
        )

    def test_calculate_returns_error_for_invalid_input_count(self) -> None:
        """状态参数数量不合法时应返回失败结果。"""
        tool = self.module.FluidPropertyTool()
        response = tool.calculate(
            {
                "fluid": "Water",
                "inputs": {"T": 300.0},
                "outputs": ["H"],
            }
        )
        self.assertFalse(response["success"])
        self.assertIn("inputs 必须且只能提供两个状态参数", response["error"])

    def test_structured_search_returns_executor_friendly_payload(self) -> None:
        """结构化接口应兼容多 Agent 执行器。"""
        tool = self.module.FluidPropertyTool()
        original_calculate = tool.calculate
        tool.calculate = lambda _payload: {
            "success": True,
            "results": {"D": 0.8},
            "error": None,
        }
        try:
            response = tool.structured_search(
                {
                    "fluid": "Air",
                    "inputs": {"T": 300.0, "P": 101.325},
                    "outputs": ["D"],
                }
            )
        finally:
            tool.calculate = original_calculate

        self.assertTrue(response["success"])
        self.assertEqual(response["results"], {"D": 0.8})
        self.assertEqual(response["retrieval_results"], [])
        self.assertIn("流体物性计算成功", response["answer"])

    def test_calculate_can_extract_payload_from_query_text(self) -> None:
        """当执行器只传入自然语言 query 时，工具也应能提取参数。"""
        seen_calls = []

        def fake_props_si(output: str, key1: str, value1: float, key2: str, value2: float, fluid: str) -> float:
            seen_calls.append((output, key1, value1, key2, value2, fluid))
            return {
                "Hmass": 112345.0,
                "Smass": 393.21,
            }[output]

        original_loader = self.module._load_props_si
        self.module._load_props_si = lambda: fake_props_si
        try:
            tool = self.module.FluidPropertyTool()
            response = tool.calculate(
                {
                    "query": "请计算 Water 在 T=300 K、P=101.325 kPa 下的 H 和 S",
                }
            )
        finally:
            self.module._load_props_si = original_loader

        self.assertTrue(response["success"])
        self.assertIn("H", response["results"])
        self.assertIn("S", response["results"])
        self.assertEqual(seen_calls[:2], [
            ("Hmass", "T", 300.0, "P", 101325.0, "Water"),
            ("Smass", "T", 300.0, "P", 101325.0, "Water"),
        ])
        self.assertIn(
            ("Phase", "T", 300.0, "P", 101325.0, "Water"),
            seen_calls,
        )
        self.assertIn(
            ("T", "P", 101325.0, "Q", 0, "Water"),
            seen_calls,
        )

    def test_calculate_converts_pressure_enthalpy_inputs_and_temperature_entropy_outputs(self) -> None:
        """应正确处理 P-H 输入与 T-S 输出的工程单位换算。"""
        seen_calls = []

        def fake_props_si(
            output: str,
            key1: str,
            value1: float,
            key2: str,
            value2: float,
            fluid: str,
        ) -> float:
            seen_calls.append((output, key1, value1, key2, value2, fluid))
            return {
                "T": 373.1243,
                "Smass": 7354.0,
            }[output]

        original_loader = self.module._load_props_si
        self.module._load_props_si = lambda: fake_props_si
        try:
            tool = self.module.FluidPropertyTool()
            response = tool.calculate(
                {
                    "fluid": "Water",
                    "inputs": {"P": 101.325, "H": 2676.0},
                    "outputs": ["T", "S"],
                }
            )
        finally:
            self.module._load_props_si = original_loader

        self.assertTrue(response["success"])
        self.assertAlmostEqual(response["results"]["T"], 373.1243)
        self.assertAlmostEqual(response["results"]["S"], 7.354)
        self.assertEqual(seen_calls[:2], [
            ("T", "P", 101325.0, "Hmass", 2676000.0, "Water"),
            ("Smass", "P", 101325.0, "Hmass", 2676000.0, "Water"),
        ])
        self.assertIn(
            ("Phase", "P", 101325.0, "Hmass", 2676000.0, "Water"),
            seen_calls,
        )

    def test_calculate_supports_multiple_query_phrasings_for_same_ph_state(self) -> None:
        """不同自然语言表述下，应能解析出相同的 P-H 物性计算请求。"""
        cases = [
            "已知 Water 的 P = 101.325 kPa、H = 2676 kJ/kg，求 T 和 S",
            "对于 H2O，已知压力: 101.325 kPa，比焓: 2676，计算温度和比熵",
            "已知 steam 的压力 = 101.325 kPa、比焓 = 2676，求温度和熵",
        ]

        original_loader = self.module._load_props_si
        try:
            for query in cases:
                seen_calls = []

                def fake_props_si(
                    output: str,
                    key1: str,
                    value1: float,
                    key2: str,
                    value2: float,
                    fluid: str,
                ) -> float:
                    seen_calls.append((output, key1, value1, key2, value2, fluid))
                    return {
                        "T": 373.1243,
                        "Smass": 7354.0,
                    }[output]

                self.module._load_props_si = lambda: fake_props_si
                tool = self.module.FluidPropertyTool()

                with self.subTest(query=query):
                    response = tool.calculate({"query": query})
                    self.assertTrue(response["success"])
                    self.assertAlmostEqual(response["results"]["T"], 373.1243)
                    self.assertAlmostEqual(response["results"]["S"], 7.354)
                    self.assertCountEqual(
                        seen_calls[:2],
                        [
                            ("T", "P", 101325.0, "Hmass", 2676000.0, "Water"),
                            ("Smass", "P", 101325.0, "Hmass", 2676000.0, "Water"),
                        ],
                    )
                    self.assertIn(
                        ("Phase", "P", 101325.0, "Hmass", 2676000.0, "Water"),
                        seen_calls,
                    )
        finally:
            self.module._load_props_si = original_loader

    def test_calculate_supports_chinese_steam_aliases(self) -> None:
        """中文工质别名如“水蒸气”“蒸汽”应能映射到 Water。"""
        cases = [
            "已知水蒸气的压力 = 300 kPa、比焓 = 2800，求温度和比熵",
            "蒸汽在 P=300 kPa、H=2800 kJ/kg 下，求 T 和 S",
        ]

        original_loader = self.module._load_props_si
        try:
            for query in cases:
                seen_calls = []

                def fake_props_si(
                    output: str,
                    key1: str,
                    value1: float,
                    key2: str,
                    value2: float,
                    fluid: str,
                ) -> float:
                    seen_calls.append((output, key1, value1, key2, value2, fluid))
                    return {
                        "T": 406.67,
                        "Smass": 7100.0,
                    }[output]

                self.module._load_props_si = lambda: fake_props_si
                tool = self.module.FluidPropertyTool()

                with self.subTest(query=query):
                    response = tool.calculate({"query": query})
                    self.assertTrue(response["success"])
                    self.assertAlmostEqual(response["results"]["T"], 406.67)
                    self.assertAlmostEqual(response["results"]["S"], 7.1)
                    self.assertCountEqual(
                        seen_calls[:2],
                        [
                            ("T", "P", 300000.0, "Hmass", 2800000.0, "Water"),
                            ("Smass", "P", 300000.0, "Hmass", 2800000.0, "Water"),
                        ],
                    )
        finally:
            self.module._load_props_si = original_loader

    def test_calculate_uses_llm_fallback_when_rule_parser_misses_fluid(self) -> None:
        """规则未识别工质时，应允许 LLM 兜底补全结构化请求。"""
        seen_calls = []

        def fake_props_si(
            output: str,
            key1: str,
            value1: float,
            key2: str,
            value2: float,
            fluid: str,
        ) -> float:
            seen_calls.append((output, key1, value1, key2, value2, fluid))
            return {
                "T": 406.67,
                "Smass": 7100.0,
            }[output]

        original_loader = self.module._load_props_si
        original_fallback = self.module.FluidPropertyTool._extract_with_llm_fallback
        self.module._load_props_si = lambda: fake_props_si
        self.module.FluidPropertyTool._extract_with_llm_fallback = lambda self, _query: {
            "fluid": "Water",
            "inputs": {"P": 300.0, "H": 2800.0},
            "outputs": ["T", "S"],
        }
        try:
            tool = self.module.FluidPropertyTool()
            response = tool.calculate(
                {
                    "query": "已知工质为去离子水产生的饱和蒸汽，压力 300 kPa、比焓 2800 kJ/kg，求温度和比熵",
                }
            )
        finally:
            self.module._load_props_si = original_loader
            self.module.FluidPropertyTool._extract_with_llm_fallback = original_fallback

        self.assertTrue(response["success"])
        self.assertAlmostEqual(response["results"]["T"], 406.67)
        self.assertAlmostEqual(response["results"]["S"], 7.1)
        self.assertCountEqual(
            seen_calls[:2],
            [
                ("T", "P", 300000.0, "Hmass", 2800000.0, "Water"),
                ("Smass", "P", 300000.0, "Hmass", 2800000.0, "Water"),
            ],
        )

    def test_calculate_supports_air_density_example(self) -> None:
        """应支持 Air 在 T-P 条件下计算密度样例。"""
        seen_calls = []

        def fake_props_si(
            output: str,
            key1: str,
            value1: float,
            key2: str,
            value2: float,
            fluid: str,
        ) -> float:
            seen_calls.append((output, key1, value1, key2, value2, fluid))
            return {"Dmass": 1.176}[output]

        original_loader = self.module._load_props_si
        self.module._load_props_si = lambda: fake_props_si
        try:
            tool = self.module.FluidPropertyTool()
            response = tool.calculate(
                {
                    "query": "请计算 Air 在 T=300 K、P=101.325 kPa 下的 D",
                }
            )
        finally:
            self.module._load_props_si = original_loader
        self.assertTrue(response["success"])
        self.assertAlmostEqual(response["results"]["D"], 1.176)
        self.assertEqual(
            seen_calls[:2],
            [
                ("Dmass", "T", 300.0, "P", 101325.0, "Air"),
                ("Phase", "T", 300.0, "P", 101325.0, "Air"),
            ],
        )

    def test_calculate_supports_r134a_pressure_quality_example(self) -> None:
        """应支持 R134a 在 P-Q 条件下计算 T 和 H。"""
        seen_calls = []

        def fake_props_si(
            output: str,
            key1: str,
            value1: float,
            key2: str,
            value2: float,
            fluid: str,
        ) -> float:
            seen_calls.append((output, key1, value1, key2, value2, fluid))
            return {
                "T": 278.15,
                "Hmass": 398500.0,
            }[output]

        original_loader = self.module._load_props_si
        self.module._load_props_si = lambda: fake_props_si
        try:
            tool = self.module.FluidPropertyTool()
            response = tool.calculate(
                {
                    "query": "已知 R134a 的 P = 700 kPa、Q = 0.2，求 T 和 H",
                }
            )
        finally:
            self.module._load_props_si = original_loader

        self.assertTrue(response["success"])
        self.assertAlmostEqual(response["results"]["T"], 278.15)
        self.assertAlmostEqual(response["results"]["H"], 398.5)
        self.assertEqual(
            seen_calls[:3],
            [
                ("T", "P", 700000.0, "Q", 0.2, "R134a"),
                ("Hmass", "P", 700000.0, "Q", 0.2, "R134a"),
                ("Phase", "P", 700000.0, "Q", 0.2, "R134a"),
            ],
        )

    def test_calculate_supports_ammonia_mixed_language_example(self) -> None:
        """应支持 Ammonia/NH3 的中英混合自然语言样例。"""
        seen_calls = []

        def fake_props_si(
            output: str,
            key1: str,
            value1: float,
            key2: str,
            value2: float,
            fluid: str,
        ) -> float:
            seen_calls.append((output, key1, value1, key2, value2, fluid))
            return {
                "P": 856000.0,
                "Smass": 5120.0,
            }[output]

        original_loader = self.module._load_props_si
        self.module._load_props_si = lambda: fake_props_si
        try:
            tool = self.module.FluidPropertyTool()
            response = tool.calculate(
                {
                    "query": "对于 NH3，温度=320 K、密度=5 kg/m^3，求 P 和 S",
                }
            )
        finally:
            self.module._load_props_si = original_loader

        self.assertTrue(response["success"])
        self.assertAlmostEqual(response["results"]["P"], 856.0)
        self.assertAlmostEqual(response["results"]["S"], 5.12)
        self.assertCountEqual(
            seen_calls[:3],
            [
                ("P", "T", 320.0, "Dmass", 5.0, "Ammonia"),
                ("Smass", "T", 320.0, "Dmass", 5.0, "Ammonia"),
                ("Phase", "T", 320.0, "Dmass", 5.0, "Ammonia"),
            ],
        )

    def test_calculate_supports_twenty_batch_query_samples(self) -> None:
        """应支持 20 组不同工质、状态量组合与表述格式的批量样例。"""
        cases = [
            {
                "query": "请计算 Water 在 T=300 K、P=101.325 kPa 下的 H 和 S",
                "expected_calls": [("Hmass", "T", 300.0, "P", 101325.0, "Water"), ("Smass", "T", 300.0, "P", 101325.0, "Water")],
                "fake_values": {"Hmass": 120000.0, "Smass": 420.0},
                "expected_results": {"H": 120.0, "S": 0.42},
            },
            {
                "query": "Water 在 T=320 K、P=200 kPa 下，求 H 和 S",
                "expected_calls": [("Hmass", "T", 320.0, "P", 200000.0, "Water"), ("Smass", "T", 320.0, "P", 200000.0, "Water")],
                "fake_values": {"Hmass": 180000.0, "Smass": 650.0},
                "expected_results": {"H": 180.0, "S": 0.65},
            },
            {
                "query": "已知 steam 的温度 = 350 K、压力 = 500 kPa，计算焓和熵",
                "expected_calls": [("Hmass", "T", 350.0, "P", 500000.0, "Water"), ("Smass", "T", 350.0, "P", 500000.0, "Water")],
                "fake_values": {"Hmass": 2600000.0, "Smass": 6800.0},
                "expected_results": {"H": 2600.0, "S": 6.8},
            },
            {
                "query": "对于 H2O，温度: 373.15 K，压力: 101.325 kPa，求 H、S",
                "expected_calls": [("Hmass", "T", 373.15, "P", 101325.0, "Water"), ("Smass", "T", 373.15, "P", 101325.0, "Water")],
                "fake_values": {"Hmass": 2676000.0, "Smass": 7350.0},
                "expected_results": {"H": 2676.0, "S": 7.35},
            },
            {
                "query": "已知 Water 的 P = 101.325 kPa、H = 2676 kJ/kg，求 T 和 S",
                "expected_calls": [("T", "P", 101325.0, "Hmass", 2676000.0, "Water"), ("Smass", "P", 101325.0, "Hmass", 2676000.0, "Water")],
                "fake_values": {"T": 373.1243, "Smass": 7354.0},
                "expected_results": {"T": 373.1243, "S": 7.354},
            },
            {
                "query": "蒸汽在 P=300 kPa、H=2800 kJ/kg 下，求 T 和 S",
                "expected_calls": [("T", "P", 300000.0, "Hmass", 2800000.0, "Water"), ("Smass", "P", 300000.0, "Hmass", 2800000.0, "Water")],
                "fake_values": {"T": 406.67, "Smass": 7100.0},
                "expected_results": {"T": 406.67, "S": 7.1},
            },
            {
                "query": "已知水蒸气的压力 = 500 kPa、比焓 = 2900，求温度和比熵",
                "expected_calls": [("T", "P", 500000.0, "Hmass", 2900000.0, "Water"), ("Smass", "P", 500000.0, "Hmass", 2900000.0, "Water")],
                "fake_values": {"T": 425.0, "Smass": 7250.0},
                "expected_results": {"T": 425.0, "S": 7.25},
            },
            {
                "query": "Air 在 T=300 K、P=101.325 kPa 下，求 D",
                "expected_calls": [("Dmass", "T", 300.0, "P", 101325.0, "Air")],
                "fake_values": {"Dmass": 1.176},
                "expected_results": {"D": 1.176},
            },
            {
                "query": "请计算空气在 T=320 K、P=200 kPa 下的密度",
                "expected_calls": [("Dmass", "T", 320.0, "P", 200000.0, "Air")],
                "fake_values": {"Dmass": 2.18},
                "expected_results": {"D": 2.18},
            },
            {
                "query": "对于 air，已知 T=280 K、P=150 kPa，求 D",
                "expected_calls": [("Dmass", "T", 280.0, "P", 150000.0, "Air")],
                "fake_values": {"Dmass": 1.87},
                "expected_results": {"D": 1.87},
            },
            {
                "query": "已知 R134a 的 P = 700 kPa、Q = 0.2，求 T 和 H",
                "expected_calls": [("T", "P", 700000.0, "Q", 0.2, "R134a"), ("Hmass", "P", 700000.0, "Q", 0.2, "R134a")],
                "fake_values": {"T": 278.15, "Hmass": 398500.0},
                "expected_results": {"T": 278.15, "H": 398.5},
            },
            {
                "query": "R134a 在 P=900 kPa、Q=0.8 下，求 T 和 H",
                "expected_calls": [("T", "P", 900000.0, "Q", 0.8, "R134a"), ("Hmass", "P", 900000.0, "Q", 0.8, "R134a")],
                "fake_values": {"T": 305.15, "Hmass": 420000.0},
                "expected_results": {"T": 305.15, "H": 420.0},
            },
            {
                "query": "请计算 r134a 在 P=400 kPa、Q=0.0 下的 T 和 H",
                "expected_calls": [("T", "P", 400000.0, "Q", 0.0, "R134a"), ("Hmass", "P", 400000.0, "Q", 0.0, "R134a")],
                "fake_values": {"T": 285.15, "Hmass": 200000.0},
                "expected_results": {"T": 285.15, "H": 200.0},
            },
            {
                "query": "对于 NH3，温度=320 K、密度=5 kg/m^3，求 P 和 S",
                "expected_calls": [("P", "T", 320.0, "Dmass", 5.0, "Ammonia"), ("Smass", "T", 320.0, "Dmass", 5.0, "Ammonia")],
                "fake_values": {"P": 856000.0, "Smass": 5120.0},
                "expected_results": {"P": 856.0, "S": 5.12},
            },
            {
                "query": "已知 ammonia 的 T=340 K、D=7 kg/m^3，求 P 和 S",
                "expected_calls": [("P", "T", 340.0, "Dmass", 7.0, "Ammonia"), ("Smass", "T", 340.0, "Dmass", 7.0, "Ammonia")],
                "fake_values": {"P": 1200000.0, "Smass": 4900.0},
                "expected_results": {"P": 1200.0, "S": 4.9},
            },
            {
                "query": "对于 nh3，T=300 K、D=3 kg/m^3，求 P 和 S",
                "expected_calls": [("P", "T", 300.0, "Dmass", 3.0, "Ammonia"), ("Smass", "T", 300.0, "Dmass", 3.0, "Ammonia")],
                "fake_values": {"P": 500000.0, "Smass": 5300.0},
                "expected_results": {"P": 500.0, "S": 5.3},
            },
            {
                "query": "CO2 在 T=300 K、P=800 kPa 下，求 D",
                "expected_calls": [("Dmass", "T", 300.0, "P", 800000.0, "CO2")],
                "fake_values": {"Dmass": 14.2},
                "expected_results": {"D": 14.2},
            },
            {
                "query": "请计算 co2 在 T=310 K、P=1000 kPa 下的 D",
                "expected_calls": [("Dmass", "T", 310.0, "P", 1000000.0, "CO2")],
                "fake_values": {"Dmass": 18.5},
                "expected_results": {"D": 18.5},
            },
            {
                "query": "carbon dioxide 在 T=290 K、P=600 kPa 下，求 D",
                "expected_calls": [("Dmass", "T", 290.0, "P", 600000.0, "CO2")],
                "fake_values": {"Dmass": 11.4},
                "expected_results": {"D": 11.4},
            },
            {
                "query": "Water 在 P=700 kPa、Q=1 下，求 T 和 H",
                "expected_calls": [("T", "P", 700000.0, "Q", 1.0, "Water"), ("Hmass", "P", 700000.0, "Q", 1.0, "Water")],
                "fake_values": {"T": 438.15, "Hmass": 2763000.0},
                "expected_results": {"T": 438.15, "H": 2763.0},
            },
        ]

        original_loader = self.module._load_props_si
        try:
            for case in cases:
                seen_calls = []

                def fake_props_si(
                    output: str,
                    key1: str,
                    value1: float,
                    key2: str,
                    value2: float,
                    fluid: str,
                    *,
                    _case=case,
                ) -> float:
                    seen_calls.append((output, key1, value1, key2, value2, fluid))
                    if output == "Phase":
                        return 5.0
                    if output == "T" and key2 == "Q":
                        return _case["fake_values"].get("T", 300.0)
                    if output == "P" and key2 == "Q":
                        return _case["fake_values"].get("P", 101325.0) * 1000.0
                    return _case["fake_values"][output]

                self.module._load_props_si = lambda _case=case: fake_props_si
                tool = self.module.FluidPropertyTool()

                with self.subTest(query=case["query"]):
                    response = tool.calculate({"query": case["query"]})
                    self.assertTrue(response["success"])
                    for output_name, expected_value in case["expected_results"].items():
                        self.assertAlmostEqual(response["results"][output_name], expected_value)
                    self.assertCountEqual(
                        seen_calls[: len(case["expected_calls"])],
                        case["expected_calls"],
                    )
        finally:
            self.module._load_props_si = original_loader

    def test_calculate_marks_quality_undefined_in_single_phase_region(self) -> None:
        """单相区下若 Q 返回 -1，应转成更安全的展示语义。"""
        seen_calls = []

        def fake_props_si(output: str, key1: str, value1: float, key2: str, value2: float, fluid: str) -> float:
            seen_calls.append(output)
            fake_values = {
                "Q": -1.0,
                "Phase": 5.0,
                "T": 373.1243,
                "P": 101417.99666,
            }
            return fake_values[output]

        original_loader = self.module._load_props_si
        self.module._load_props_si = lambda: fake_props_si
        try:
            tool = self.module.FluidPropertyTool()
            response = tool.calculate(
                {
                    "fluid": "Water",
                    "inputs": {"T": 373.15, "P": 101.325},
                    "outputs": ["Q"],
                }
            )
        finally:
            self.module._load_props_si = original_loader

        self.assertTrue(response["success"])
        self.assertIsNone(response["results"]["Q"])
        self.assertEqual(response["metadata"]["raw_results"]["Q"], -1.0)
        self.assertTrue(response["metadata"]["near_saturation"])
        self.assertFalse(response["metadata"]["state_pair_independent"])
        self.assertTrue(
            any("干度 Q 无定义" in note for note in response["metadata"]["notes"])
        )

    def test_structured_search_keeps_metadata(self) -> None:
        """结构化返回应保留状态说明元数据，供上层格式化。"""
        tool = self.module.FluidPropertyTool()
        original_calculate = tool.calculate
        tool.calculate = lambda _payload: {
            "success": True,
            "results": {"Q": None},
            "metadata": {"notes": ["当前状态位于单相区，干度 Q 无定义。"]},
            "error": None,
        }
        try:
            response = tool.structured_search(
                {
                    "fluid": "Water",
                    "inputs": {"T": 373.15, "P": 101.325},
                    "outputs": ["Q"],
                }
            )
        finally:
            tool.calculate = original_calculate

        self.assertEqual(response["metadata"]["notes"][0], "当前状态位于单相区，干度 Q 无定义。")


if __name__ == "__main__":
    unittest.main()
