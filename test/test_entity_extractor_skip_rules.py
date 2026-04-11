"""验证实体抽取阶段的 chunk 跳过规则不会误杀正文。"""

from __future__ import annotations

import unittest


class TestEntityExtractorSkipRules(unittest.TestCase):
    """覆盖低价值 chunk 过滤规则的关键边界。"""

    def setUp(self) -> None:
        """初始化一个不依赖真实模型调用的抽取器实例。"""
        try:
            from graphrag_agent.graph.extraction.entity_extractor import (
                EntityRelationExtractor,
            )
        except ModuleNotFoundError as exc:
            self.skipTest(f"当前环境缺少依赖，无法导入 EntityRelationExtractor: {exc}")
            return

        # 仅验证纯规则函数，避免在测试中依赖真实 LLM Runnable 初始化。
        self.extractor = EntityRelationExtractor.__new__(EntityRelationExtractor)

    def test_should_not_skip_long_english_prose(self) -> None:
        """长篇英文教材正文不应被误判为低价值文本。"""
        text = (
            "When you are solving a problem, we recommend that you use the following "
            "steps zealously as applicable. This will help you avoid some of the common "
            "pitfalls associated with problem solving. Step 1: Problem Statement. In your "
            "own words, briefly state the problem, the key information given, and the "
            "quantities to be found. This is to make sure that you understand the problem "
            "and the objectives before you try to solve the problem. Step 2: Schematic. "
            "Draw a realistic sketch of the physical system involved, and list the relevant "
            "information on the figure. The sketch does not have to be something elaborate, "
            "but it should resemble the actual system and show the key features."
        )
        self.assertFalse(self.extractor._should_skip_chunk(text))

    def test_should_skip_short_figure_noise(self) -> None:
        """短小且以图表噪声为主的文本仍应被跳过。"""
        text = "Figure 1 Figure 2 Figure 3 Table 1 Table 2"
        self.assertTrue(self.extractor._should_skip_chunk(text))


if __name__ == "__main__":
    unittest.main()
