from typing import Any, AsyncGenerator, Dict, List

from langchain_core.messages import AIMessage
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate

from graphrag_agent.agents.base import BaseAgent
from graphrag_agent.config.prompts import HYBRID_AGENT_GENERATE_PROMPT, LC_SYSTEM_PROMPT
from graphrag_agent.config.settings import response_type
from graphrag_agent.search.tool_registry import get_langchain_extra_tools
from graphrag_agent.search.tool.hybrid_tool import HybridSearchTool


class HybridAgent(BaseAgent):
    """使用混合搜索的 Agent 实现。"""

    def __init__(self):
        self.search_tool = HybridSearchTool()
        self.cache_dir = "./cache/hybrid_agent"
        super().__init__(cache_dir=self.cache_dir)

    def _setup_tools(self) -> List:
        """设置工具。"""
        return [
            self.search_tool.get_tool(),
            self.search_tool.get_global_tool(),
            *get_langchain_extra_tools(),
        ]

    def _add_retrieval_edges(self, workflow):
        """添加从检索到生成的边。"""
        workflow.add_edge("retrieve", "generate")

    def _extract_keywords(self, query: str) -> Dict[str, List[str]]:
        """提取查询关键词。"""
        cached_keywords = self._keyword_cache.get(query)
        if cached_keywords:
            return cached_keywords

        try:
            keywords = self.search_tool.extract_keywords(query)
            if not isinstance(keywords, dict):
                keywords = {}
            keywords["low_level"] = self._normalize_keywords(
                keywords.get("low_level", [])
            )
            keywords["high_level"] = self._normalize_keywords(
                keywords.get("high_level", [])
            )
            self._keyword_cache[query] = keywords
            return keywords
        except Exception as e:
            print(f"关键词提取失败: {e}")
            return {"low_level": [], "high_level": []}

    def _generate_node(self, state):
        """生成回答节点逻辑。"""
        messages = state["messages"]

        try:
            question = messages[-3].content if len(messages) >= 3 else "未找到问题"
        except Exception:
            question = "无法获取问题"

        try:
            docs = messages[-1].content if messages[-1] else "未找到相关信息"
        except Exception:
            docs = "无法获取检索结果"

        if self._is_negative_or_empty_response(docs):
            self._log_execution(
                "generate",
                {"question": question, "docs_length": len(docs), "empty_retrieval": True},
                docs,
            )
            return {"messages": [AIMessage(content=docs)]}

        global_result = self.global_cache_manager.get(question)
        if self._should_cache_response(global_result):
            self._log_execution(
                "generate",
                {"question": question, "docs_length": len(docs)},
                "全局缓存命中",
            )
            return {"messages": [AIMessage(content=global_result)]}

        thread_id = state.get("configurable", {}).get("thread_id", "default")
        cached_result = self.cache_manager.get(question, thread_id=thread_id)
        if self._should_cache_response(cached_result):
            self._log_execution(
                "generate",
                {"question": question, "docs_length": len(docs)},
                "会话缓存命中",
            )
            self.global_cache_manager.set(question, cached_result)
            return {"messages": [AIMessage(content=cached_result)]}

        prompt = ChatPromptTemplate.from_messages([
            ("system", LC_SYSTEM_PROMPT),
            ("human", HYBRID_AGENT_GENERATE_PROMPT),
        ])
        rag_chain = prompt | self.llm | StrOutputParser()

        try:
            response = rag_chain.invoke({
                "context": docs,
                "question": question,
                "response_type": response_type,
            })
            if response and len(response) > 10 and self._should_cache_response(response):
                self.cache_manager.set(question, response, thread_id=thread_id)
                self.global_cache_manager.set(question, response)

            self._log_execution(
                "generate",
                {"question": question, "docs_length": len(docs)},
                response,
            )
            return {"messages": [AIMessage(content=response)]}
        except Exception as e:
            error_msg = f"生成回答时出错: {str(e)}"
            self._log_execution(
                "generate_error",
                {"question": question, "docs_length": len(docs)},
                error_msg,
            )
            return {"messages": [AIMessage(content=f"抱歉，我无法回答这个问题。技术原因: {str(e)}")]}

    async def _generate_node_stream(self, state: Dict[str, Any]) -> AsyncGenerator[str, None]:
        """基于流式模型生成回答。"""
        messages = state["messages"]

        try:
            question = messages[-3].content if len(messages) >= 3 else "未找到问题"
        except Exception:
            question = "无法获取问题"

        try:
            docs = messages[-1].content if messages[-1] else "未找到相关信息"
        except Exception:
            docs = "无法获取检索结果"

        if self._is_negative_or_empty_response(docs):
            yield docs
            self._log_execution(
                "generate",
                {"question": question, "docs_length": len(docs), "empty_retrieval": True},
                docs,
            )
            return

        thread_id = state.get("configurable", {}).get("thread_id", "default")
        prompt = ChatPromptTemplate.from_messages([
            ("system", LC_SYSTEM_PROMPT),
            ("human", HYBRID_AGENT_GENERATE_PROMPT),
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
        if self._should_cache_response(response):
            self.cache_manager.set(question, response, thread_id=thread_id)
            self.global_cache_manager.set(question, response)
        self._log_execution(
            "generate",
            {"question": question, "docs_length": len(docs)},
            response,
        )

    async def _stream_process(self, inputs, config):
        """复用基类统一的流式工作流。"""
        async for event in super()._stream_process(inputs, config):
            yield event

    def close(self):
        """关闭资源。"""
        super().close()
        if self.search_tool:
            self.search_tool.close()
