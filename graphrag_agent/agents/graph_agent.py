from typing import Any, AsyncGenerator, Dict, List

import json
import re

from langchain_core.messages import AIMessage
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
from graphrag_agent.search.tool.global_search_tool import GlobalSearchTool
from graphrag_agent.search.tool.local_search_tool import LocalSearchTool


class GraphAgent(BaseAgent):
    """使用图结构检索的 Agent 实现。"""

    def __init__(self):
        # 初始化本地和全局搜索工具。
        self.local_tool = LocalSearchTool()
        self.global_tool = GlobalSearchTool()

        # 设置缓存目录。
        self.cache_dir = "./cache/graph_agent"

        # 调用父类构造函数。
        super().__init__(cache_dir=self.cache_dir)

    def _setup_tools(self) -> List:
        """设置工具列表。"""
        return [
            self.local_tool.get_tool(),
            self.global_tool.get_tool(),
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
