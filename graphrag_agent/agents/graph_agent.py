from typing import Any, AsyncGenerator, Dict, List

import json
import re

from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langgraph.graph import END

from graphrag_agent.agents.base import BaseAgent
from graphrag_agent.config.prompts import (
    GRAPH_AGENT_GENERATE_PROMPT,
    GRAPH_AGENT_KEYWORD_PROMPT,
    GRAPH_AGENT_REDUCE_PROMPT,
    LC_SYSTEM_PROMPT,
    REDUCE_SYSTEM_PROMPT,
)
from graphrag_agent.config.settings import response_type
from graphrag_agent.search.tool_registry import get_langchain_extra_tools
from graphrag_agent.search.tool.global_search_tool import GlobalSearchTool
from graphrag_agent.search.tool.fluid_property_tool import FluidPropertyTool
from graphrag_agent.search.tool.local_search_tool import LocalSearchTool


class GraphAgent(BaseAgent):
    """使用图结构检索的 Agent 实现。"""

    def __init__(self):
        # 初始化本地和全局搜索工具。
        self.local_tool = LocalSearchTool()
        self.global_tool = GlobalSearchTool()
        self.fluid_property_tool = FluidPropertyTool()

        # 设置缓存目录。
        self.cache_dir = "./cache/graph_agent"

        # 调用父类构造函数。
        super().__init__(cache_dir=self.cache_dir)

    def _setup_tools(self) -> List:
        """设置工具列表。"""
        return [
            self.local_tool.get_tool(),
            self.global_tool.get_tool(),
            *get_langchain_extra_tools(),
        ]

    def _add_retrieval_edges(self, workflow):
        """添加从检索到生成的边。"""
        workflow.add_node("reduce", self._reduce_node)
        workflow.add_conditional_edges(
            "retrieve",
            self._grade_documents,
            {
                "generate": "generate",
                "reduce": "reduce",
            },
        )
        workflow.add_edge("reduce", END)

    def _extract_keywords(self, query: str) -> Dict[str, List[str]]:
        """提取查询关键词。"""
        if not query or not isinstance(query, str):
            return {"low_level": [], "high_level": []}

        cached_keywords = self._keyword_cache.get(query)
        if cached_keywords:
            return cached_keywords

        try:
            prompt = GRAPH_AGENT_KEYWORD_PROMPT.format(query=query)
            result = self.llm.invoke(prompt)
            content = result.content if hasattr(result, "content") else result
            json_match = re.search(r"({.*})", content, re.DOTALL)
            if json_match:
                keywords = json.loads(json_match.group(1))
                if not isinstance(keywords, dict):
                    keywords = {}
                keywords.setdefault("low_level", [])
                keywords.setdefault("high_level", [])
                self._keyword_cache[query] = keywords
                return keywords
        except Exception as e:
            print(f"关键词提取失败: {e}")

        return {"low_level": [], "high_level": []}

    def _resolve_fluid_request(self, query: str) -> Dict[str, Any] | None:
        """识别典型物性计算问句，并解析为结构化请求。"""
        if not isinstance(query, str) or not query.strip():
            return None

        # 复用工具内置的自然语言解析逻辑，确保路由条件与实际可执行条件一致。
        try:
            normalized = self.fluid_property_tool._normalize_request({"query": query})  # noqa: SLF001
        except Exception:
            return None

        # 仅当能够解析出完整请求时才强制走工具，避免误路由普通知识问答。
        if not normalized.get("fluid") or not normalized.get("inputs") or not normalized.get("outputs"):
            return None
        return normalized

    @staticmethod
    def _classify_state_pair(inputs: Dict[str, Any], metadata: Dict[str, Any] | None = None) -> str:
        """根据两个已知状态量给出状态量组合类型说明。"""
        keys = list(inputs.keys())
        if len(keys) != 2:
            return "两独立状态量组合"
        if metadata and metadata.get("near_saturation") and set(keys) == {"T", "P"}:
            return f"{keys[0]}-{keys[1]} 状态点接近饱和线"
        return f"{keys[0]}-{keys[1]} 两独立状态量组合"

    def _format_fluid_answer(
        self,
        query: str,
        normalized: Dict[str, Any],
        result: Dict[str, Any],
    ) -> str:
        """将物性工具结果格式化为用户可读回答。"""
        if not result.get("success"):
            error_message = result.get("error") or "未知错误"
            return f"流体物性计算失败：{error_message}"

        inputs = normalized.get("inputs", {})
        outputs = result.get("results", {})
        metadata = result.get("metadata", {}) or {}
        state_pair = self._classify_state_pair(inputs, metadata)

        lines = [
            f"{normalized.get('fluid', '该工质')} 在给定状态下的计算结果如下：",
        ]
        if "T" in inputs:
            lines.append(f"- 温度 T = {inputs['T']} K")
        if "P" in inputs:
            lines.append(f"- 压强 P = {inputs['P']} kPa")
        if "H" in inputs:
            lines.append(f"- 比焓 H = {inputs['H']} kJ/kg")
        if "S" in inputs:
            lines.append(f"- 比熵 S = {inputs['S']} kJ/(kg*K)")
        if "D" in inputs:
            lines.append(f"- 密度 D = {inputs['D']} kg/m^3")
        if "Q" in inputs:
            lines.append(f"- 干度 Q = {inputs['Q']}")

        for key, value in outputs.items():
            if key == "T":
                lines.append(f"- 计算得到温度 T = {value:.6f} K")
            elif key == "P":
                lines.append(f"- 计算得到压强 P = {value:.6f} kPa")
            elif key == "H":
                lines.append(f"- 计算得到比焓 H = {value:.6f} kJ/kg")
            elif key == "S":
                lines.append(f"- 计算得到比熵 S = {value:.6f} kJ/(kg*K)")
            elif key == "D":
                lines.append(f"- 计算得到密度 D = {value:.6f} kg/m^3")
            elif key == "Q":
                if value is None:
                    lines.append("- 当前状态位于单相区，干度 Q 无定义")
                else:
                    lines.append(f"- 计算得到干度 Q = {value:.6f}")

        lines.append(f"这属于 {state_pair} 的物性计算。")
        for note in metadata.get("notes", []):
            lines.append(f"- 说明：{note}")
        return "\n".join(lines)

    def _try_direct_fluid_answer(self, query: str) -> str | None:
        """对物性计算请求直接调用工具，绕开模型函数调用兼容问题。"""
        normalized = self._resolve_fluid_request(query)
        if normalized is None:
            return None

        result = self.fluid_property_tool.calculate(normalized)
        answer = self._format_fluid_answer(query, normalized, result)
        self._log_execution(
            "direct_fluid_property_calc",
            {"query": query, "normalized": normalized},
            result,
        )
        return answer

    def _build_keyword_cache_params(
        self,
        query: str,
        thread_id: str = "default",
    ) -> Dict[str, List[str]]:
        """
        为 GraphAgent 构建缓存检查参数。

        说明：
            GraphAgent 在缓存检查阶段不再调用 LLM 提取关键词，
            避免语义缓存 miss 前先支付高昂的关键词提取成本。
            关键词仍然会在正常问答流程中通过 `_extract_keywords`
            使用，用于检索与回答生成阶段。
        """
        return {
            "thread_id": thread_id,
            "low_level_keywords": [],
            "high_level_keywords": [],
        }

    def _grade_documents(self, state) -> str:
        """评估文档相关性，返回 generate 或 reduce。"""
        messages = state["messages"]
        retrieve_message = messages[-2]

        tool_calls = []
        if hasattr(retrieve_message, "tool_calls") and retrieve_message.tool_calls:
            tool_calls = retrieve_message.tool_calls
        elif getattr(retrieve_message, "additional_kwargs", None):
            tool_calls = retrieve_message.additional_kwargs.get("tool_calls", [])

        if tool_calls:
            first_call = tool_calls[0]
            tool_name = first_call.get("name", "")
            function_payload = first_call.get("function")
            if isinstance(function_payload, dict):
                tool_name = function_payload.get("name", tool_name)
            if tool_name == "global_retriever":
                self._log_execution("grade_documents", messages, "reduce")
                return "reduce"

        try:
            question = messages[-3].content
            docs = messages[-1].content
        except Exception as e:
            print(f"文档评分出错: {e}")
            return "generate"

        if not docs or len(docs) < 100:
            print("文档内容不足，尝试使用本地搜索")
            try:
                local_result = self.local_tool.search(question)
                if local_result and len(local_result) > 100:
                    messages[-1].content = local_result
                    docs = local_result
            except Exception as e:
                print(f"本地搜索失败: {e}")

        keywords: List[str] = []
        if hasattr(messages[-3], "additional_kwargs") and messages[-3].additional_kwargs:
            kw_data = messages[-3].additional_kwargs.get("keywords", {})
            if isinstance(kw_data, dict):
                keywords = kw_data.get("low_level", []) + kw_data.get("high_level", [])

        if not keywords:
            keywords = [word for word in question.lower().split() if len(word) > 2]

        docs_text = docs.lower() if docs else ""
        matches = sum(1 for keyword in keywords if keyword.lower() in docs_text)
        match_rate = matches / len(keywords) if keywords else 0

        self._log_execution(
            "grade_documents",
            {
                "question": question,
                "keywords": keywords,
                "match_rate": match_rate,
                "docs_length": len(docs_text),
            },
            f"匹配率: {match_rate}",
        )

        return "generate"

    def _generate_node(self, state):
        """生成回答节点逻辑。"""
        messages = state["messages"]
        question = messages[-3].content
        docs = messages[-1].content

        global_result = self.global_cache_manager.get(question)
        if self._is_valid_text_response(global_result):
            self._log_execution(
                "generate",
                {"question": question, "docs_length": len(docs)},
                "全局缓存命中",
            )
            return {"messages": [AIMessage(content=global_result)]}

        thread_id = state.get("configurable", {}).get("thread_id", "default")
        cached_result = self.cache_manager.get(question, thread_id=thread_id)
        if self._is_valid_text_response(cached_result):
            self._log_execution(
                "generate",
                {"question": question, "docs_length": len(docs)},
                "会话缓存命中",
            )
            self.global_cache_manager.set(question, cached_result)
            return {"messages": [AIMessage(content=cached_result)]}

        prompt = ChatPromptTemplate.from_messages([
            ("system", LC_SYSTEM_PROMPT),
            ("human", GRAPH_AGENT_GENERATE_PROMPT),
        ])
        rag_chain = prompt | self.llm | StrOutputParser()
        response = rag_chain.invoke({
            "context": docs,
            "question": question,
            "response_type": response_type,
        })

        if response and len(response) > 10:
            self.cache_manager.set(question, response, thread_id=thread_id)
            self.global_cache_manager.set(question, response)

        self._log_execution(
            "generate",
            {"question": question, "docs_length": len(docs)},
            response,
        )
        return {"messages": [AIMessage(content=response)]}

    def _agent_node(self, state):
        """Agent 节点逻辑。"""
        return super()._agent_node(state)

    def ask(self, query: str, thread_id: str = "default", recursion_limit=None):
        """优先处理可直接执行的物性计算请求。"""
        direct_answer = self._try_direct_fluid_answer(query.strip())
        if direct_answer:
            if len(direct_answer) > 10:
                self.cache_manager.set(query.strip(), direct_answer, thread_id=thread_id)
                self.global_cache_manager.set(query.strip(), direct_answer)
            return direct_answer
        return super().ask(query, thread_id=thread_id, recursion_limit=recursion_limit)

    async def ask_stream(self, query: str, thread_id: str = "default", recursion_limit=None) -> AsyncGenerator[Any, None]:
        """流式模式下优先处理可直接执行的物性计算请求。"""
        safe_query = query.strip()
        direct_answer = self._try_direct_fluid_answer(safe_query)
        if direct_answer:
            yield self._make_stage_event("fluid_property_calc", "正在进行流体物性计算", source="direct_tool")
            yield direct_answer
            if len(direct_answer) > 10:
                self.cache_manager.set(safe_query, direct_answer, thread_id=thread_id)
                self.global_cache_manager.set(safe_query, direct_answer)
            return
        async for chunk in super().ask_stream(query, thread_id=thread_id, recursion_limit=recursion_limit):
            yield chunk

    def _reduce_node(self, state):
        """处理全局搜索的 reduce 节点逻辑。"""
        messages = state["messages"]
        question = messages[-3].content
        docs = messages[-1].content

        cache_key = f"reduce:{question}"
        cached_result = self.cache_manager.get(cache_key)
        if self._is_valid_text_response(cached_result):
            self._log_execution(
                "reduce",
                {"question": question, "docs_length": len(docs)},
                cached_result,
            )
            return {"messages": [AIMessage(content=cached_result)]}

        reduce_prompt = ChatPromptTemplate.from_messages([
            ("system", REDUCE_SYSTEM_PROMPT),
            ("human", GRAPH_AGENT_REDUCE_PROMPT),
        ])
        reduce_chain = reduce_prompt | self.llm | StrOutputParser()
        response = reduce_chain.invoke({
            "report_data": docs,
            "question": question,
            "response_type": response_type,
        })

        self.cache_manager.set(cache_key, response)
        self._log_execution(
            "reduce",
            {"question": question, "docs_length": len(docs)},
            response,
        )
        return {"messages": [AIMessage(content=response)]}

    async def _generate_node_stream(self, state: Dict[str, Any]) -> AsyncGenerator[str, None]:
        """基于流式模型生成最终回答。"""
        messages = state["messages"]

        try:
            question = messages[-3].content if len(messages) >= 3 else "未找到问题"
            docs = messages[-1].content if messages[-1] else "未找到相关信息"
        except Exception as e:
            yield f"获取问题或文档时出错: {str(e)}"
            return

        thread_id = state.get("configurable", {}).get("thread_id", "default")
        prompt = ChatPromptTemplate.from_messages([
            ("system", LC_SYSTEM_PROMPT),
            ("human", GRAPH_AGENT_GENERATE_PROMPT),
        ])
        rag_chain = prompt | self.stream_llm | StrOutputParser()
        response_chunks: List[str] = []

        async for chunk in rag_chain.astream({
            "context": docs,
            "question": question,
            "response_type": response_type,
        }):
            text = str(chunk)
            if not text:
                continue
            response_chunks.append(text)
            yield text

        response = "".join(response_chunks).strip()
        if response:
            self.cache_manager.set(question, response, thread_id=thread_id)
            self.global_cache_manager.set(question, response)
            self._log_execution(
                "generate",
                {"question": question, "docs_length": len(docs)},
                response,
            )

    async def _reduce_node_stream(self, state: Dict[str, Any]) -> AsyncGenerator[str, None]:
        """基于流式模型归纳全局搜索结果。"""
        messages = state["messages"]
        question = messages[-3].content
        docs = messages[-1].content

        cache_key = f"reduce:{question}"
        cached_result = self.cache_manager.get(cache_key)
        if self._is_valid_text_response(cached_result):
            async for chunk in self._replay_text_stream(cached_result):
                yield chunk
            return

        reduce_prompt = ChatPromptTemplate.from_messages([
            ("system", REDUCE_SYSTEM_PROMPT),
            ("human", GRAPH_AGENT_REDUCE_PROMPT),
        ])
        reduce_chain = reduce_prompt | self.stream_llm | StrOutputParser()
        response_chunks: List[str] = []

        async for chunk in reduce_chain.astream({
            "report_data": docs,
            "question": question,
            "response_type": response_type,
        }):
            text = str(chunk)
            if not text:
                continue
            response_chunks.append(text)
            yield text

        response = "".join(response_chunks).strip()
        if response:
            self.cache_manager.set(cache_key, response)
            self._log_execution(
                "reduce",
                {"question": question, "docs_length": len(docs)},
                response,
            )

    def _route_stream_after_retrieval(self, state: Dict[str, Any]) -> str:
        """流式路径与非流式路径保持相同的检索后路由。"""
        return self._grade_documents(state)

    def close(self):
        """关闭资源。"""
        super().close()
        if self.local_tool:
            self.local_tool.close()
        if self.global_tool:
            self.global_tool.close()
