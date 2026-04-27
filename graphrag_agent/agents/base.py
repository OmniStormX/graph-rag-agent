from typing import Annotated, Sequence, TypedDict, List, Dict, Any, AsyncGenerator, Optional
from abc import ABC, abstractmethod
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from langgraph.graph import END, StateGraph, START
from langgraph.prebuilt import ToolNode, tools_condition
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph.message import add_messages
import pprint
import time
import asyncio
import json
import re
from copy import deepcopy

from graphrag_agent.models.get_models import get_llm_model, get_stream_llm_model, get_embeddings_model
from graphrag_agent.runtime_logging import emit_runtime_log, shorten_text
from graphrag_agent.cache_manager.manager import (
    CacheManager, 
    ContextAwareCacheKeyStrategy, 
    HybridCacheBackend
)
from graphrag_agent.cache_manager.strategies.global_strategy import GlobalCacheKeyStrategy
from graphrag_agent.config.settings import AGENT_SETTINGS

class BaseAgent(ABC):
    """Agent 基类，定义通用功能和接口"""
    
    def __init__(self, cache_dir="./cache", memory_only=False):
        """
        初始化搜索工具
        
        参数:
            cache_dir: 缓存目录，用于存储搜索结果
        """
        # 初始化普通 LLM 和流式 LLM
        self.llm = get_llm_model()
        self.stream_llm = get_stream_llm_model()
        self.embeddings = get_embeddings_model()
        self.default_recursion_limit = AGENT_SETTINGS["default_recursion_limit"]
        self.stream_flush_threshold = AGENT_SETTINGS["stream_flush_threshold"]
        self.deep_stream_flush_threshold = AGENT_SETTINGS["deep_stream_flush_threshold"]
        self.fusion_stream_flush_threshold = AGENT_SETTINGS["fusion_stream_flush_threshold"]
        self.chunk_size = AGENT_SETTINGS["chunk_size"]
        
        self.memory = MemorySaver()
        self.execution_log = []
    
        # 常规上下文感知缓存（会话内）
        self.cache_manager = CacheManager(
            key_strategy=ContextAwareCacheKeyStrategy(),
            storage_backend=HybridCacheBackend(
                cache_dir=cache_dir,
                memory_max_size=200,
                disk_max_size=2000
            ) if not memory_only else None,
            cache_dir=cache_dir,
            memory_only=memory_only
        )
        
        # 全局缓存（跨会话）
        self.global_cache_manager = CacheManager(
            key_strategy=GlobalCacheKeyStrategy(),
            storage_backend=HybridCacheBackend(
                cache_dir=f"{cache_dir}/global",
                memory_max_size=500,
                disk_max_size=5000
            ) if not memory_only else None,
            cache_dir=f"{cache_dir}/global",
            memory_only=memory_only
        )
        
        self.performance_metrics = {}  # 性能指标收集
        # 关键词缓存与回答缓存隔离，避免结构化字典误入回答缓存链路。
        self._keyword_cache: Dict[str, Dict[str, List[str]]] = {}
        self._request_context: Dict[str, Any] = {}
        
        # 初始化工具
        self.tools = self._setup_tools()
        
        # 设置工作流图
        self._setup_graph()

    def _is_valid_text_response(self, value: Any) -> bool:
        """判断对象是否为可直接作为最终回答的文本。"""
        return isinstance(value, str) and bool(value.strip())

    def _is_negative_or_empty_response(self, value: Any) -> bool:
        """判断回答是否属于无证据兜底结果，避免污染可复用缓存。"""
        if not isinstance(value, str):
            return False

        normalized = value.strip()
        if normalized in {"不知道", "未能生成回答"}:
            return True

        negative_markers = (
            "当前未提供任何分析报告",
            "无法确定具体的分析对象",
            "无法阐述任何作用机理",
            "无法识别关键变量",
            "无法得出任何工程结论",
            "没有找到相关的低级内容",
            "没有找到相关的高级内容",
            "当前知识库没有检索到可支持回答的文档证据",
            "没有找到与",
            "未找到相关信息",
            "在知识库中未找到相关信息",
            "搜索过程中出错",
            "查询实体信息时出错",
            "查询社区信息时出错",
        )
        return any(marker in normalized for marker in negative_markers)

    def _should_cache_response(self, value: Any) -> bool:
        """仅缓存有实质内容的正向回答。"""
        return self._is_valid_text_response(value) and not self._is_negative_or_empty_response(value)

    def _normalize_keywords(self, value: Any) -> List[str]:
        """将模型返回的关键词统一整理为字符串列表。"""
        if value is None:
            return []
        if isinstance(value, str):
            stripped = value.strip()
            return [stripped] if stripped else []
        if isinstance(value, dict):
            normalized: List[str] = []
            for item in value.values():
                normalized.extend(self._normalize_keywords(item))
            return normalized
        if isinstance(value, (list, tuple, set)):
            normalized = []
            for item in value:
                normalized.extend(self._normalize_keywords(item))
            return normalized

        stripped = str(value).strip()
        return [stripped] if stripped else []
    
    @abstractmethod
    def _setup_tools(self) -> List:
        """设置工具，子类必须实现"""
        pass
    
    def _setup_graph(self):
        """设置工作流图 - 基础结构，子类可以通过_add_retrieval_edges自定义"""
        # 定义状态类型
        class AgentState(TypedDict):
            messages: Annotated[Sequence[BaseMessage], add_messages]

        # 创建工作流图
        workflow = StateGraph(AgentState)
        
        # 添加节点 - 节点与原始代码保持一致
        workflow.add_node("agent", self._agent_node)
        workflow.add_node("retrieve", ToolNode(self.tools))
        workflow.add_node("generate", self._generate_node)
        
        # 添加从开始到Agent的边
        workflow.add_edge(START, "agent")
        workflow.add_conditional_edges(
            "agent",
            tools_condition,
            {
                "tools": "retrieve",
                END: END,
            },
        )
        
        # 添加从检索到生成的边 - 这个逻辑由子类实现
        self._add_retrieval_edges(workflow)
        
        # 从生成到结束
        workflow.add_edge("generate", END)
        
        # 编译图
        self.graph = workflow.compile(checkpointer=self.memory)

    def _make_stream_event(self, status: str, **fields: Any) -> Dict[str, Any]:
        """构造统一的流式事件负载。"""
        return {"status": status, **fields}

    def _make_stage_event(
        self,
        stage: str,
        content: str,
        **fields: Any,
    ) -> Dict[str, Any]:
        """构造阶段事件，便于前后端统一处理。"""
        return self._make_stream_event("stage", stage=stage, content=content, **fields)

    def _split_text_for_stream(self, text: str) -> List[str]:
        """按自然语言边界切分文本，复用于缓存回放与降级输出。"""
        if not text:
            return []

        parts = re.split(r'([.!?。！？]\s*)', text)
        chunks: List[str] = []
        buffer = ""

        for index, part in enumerate(parts):
            if not part:
                continue
            buffer += part
            if (index % 2 == 1) or len(buffer) >= self.stream_flush_threshold:
                chunks.append(buffer)
                buffer = ""

        if buffer:
            chunks.append(buffer)

        return chunks

    async def _replay_text_stream(
        self,
        text: str,
        *,
        sleep_interval: float = 0.01,
    ) -> AsyncGenerator[str, None]:
        """将已有文本按块回放为流。"""
        for chunk in self._split_text_for_stream(text):
            yield chunk
            await asyncio.sleep(sleep_interval)

    async def _agent_node_async(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """在线程池中执行 agent 节点，避免阻塞事件循环。"""
        return await asyncio.get_event_loop().run_in_executor(None, self._agent_node, state)

    def _extract_tool_calls(self, message: BaseMessage) -> List[Dict[str, Any]]:
        """统一解析 AIMessage 中的工具调用。"""
        tool_calls = []

        if hasattr(message, "tool_calls") and getattr(message, "tool_calls"):
            raw_tool_calls = getattr(message, "tool_calls")
            if isinstance(raw_tool_calls, list):
                for tool_call in raw_tool_calls:
                    if isinstance(tool_call, dict):
                        tool_calls.append(tool_call)

        if tool_calls:
            return tool_calls

        if hasattr(message, "additional_kwargs") and getattr(message, "additional_kwargs"):
            raw_tool_calls = message.additional_kwargs.get("tool_calls", [])
            if isinstance(raw_tool_calls, list):
                for tool_call in raw_tool_calls:
                    if isinstance(tool_call, dict):
                        tool_calls.append(tool_call)

        return tool_calls

    def _normalize_tool_input(self, tool_call: Dict[str, Any]) -> tuple[str, Any, str]:
        """规范化工具调用名称、参数与调用ID。"""
        tool_name = tool_call.get("name", "")
        tool_args: Any = tool_call.get("args", {})
        tool_call_id = tool_call.get("id", "tool_call_0")

        function_payload = tool_call.get("function")
        if isinstance(function_payload, dict):
            tool_name = function_payload.get("name", tool_name)
            tool_args = function_payload.get("arguments", tool_args)

        if isinstance(tool_args, str):
            try:
                tool_args = json.loads(tool_args)
            except json.JSONDecodeError:
                tool_args = {"query": tool_args}

        if not isinstance(tool_args, dict):
            tool_args = {"query": str(tool_args)}

        return tool_name, tool_args, tool_call_id

    def _get_tool_registry(self) -> Dict[str, Any]:
        """构建名称到工具实例的映射。"""
        registry: Dict[str, Any] = {}
        for tool in self.tools:
            tool_name = getattr(tool, "name", None)
            if tool_name:
                registry[tool_name] = tool
            elif callable(tool):
                registry[getattr(tool, "__name__", tool.__class__.__name__)] = tool
        return registry

    async def _invoke_tool_async(self, tool: Any, tool_input: Any) -> Any:
        """在线程池中执行工具调用。"""
        loop = asyncio.get_event_loop()

        def invoke_tool() -> Any:
            normalized_input = tool_input
            if isinstance(tool_input, dict):
                if "query" in tool_input and len(tool_input) == 1:
                    normalized_input = tool_input["query"]
                elif "input" in tool_input and len(tool_input) == 1:
                    normalized_input = tool_input["input"]
            if hasattr(tool, "invoke"):
                return tool.invoke(normalized_input)
            if callable(tool):
                if isinstance(normalized_input, dict):
                    if "query" in normalized_input:
                        return tool(normalized_input["query"])
                    if "input" in normalized_input:
                        return tool(normalized_input["input"])
                return tool(normalized_input)
            raise TypeError(f"不支持的工具类型: {type(tool)}")

        return await loop.run_in_executor(None, invoke_tool)

    def _serialize_tool_call_arguments(self, tool_call: Dict[str, Any]) -> Dict[str, Any]:
        """将工具调用参数规范化为 JSON 字符串，兼容严格网关。"""
        normalized_call = deepcopy(tool_call)

        if "args" in normalized_call and not isinstance(normalized_call.get("args"), str):
            try:
                normalized_call["args"] = json.dumps(
                    normalized_call.get("args", {}),
                    ensure_ascii=False,
                )
            except TypeError:
                normalized_call["args"] = json.dumps(
                    {"value": str(normalized_call.get("args"))},
                    ensure_ascii=False,
                )

        function_payload = normalized_call.get("function")
        if isinstance(function_payload, dict):
            arguments = function_payload.get("arguments")
            if not isinstance(arguments, str):
                try:
                    function_payload["arguments"] = json.dumps(
                        arguments if arguments is not None else {},
                        ensure_ascii=False,
                    )
                except TypeError:
                    function_payload["arguments"] = json.dumps(
                        {"value": str(arguments)},
                        ensure_ascii=False,
                    )

        return normalized_call

    def _prepare_messages_for_model(self, messages: Sequence[BaseMessage]) -> List[BaseMessage]:
        """在模型调用前清洗历史消息，避免 tool_call 参数格式错误。"""
        prepared_messages: List[BaseMessage] = []

        for message in messages:
            if not isinstance(message, AIMessage):
                prepared_messages.append(message)
                continue

            raw_tool_calls = []
            if isinstance(message.additional_kwargs, dict):
                raw_tool_calls = message.additional_kwargs.get("tool_calls", [])

            sanitized_tool_calls: List[Dict[str, Any]] = []
            if isinstance(raw_tool_calls, list) and raw_tool_calls:
                sanitized_tool_calls = [
                    self._serialize_tool_call_arguments(tool_call)
                    for tool_call in raw_tool_calls
                    if isinstance(tool_call, dict)
                ]
            elif getattr(message, "tool_calls", None):
                # LangChain 内存中常把 args 保存为 dict，这里显式转回协议要求的字符串。
                sanitized_tool_calls = [
                    {
                        "id": tool_call.get("id", f"tool_call_{index}"),
                        "type": "function",
                        "function": {
                            "name": tool_call.get("name", ""),
                            "arguments": json.dumps(
                                tool_call.get("args", {}),
                                ensure_ascii=False,
                            ),
                        },
                    }
                    for index, tool_call in enumerate(message.tool_calls)
                    if isinstance(tool_call, dict)
                ]

            if sanitized_tool_calls:
                prepared_messages.append(
                    AIMessage(
                        content=message.content,
                        additional_kwargs={
                            **(message.additional_kwargs or {}),
                            "tool_calls": sanitized_tool_calls,
                        },
                        response_metadata=message.response_metadata,
                        name=message.name,
                        id=message.id,
                        usage_metadata=getattr(message, "usage_metadata", None),
                    )
                )
                continue

            prepared_messages.append(message)

        return prepared_messages

    async def _run_retrieval_step(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """执行统一的工具检索步骤，返回 ToolMessage 列表。"""
        last_message = state["messages"][-1]
        tool_calls = self._extract_tool_calls(last_message)
        if not tool_calls:
            raise ValueError("未找到可执行的工具调用")

        tool_registry = self._get_tool_registry()
        tool_messages: List[ToolMessage] = []

        for tool_call in tool_calls:
            tool_name, tool_args, tool_call_id = self._normalize_tool_input(tool_call)
            tool = tool_registry.get(tool_name)
            if tool is None:
                raise ValueError(f"未注册的工具: {tool_name}")

            tool_result = await self._invoke_tool_async(tool, tool_args)
            tool_messages.append(
                ToolMessage(
                    content=tool_result,
                    tool_call_id=tool_call_id,
                    name=tool_name,
                )
            )

        return {"messages": tool_messages}

    def _route_stream_after_retrieval(self, state: Dict[str, Any]) -> str:
        """决定检索后的流式节点路由，默认直接进入生成。"""
        return "generate"
    
    async def _stream_process(self, inputs: Dict[str, Any], config: Dict[str, Any]) -> AsyncGenerator[Any, None]:
        """
        执行流式处理的默认实现
        
        子类应该覆盖此方法以实现特定的流式处理逻辑
        
        参数:
            inputs: 输入消息
            config: 配置
            
        返回:
            AsyncGenerator[str, None]: 流式响应生成器
        """
        messages = list(inputs.get("messages", []))
        state = {
            "messages": messages,
            "configurable": config.get("configurable", {}),
        }

        yield self._make_stage_event("agent", "正在分析问题")
        agent_output = await self._agent_node_async(state)
        state["messages"] = state["messages"] + agent_output.get("messages", [])

        tool_decision = tools_condition({"messages": state["messages"]})
        if tool_decision != "tools":
            final_message = state["messages"][-1]
            content = final_message.content if hasattr(final_message, "content") else str(final_message)
            async for chunk in self._replay_text_stream(content, sleep_interval=0):
                yield chunk
            return

        yield self._make_stage_event("retrieve", "正在检索相关信息")
        retrieve_output = await self._run_retrieval_step(state)
        state["messages"] = state["messages"] + retrieve_output.get("messages", [])

        next_node = self._route_stream_after_retrieval(state)
        if next_node == "reduce":
            yield self._make_stage_event("reduce", "正在归纳检索结果")
            async for chunk in self._reduce_node_stream(state):
                yield chunk
            return

        yield self._make_stage_event("generate", "正在生成回答")
        async for chunk in self._generate_node_stream(state):
            yield chunk

    
    @abstractmethod
    def _add_retrieval_edges(self, workflow):
        """添加从检索到生成的边，子类必须实现"""
        pass
    
    def _log_execution(self, node_name: str, input_data: Any, output_data: Any):
        """记录节点执行"""
        self.execution_log.append({
            "node": node_name,
            "timestamp": time.time(),
            "input": input_data,
            "output": output_data
        })

    def set_request_context(self, **context: Any) -> None:
        """设置当前请求的日志上下文。"""
        self._request_context = {
            "agent_class": self.__class__.__name__,
            **context,
        }

    def clear_request_context(self) -> None:
        """清理当前请求的日志上下文。"""
        self._request_context = {}

    def _log_runtime_event(self, event: str, **fields: Any) -> None:
        """打印带请求上下文的结构化运行时日志。"""
        payload = {**self._request_context, **fields}
        emit_runtime_log(event, **payload)
    
    def _log_performance(self, operation, metrics):
        """记录性能指标"""
        self.performance_metrics[operation] = {
            "timestamp": time.time(),
            **metrics
        }

        log_fields = dict(metrics)
        if "duration" in log_fields:
            log_fields["duration_ms"] = round(log_fields["duration"] * 1000, 2)

        self._log_runtime_event(
            "agent.performance",
            operation=operation,
            **log_fields
        )
    
    def _agent_node(self, state):
        """Agent 节点逻辑"""
        messages = state["messages"]
        
        # 提取关键词优化查询
        if len(messages) > 0 and isinstance(messages[-1], HumanMessage):
            query = messages[-1].content
            keywords = self._extract_keywords(query)
            
            # 记录关键词
            self._log_execution("extract_keywords", query, keywords)
            
            # 增强消息，添加关键词信息
            if keywords:
                # 创建一个新的消息，带有关键词元数据
                enhanced_message = HumanMessage(
                    content=query,
                    additional_kwargs={"keywords": keywords}
                )
                # 替换原始消息
                messages = messages[:-1] + [enhanced_message]
        
        # 使用工具处理请求。
        # 这里先清洗历史消息中的 tool_call 参数，避免兼容接口拒绝非 JSON 字符串。
        model = self.llm.bind_tools(self.tools)
        response = model.invoke(self._prepare_messages_for_model(messages))
        
        self._log_execution("agent", messages, response)
        return {"messages": [response]}
    
    @abstractmethod
    def _extract_keywords(self, query: str) -> Dict[str, List[str]]:
        """提取查询关键词，子类必须实现"""
        pass
    
    @abstractmethod
    def _generate_node(self, state):
        """生成回答节点逻辑，子类必须实现"""
        pass

    async def _generate_node_stream(self, state):
        """
        生成回答节点逻辑的流式版本
        
        参数:
            state: 当前状态
            
        返回:
            AsyncGenerator[str, None]: 流式响应生成器
        """
        # 默认实现 - 应由子类覆盖
        result = self._generate_node(state)
        if "messages" in result and result["messages"]:
            message = result["messages"][0]
            content = message.content if hasattr(message, "content") else str(message)
            
            # 模拟流式输出
            for i in range(0, len(content), self.chunk_size):
                yield content[i:i+self.chunk_size]
                await asyncio.sleep(0.01)

    async def _reduce_node_stream(self, state: Dict[str, Any]) -> AsyncGenerator[str, None]:
        """Reduce 节点的默认流式实现，默认回退为同步生成后分块。"""
        raise NotImplementedError("当前 Agent 未实现 reduce 流式输出")
    
    async def _generate_node_async(self, state):
        """
        生成回答节点逻辑的异步版本
        
        参数:
            state: 当前状态
            
        返回:
            Dict: 包含消息的结果字典
        """
        # 这个默认实现只是调用同步版本
        # 子类应该提供真正的异步实现
        def sync_generate():
            return self._generate_node(state)
            
        # 在线程池中运行同步代码，避免阻塞事件循环
        return await asyncio.get_event_loop().run_in_executor(None, sync_generate)
    
    def check_fast_cache(self, query: str, thread_id: str = "default") -> str:
        """专用的快速缓存检查方法，仅执行精确高质量缓存命中。"""
        start_time = time.time()

        # 快速路径必须避免触发 LLM 和语义检索，只做会话内精确缓存命中。
        result = self.cache_manager.get_exact(
            query,
            high_quality_only=True,
            thread_id=thread_id
        )
        duration = time.time() - start_time
        self._log_performance("fast_cache_check", {
            "duration": duration,
            "hit": result is not None
        })
        
        return result if self._should_cache_response(result) else None

    def _build_keyword_cache_params(self, query: str, thread_id: str = "default") -> Dict[str, Any]:
        """构建语义缓存所需的关键词参数。"""
        keywords = self._extract_keywords(query)
        return {
            "thread_id": thread_id,
            "low_level_keywords": self._normalize_keywords(
                keywords.get("low_level", [])
            ),
            "high_level_keywords": self._normalize_keywords(
                keywords.get("high_level", [])
            )
        }

    def check_semantic_cache(
        self,
        query: str,
        thread_id: str = "default",
        *,
        high_quality_only: bool = True
    ) -> str:
        """执行语义缓存检查，作为精确缓存失配后的慢路径兜底。"""
        start_time = time.time()

        keyword_start = time.time()
        cache_params = self._build_keyword_cache_params(query, thread_id)
        keyword_duration = time.time() - keyword_start

        semantic_lookup_start = time.time()
        result = self.cache_manager.get_semantic(
            query,
            high_quality_only=high_quality_only,
            top_k=1 if high_quality_only else 3,
            **cache_params
        )
        semantic_lookup_duration = time.time() - semantic_lookup_start

        duration = time.time() - start_time
        self._log_performance("semantic_cache_check", {
            "duration": duration,
            "keyword_duration": keyword_duration,
            "semantic_lookup_duration": semantic_lookup_duration,
            "high_quality_only": high_quality_only,
            "hit": result is not None
        })

        return result if self._should_cache_response(result) else None

    def _lookup_cached_response(self, query: str, thread_id: str = "default"):
        """统一缓存决策逻辑，返回命中内容、命中类型与总耗时。"""
        cache_check_start = time.time()

        # 1. 全局缓存仅做精确匹配，避免在共享缓存上触发昂贵的语义检索。
        global_result = self.global_cache_manager.get_exact(query)
        if self._should_cache_response(global_result):
            cache_time = time.time() - cache_check_start
            self._log_performance("cache_check", {
                "duration": cache_time,
                "type": "global_exact"
            })
            return global_result, "global_exact", cache_time

        # 2. 会话快速路径只允许精确高质量命中，保证 fast path 可预测。
        fast_result = self.check_fast_cache(query, thread_id)
        if self._should_cache_response(fast_result):
            self.global_cache_manager.set(query, fast_result)
            cache_time = time.time() - cache_check_start
            self._log_performance("cache_check", {
                "duration": cache_time,
                "type": "fast_exact"
            })
            return fast_result, "fast_exact", cache_time

        # 3. 语义缓存单独作为慢路径阶段，便于独立观测与熔断。
        semantic_result = self.check_semantic_cache(
            query,
            thread_id,
            high_quality_only=True
        )
        if self._should_cache_response(semantic_result):
            self.global_cache_manager.set(query, semantic_result)
            cache_time = time.time() - cache_check_start
            self._log_performance("cache_check", {
                "duration": cache_time,
                "type": "semantic_high_quality"
            })
            return semantic_result, "semantic_high_quality", cache_time

        # 4. 精确缓存兜底，允许返回未标记高质量但仍可用的会话缓存。
        exact_result = self.cache_manager.get_exact(query, thread_id=thread_id)
        if self._should_cache_response(exact_result):
            self.global_cache_manager.set(query, exact_result)
            cache_time = time.time() - cache_check_start
            self._log_performance("cache_check", {
                "duration": cache_time,
                "type": "standard_exact"
            })
            return exact_result, "standard_exact", cache_time

        # 5. 最后再尝试常规语义缓存，保留原有语义命中能力，但不再伪装成 fast path。
        semantic_fallback = self.check_semantic_cache(
            query,
            thread_id,
            high_quality_only=False
        )
        if self._should_cache_response(semantic_fallback):
            self.global_cache_manager.set(query, semantic_fallback)
            cache_time = time.time() - cache_check_start
            self._log_performance("cache_check", {
                "duration": cache_time,
                "type": "semantic_fallback"
            })
            return semantic_fallback, "semantic_fallback", cache_time

        cache_time = time.time() - cache_check_start
        self._log_performance("cache_check", {
            "duration": cache_time,
            "type": "miss"
        })
        return None, "miss", cache_time
    
    def _check_all_caches(self, query: str, thread_id: str = "default"):
        """整合的缓存检查方法"""
        cached_result, cache_type, _ = self._lookup_cached_response(query, thread_id)
        if self._should_cache_response(cached_result):
            self._log_runtime_event(
                "agent.cache_hit",
                thread_id=thread_id,
                cache_type=cache_type,
                query_preview=shorten_text(query)
            )
            return cached_result
        return None
    
    def ask_with_trace(self, query: str, thread_id: str = "default", recursion_limit: Optional[int] = None) -> Dict:
        """执行查询并获取带执行轨迹的回答"""
        overall_start = time.time()
        self.execution_log = []  # 重置执行日志
        recursion_limit = (
            recursion_limit
            if recursion_limit is not None
            else self.default_recursion_limit
        )
        
        # 确保查询字符串是干净的
        safe_query = query.strip()
        self._log_runtime_event(
            "agent.ask_with_trace.start",
            thread_id=thread_id,
            query_preview=shorten_text(safe_query)
        )
        
        cached_response, cache_type, cache_time = self._lookup_cached_response(
            safe_query,
            thread_id
        )
        if self._is_valid_text_response(cached_response):
            self._log_runtime_event(
                "agent.ask_with_trace.cache_hit",
                cache_type=cache_type,
                duration=cache_time,
                duration_ms=round(cache_time * 1000, 2)
            )
            return {
                "answer": cached_response,
                "execution_log": [{
                    "node": f"{cache_type}_cache_hit",
                    "timestamp": time.time(),
                    "input": safe_query,
                    "output": f"缓存命中: {cache_type}"
                }]
            }
        
        # 未命中缓存，执行标准流程
        process_start = time.time()
        self._log_runtime_event(
            "agent.ask_with_trace.processing_start",
            thread_id=thread_id
        )
        
        config = {
            "configurable": {
                "thread_id": thread_id,
                "recursion_limit": recursion_limit
            }
        }
        
        inputs = {"messages": [HumanMessage(content=query)]}
        try:
            # 执行完整的处理流程
            for output in self.graph.stream(inputs, config=config):
                pprint.pprint(f"Output from node '{list(output.keys())[0]}':")
                pprint.pprint("---")
                pprint.pprint(output, indent=2, width=80, depth=None)
                pprint.pprint("\n---\n")
                
            chat_history = self.memory.get(config)["channel_values"]["messages"]
            answer = chat_history[-1].content
            
            # 缓存处理结果 - 同时更新会话缓存和全局缓存
            if self._is_valid_text_response(answer) and len(answer) > 10:
                # 更新会话缓存
                self.cache_manager.set(safe_query, answer, thread_id=thread_id)
                # 更新全局缓存
                self.global_cache_manager.set(safe_query, answer)
            
            process_time = time.time() - process_start
            overall_time = time.time() - overall_start
            self._log_performance("ask_with_trace", {
                "total_duration": overall_time,
                "cache_check": cache_time,
                "processing": process_time
            })
            self._log_runtime_event(
                "agent.ask_with_trace.success",
                processing_duration=process_time,
                processing_duration_ms=round(process_time * 1000, 2),
                total_duration=overall_time,
                total_duration_ms=round(overall_time * 1000, 2)
            )
            
            return {
                "answer": answer,
                "execution_log": self.execution_log
            }
        except Exception as e:
            error_time = time.time() - process_start
            self._log_runtime_event(
                "agent.ask_with_trace.error",
                error=str(e),
                duration=error_time,
                duration_ms=round(error_time * 1000, 2)
            )
            return {
                "answer": f"抱歉，处理您的问题时遇到了错误。请稍后再试或换一种提问方式。错误详情: {str(e)}",
                "execution_log": self.execution_log + [{"node": "error", "timestamp": time.time(), "input": query, "output": str(e)}]
            }
        
    def ask(self, query: str, thread_id: str = "default", recursion_limit: Optional[int] = None):
        """向Agent提问"""
        overall_start = time.time()
        
        # 确保查询字符串是干净的
        safe_query = query.strip()
        self._log_runtime_event(
            "agent.ask.start",
            thread_id=thread_id,
            query_preview=shorten_text(safe_query)
        )
        
        cached_result = self._check_all_caches(safe_query, thread_id)
        if cached_result:
            total_time = time.time() - overall_start
            self._log_runtime_event(
                "agent.ask.cache_hit",
                total_duration=total_time,
                total_duration_ms=round(total_time * 1000, 2)
            )
            return cached_result
        
        # 未命中缓存，执行标准流程
        process_start = time.time()
        
        recursion_value = (
            recursion_limit
            if recursion_limit is not None
            else self.default_recursion_limit
        )
        
        # 正常处理请求
        config = {
            "configurable": {
                "thread_id": thread_id,
                "recursion_limit": recursion_value
            }
        }
        
        inputs = {"messages": [HumanMessage(content=query)]}
        try:
            for output in self.graph.stream(inputs, config=config):
                pass
                    
            chat_history = self.memory.get(config)["channel_values"]["messages"]
            answer = chat_history[-1].content
            
            # 缓存处理结果 - 同时更新会话缓存和全局缓存
            if self._is_valid_text_response(answer) and len(answer) > 10:
                # 更新会话缓存
                self.cache_manager.set(safe_query, answer, thread_id=thread_id)
                # 更新全局缓存
                self.global_cache_manager.set(safe_query, answer)
            
            process_time = time.time() - process_start
            overall_time = time.time() - overall_start
            
            self._log_performance("ask", {
                "total_duration": overall_time,
                "cache_check": 0,  # 由_check_all_caches记录
                "processing": process_time
            })
            self._log_runtime_event(
                "agent.ask.success",
                processing_duration=process_time,
                processing_duration_ms=round(process_time * 1000, 2),
                total_duration=overall_time,
                total_duration_ms=round(overall_time * 1000, 2)
            )
            
            return answer
        except Exception as e:
            error_time = time.time() - process_start
            self._log_runtime_event(
                "agent.ask.error",
                error=str(e),
                duration=error_time,
                duration_ms=round(error_time * 1000, 2)
            )
            return f"抱歉，处理您的问题时遇到了错误。请稍后再试或换一种提问方式。错误详情: {str(e)}"
    
    async def ask_stream(self, query: str, thread_id: str = "default", recursion_limit: Optional[int] = None) -> AsyncGenerator[Any, None]:
        """
        向Agent提问，返回流式响应
        
        参数:
            query: 用户问题
            thread_id: 会话ID
            recursion_limit: 递归限制
                
        返回:
            AsyncGenerator[str, None]: 流式响应生成器
        """
        overall_start = time.time()
        
        # 确保查询字符串是干净的
        safe_query = query.strip()
        self._log_runtime_event(
            "agent.ask_stream.start",
            thread_id=thread_id,
            query_preview=shorten_text(safe_query)
        )
        cache_lookup_start = time.time()
        cached_response, _, _ = self._lookup_cached_response(safe_query, thread_id)
        self._log_runtime_event(
            "agent.ask_stream.cache_lookup",
            thread_id=thread_id,
            duration=time.time() - cache_lookup_start,
            duration_ms=round((time.time() - cache_lookup_start) * 1000, 2),
            hit=bool(cached_response),
        )
        if cached_response:
            yield self._make_stage_event("cache_replay", "命中缓存，正在回放结果", source="cache")
            async for chunk in self._replay_text_stream(cached_response):
                yield chunk
            self._log_runtime_event(
                "agent.ask_stream.cache_hit",
                thread_id=thread_id,
                response_length=len(cached_response)
            )
            return
        
        # 未命中缓存，执行标准流程
        recursion_value = (
            recursion_limit
            if recursion_limit is not None
            else self.default_recursion_limit
        )
        config = {
            "configurable": {
                "thread_id": thread_id,
                "recursion_limit": recursion_value,
                "stream_mode": True  # 指示流式输出模式
            }
        }
        
        inputs = {"messages": [HumanMessage(content=query)]}
        answer = ""
        first_chunk_emitted = False
        
        try:
            # 执行流式处理
            async for chunk in self._stream_process(inputs, config):
                if not first_chunk_emitted:
                    self._log_runtime_event(
                        "agent.ask_stream.first_chunk",
                        thread_id=thread_id
                    )
                    first_chunk_emitted = True
                yield chunk
                if isinstance(chunk, str):
                    answer += chunk
                elif isinstance(chunk, dict) and chunk.get("status") == "token":
                    answer += str(chunk.get("content", ""))
            
            # 缓存完整回答 - 同时更新会话缓存和全局缓存
            if answer and len(answer) > 10:
                cache_store_start = time.time()
                # 更新会话缓存
                self.cache_manager.set(safe_query, answer, thread_id=thread_id)
                # 更新全局缓存
                self.global_cache_manager.set(safe_query, answer)
                self._log_runtime_event(
                    "agent.ask_stream.cache_store",
                    thread_id=thread_id,
                    duration=time.time() - cache_store_start,
                    duration_ms=round((time.time() - cache_store_start) * 1000, 2),
                )
            
            process_time = time.time() - overall_start
            self._log_performance("ask_stream", {
                "total_duration": process_time,
                "processing": process_time
            })
            self._log_runtime_event(
                "agent.ask_stream.success",
                total_duration=process_time,
                total_duration_ms=round(process_time * 1000, 2),
                response_length=len(answer)
            )
            
        except Exception as e:
            error_time = time.time() - overall_start
            error_msg = f"处理查询时出错: {str(e)} ({error_time:.4f}s)"
            self._log_runtime_event(
                "agent.ask_stream.error",
                error=str(e),
                duration=error_time,
                duration_ms=round(error_time * 1000, 2)
            )
            yield error_msg
    
    def mark_answer_quality(self, query: str, is_positive: bool, thread_id: str = "default"):
        """标记回答质量，用于缓存质量控制"""
        start_time = time.time()
        
        # 提取关键词
        keywords = self._extract_keywords(query)
        cache_params = {
            "thread_id": thread_id,
            "low_level_keywords": self._normalize_keywords(
                keywords.get("low_level", [])
            ),
            "high_level_keywords": self._normalize_keywords(
                keywords.get("high_level", [])
            )
        }
        
        # 调用缓存管理器的质量标记方法，传递相关参数
        marked = self.cache_manager.mark_quality(query.strip(), is_positive, **cache_params)
        
        mark_time = time.time() - start_time
        self._log_performance("mark_quality", {
            "duration": mark_time,
            "is_positive": is_positive
        })
    
    def clear_cache_for_query(self, query: str, thread_id: str = "default"):
        """
        清除特定查询的缓存（会话缓存和全局缓存）
        
        参数:
            query: 查询字符串
            thread_id: 会话ID
        
        返回:
            bool: 是否成功删除
        """
        # 清除会话缓存
        success = False
        
        try:
            # 尝试移除可能存在的前缀
            clean_query = query.strip()
            if ":" in clean_query:
                parts = clean_query.split(":", 1)
                if len(parts) > 1:
                    clean_query = parts[1].strip()
            
            # 清除原始查询的会话缓存
            session_cache_deleted = self.cache_manager.delete(query.strip(), thread_id=thread_id)
            success = session_cache_deleted
            
            # 清除没有前缀的查询缓存
            if clean_query != query.strip():
                self.cache_manager.delete(clean_query, thread_id=thread_id)
            
            # 清除带前缀的查询缓存变体
            prefixes = ["generate:", "deep:", "query:"]
            for prefix in prefixes:
                self.cache_manager.delete(f"{prefix}{clean_query}", thread_id=thread_id)
            
            # 清除全局缓存 - 使用所有可能的变体
            if hasattr(self, 'global_cache_manager'):
                # 删除原始查询
                global_cache_deleted = self.global_cache_manager.delete(query.strip())
                success = success or global_cache_deleted
                
                # 删除清理后的查询
                if clean_query != query.strip():
                    self.global_cache_manager.delete(clean_query)
                
                # 删除带前缀的查询变体
                for prefix in prefixes:
                    self.global_cache_manager.delete(f"{prefix}{clean_query}")
            
            # 强制刷新缓存写入
            if hasattr(self.cache_manager.storage, '_flush_write_queue'):
                self.cache_manager.storage._flush_write_queue()
            
            if hasattr(self, 'global_cache_manager') and hasattr(self.global_cache_manager.storage, '_flush_write_queue'):
                self.global_cache_manager.storage._flush_write_queue()
                
            # 记录日志
            print(f"已清除查询缓存: {query.strip()}")
            
            return success
        except Exception as e:
            print(f"清除缓存时出错: {e}")
            return False
    
    def _validate_answer(self, query: str, answer: str, thread_id: str = "default") -> bool:
        """验证答案质量"""
        
        # 使用缓存管理器的验证方法
        def validator(query, answer):
            # 基本检查 - 长度
            if len(answer) < 20:
                return False
                
            # 检查是否包含错误消息
            error_patterns = [
                "抱歉，处理您的问题时遇到了错误",
                "技术原因:",
                "无法获取",
                "无法回答这个问题"
            ]
            
            for pattern in error_patterns:
                if pattern in answer:
                    return False
                    
            # 相关性检查 - 检查问题关键词是否在答案中出现
            keywords = self._extract_keywords(query)
            if keywords:
                low_level_keywords = self._normalize_keywords(
                    keywords.get("low_level", [])
                )
                if low_level_keywords:
                    # 至少有一个低级关键词应该在答案中出现
                    keyword_found = any(keyword.lower() in answer.lower() for keyword in low_level_keywords)
                    if not keyword_found:
                        return False
            
            # 通过所有检查
            return True
        
        return self.cache_manager.validate_answer(query, answer, validator, thread_id=thread_id)
    
    def close(self):
        """关闭资源"""
        # 确保所有延迟写入的缓存项都被保存
        if hasattr(self.cache_manager.storage, '_flush_write_queue'):
            self.cache_manager.storage._flush_write_queue()
            
        # 同样确保全局缓存的写入被保存
        if hasattr(self.global_cache_manager.storage, '_flush_write_queue'):
            self.global_cache_manager.storage._flush_write_queue()
