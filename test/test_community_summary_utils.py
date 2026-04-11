"""社区主题摘要解析测试。"""

from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest


def _load_summary_utils_module():
    """按文件路径加载社区摘要工具模块。"""
    module_path = (
        Path(__file__).resolve().parent.parent
        / "graphrag_agent"
        / "community"
        / "summary"
        / "utils.py"
    )
    spec = importlib.util.spec_from_file_location(
        "test_community_summary_utils_module",
        module_path,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class CommunitySummaryUtilsTest(unittest.TestCase):
    """验证社区主题摘要解析逻辑。"""

    @classmethod
    def setUpClass(cls) -> None:
        """预加载待测模块。"""
        cls.module = _load_summary_utils_module()

    def test_parse_community_summary_payload_reads_json_topic_and_summary(self) -> None:
        """JSON 输出应被解析为结构化主题与摘要。"""
        result = self.module.parse_community_summary_payload(
            '{"topic":"泵站控制回路","summary":"该社区围绕泵站、回路与调节逻辑展开。"}'
        )

        self.assertEqual(result["topic"], "泵站控制回路")
        self.assertEqual(result["summary"], "该社区围绕泵站、回路与调节逻辑展开。")

    def test_parse_community_summary_payload_falls_back_for_plain_text(self) -> None:
        """非结构化文本也应回退生成可用主题。"""
        result = self.module.parse_community_summary_payload(
            "该社区主要讨论泵站、阀门与控制回路之间的联动关系。",
            fallback_text="泵站 阀门 控制回路",
        )

        self.assertTrue(result["topic"])
        self.assertIn("泵站", result["summary"])


if __name__ == "__main__":
    unittest.main()
