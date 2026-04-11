"""社区摘要提示词测试。"""

from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import types
import unittest


class CommunitySummaryPromptTest(unittest.TestCase):
    """验证社区摘要提示词不会被误解析为模板变量。"""

    @classmethod
    def setUpClass(cls) -> None:
        """按文件路径加载提示词模块，避免引入全量工程依赖。"""
        module_path = (
            Path(__file__).resolve().parent.parent
            / "graphrag_agent"
            / "config"
            / "prompts"
            / "graph_prompts.py"
        )
        spec = importlib.util.spec_from_file_location(
            "test_graph_prompts_module",
            module_path,
        )
        assert spec is not None
        assert spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        cls.prompt_module = module

    def test_prompt_renders_without_topic_placeholder_error(self) -> None:
        """花括号中的 JSON 示例应被当作字面量，而不是模板变量。"""
        fake_langchain_prompts = types.ModuleType("langchain.prompts")

        class _FakeChatPromptTemplate:
            """最小替身，复用 Python format 检查模板变量。"""

            def __init__(self, messages):
                self._messages = messages

            @classmethod
            def from_messages(cls, messages):
                return cls(messages)

            def format_messages(self, **kwargs):
                return [content.format(**kwargs) for _role, content in self._messages]

        fake_langchain_prompts.ChatPromptTemplate = _FakeChatPromptTemplate
        original_module = sys.modules.get("langchain.prompts")
        try:
            sys.modules["langchain.prompts"] = fake_langchain_prompts
            from langchain.prompts import ChatPromptTemplate

            prompt = ChatPromptTemplate.from_messages(
                [
                    ("system", self.prompt_module.COMMUNITY_SUMMARY_PROMPT),
                    ("human", "{community_info}"),
                ]
            )
            rendered = prompt.format_messages(community_info="测试社区")
        finally:
            if original_module is None:
                sys.modules.pop("langchain.prompts", None)
            else:
                sys.modules["langchain.prompts"] = original_module

        self.assertEqual(len(rendered), 2)
        self.assertIn('"topic"', rendered[0])
        self.assertIn("测试社区", rendered[1])


if __name__ == "__main__":
    unittest.main()
