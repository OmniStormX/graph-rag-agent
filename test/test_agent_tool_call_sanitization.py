"""验证 Agent 对历史工具调用消息的兼容性清洗。"""

from __future__ import annotations

import json
import unittest

from langchain_core.messages import AIMessage, HumanMessage

from graphrag_agent.agents.base import BaseAgent


class _MinimalAgent(BaseAgent):
    """仅用于测试消息清洗逻辑的最小 Agent。"""

    def __init__(self) -> None:
        """测试中跳过真实模型初始化。"""

    def _setup_tools(self):
        """测试桩。"""
        return []

    def _add_retrieval_edges(self, workflow):
        """测试桩。"""

    def _extract_keywords(self, query: str):
        """测试桩。"""
        return {"low_level": [], "high_level": []}

    def _generate_node(self, state):
        """测试桩。"""
        return {"messages": []}


class AgentToolCallSanitizationTest(unittest.TestCase):
    """覆盖历史 tool_call 参数格式兼容逻辑。"""

    def setUp(self) -> None:
        """构造不触发真实依赖初始化的 Agent 实例。"""
        self.agent = _MinimalAgent()

    def test_prepare_messages_serializes_parsed_tool_calls(self) -> None:
        """AIMessage.tool_calls 中的 dict 参数应转成 JSON 字符串。"""
        message = AIMessage(
            content="",
            tool_calls=[
                {
                    "id": "call_1",
                    "name": "fluid_property_calc",
                    "args": {
                        "fluid": "Water",
                        "inputs": {"T": 300, "P": 101.325},
                        "outputs": ["H", "S"],
                    },
                    "type": "tool_call",
                }
            ],
        )

        prepared = self.agent._prepare_messages_for_model([HumanMessage(content="test"), message])

        self.assertEqual(len(prepared), 2)
        self.assertEqual(prepared[0].content, "test")
        sanitized_calls = prepared[1].additional_kwargs["tool_calls"]
        self.assertEqual(sanitized_calls[0]["function"]["name"], "fluid_property_calc")
        self.assertIsInstance(sanitized_calls[0]["function"]["arguments"], str)
        self.assertEqual(
            json.loads(sanitized_calls[0]["function"]["arguments"]),
            {
                "fluid": "Water",
                "inputs": {"T": 300, "P": 101.325},
                "outputs": ["H", "S"],
            },
        )

    def test_prepare_messages_serializes_raw_openai_tool_calls(self) -> None:
        """additional_kwargs.tool_calls 中的 arguments 也应被规范化。"""
        message = AIMessage(
            content="",
            additional_kwargs={
                "tool_calls": [
                    {
                        "id": "call_2",
                        "type": "function",
                        "function": {
                            "name": "fluid_property_calc",
                            "arguments": {
                                "fluid": "Air",
                                "inputs": {"T": 300, "P": 101.325},
                                "outputs": ["D"],
                            },
                        },
                    }
                ]
            },
        )

        prepared = self.agent._prepare_messages_for_model([message])
        sanitized_calls = prepared[0].additional_kwargs["tool_calls"]

        self.assertIsInstance(sanitized_calls[0]["function"]["arguments"], str)
        self.assertEqual(
            json.loads(sanitized_calls[0]["function"]["arguments"]),
            {
                "fluid": "Air",
                "inputs": {"T": 300, "P": 101.325},
                "outputs": ["D"],
            },
        )

    def test_negative_empty_answers_are_not_cacheable(self) -> None:
        """无证据兜底回答不应写入缓存，避免构建后继续命中旧答案。"""
        self.assertTrue(
            self.agent._is_negative_or_empty_response(
                "当前未提供任何分析报告，因此无法确定具体的分析对象。"
            )
        )
        self.assertFalse(
            self.agent._should_cache_response(
                "当前知识库没有检索到可支持回答的文档证据。"
            )
        )
        self.assertTrue(
            self.agent._should_cache_response(
                "压强属于强度参数，因为它不随系统质量或体积整体缩放而线性相加。"
            )
        )

    def test_normalize_keywords_flattens_nested_model_output(self) -> None:
        """模型返回嵌套关键词时应扁平化为字符串，避免 lower 调用失败。"""
        self.assertEqual(
            self.agent._normalize_keywords(
                {
                    "low_level": [["广延参数", "强度参数"], "状态参数"],
                    "high_level": ("热力学", None),
                }
            ),
            ["广延参数", "强度参数", "状态参数", "热力学"],
        )


if __name__ == "__main__":
    unittest.main()
