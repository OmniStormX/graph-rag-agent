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


if __name__ == "__main__":
    unittest.main()
