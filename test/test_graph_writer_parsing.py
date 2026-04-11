"""验证 GraphWriter 对常见 LLM 输出格式的解析兼容性。"""

from __future__ import annotations

import unittest

class TestGraphWriterParsing(unittest.TestCase):
    """覆盖实体关系抽取结果的关键解析场景。"""

    def setUp(self) -> None:
        """初始化一个不依赖真实图数据库连接的写入器实例。"""
        try:
            from graphrag_agent.graph.extraction.graph_writer import GraphWriter
        except ModuleNotFoundError as exc:
            self.skipTest(f"当前环境缺少依赖，无法导入 GraphWriter: {exc}")
            return

        self.writer = GraphWriter(graph=object())

    def test_parse_unquoted_fields(self) -> None:
        """应兼容字段不带引号的传统输出格式。"""
        result = (
            '("entity" : THERMOSCOPE : Equipment : 验温器是一种温度指示装置。)\n\n'
            '("relationship" : THERMOSCOPE : THERMOMETER : RELATED_TO : '
            '验温器与温度计属于同类测温设备。 : 8)'
        )

        graph_document = self.writer.convert_to_graph_document(
            chunk_id="chunk-1",
            input_text="dummy",
            result=result,
        )

        self.assertEqual(len(graph_document.nodes), 2)
        self.assertEqual(len(graph_document.relationships), 1)
        self.assertEqual(graph_document.nodes[0].properties["description"], "验温器是一种温度指示装置。")

    def test_parse_quoted_fields_with_markdown_noise(self) -> None:
        """应兼容字段带引号且混入 Markdown 标记的输出。"""
        result = (
            '**("entity" : "热平衡" : "Concept" : "系统之间没有净热流交换的状态。")\n'
            '**("relationship" : "热力学第零定律" : "热平衡" : "DEFINES" : '
            '"第零定律定义了热平衡的判据。" : 10)'
        )

        graph_document = self.writer.convert_to_graph_document(
            chunk_id="chunk-2",
            input_text="dummy",
            result=result,
        )

        self.assertEqual(len(graph_document.nodes), 2)
        self.assertEqual(len(graph_document.relationships), 1)
        self.assertEqual(graph_document.relationships[0].properties["weight"], 10.0)

    def test_parse_description_with_parentheses_and_colons(self) -> None:
        """应兼容描述中包含括号与冒号的复杂文本。"""
        result = (
            '("entity" : "状态方程(3.56)" : "Formula" : '
            '"形式为 sigma(T) = sigma0 * (1 - T/Tc)^n，用于描述表面张力随温度变化。")\n\n'
            '("relationship" : "状态方程(3.56)" : "表面张力" : "DEFINES" : '
            '"该公式给出了表面张力与温度的函数关系: 适用于单元系气液界面。" : "9")'
        )

        graph_document = self.writer.convert_to_graph_document(
            chunk_id="chunk-3",
            input_text="dummy",
            result=result,
        )

        self.assertEqual(len(graph_document.nodes), 2)
        self.assertEqual(len(graph_document.relationships), 1)
        self.assertIn("函数关系", graph_document.relationships[0].properties["description"])


if __name__ == "__main__":
    unittest.main()
