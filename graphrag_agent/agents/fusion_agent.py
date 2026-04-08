import asyncio
import re
import time
from typing import Any, AsyncGenerator, Dict, Optional, Tuple

from graphrag_agent.config.settings import AGENT_SETTINGS
from graphrag_agent.runtime_logging import emit_runtime_log, shorten_text

from graphrag_agent.agents.multi_agent.integration.legacy_facade import MultiAgentFacade


FUSION_EMPTY_ANSWER = "未能生成回答"


class _MemoryShim:
    """兼容旧版接口的记忆占位实现，仅提供空消息列表。"""

    def get(self, _config: Dict[str, Any]) -> Dict[str, Any]:
        return {"channel_values": {"messages": []}}


class _GraphShim:
    """兼容LangGraph所需接口的空实现。"""

    def update_state(self, *_args: Any, **_kwargs: Any) -> None:  # pragma: no cover
        return None


class FusionGraphRAGAgent:
    """Fusion GraphRAG Agent 的轻量封装版本，完全委托给多智能体编排栈。"""

    def __init__(self, cache_dir: str = "./cache/fusion_graphrag") -> None:
        self.cache_dir = cache_dir
        self.multi_agent = MultiAgentFacade()
        self.memory = _MemoryShim()
        self.graph = _GraphShim()
        self.execution_log: list[Any] = []
        self._global_cache: Dict[str, str] = {}
        self._session_cache: Dict[str, Dict[str, str]] = {}
        self._last_payload: Dict[str, Any] = {}
        self._flush_threshold = AGENT_SETTINGS["fusion_stream_flush_threshold"]
        self._default_recursion_limit = AGENT_SETTINGS["default_recursion_limit"]
        self._request_context: Dict[str, Any] = {}

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
        """输出统一格式的 Fusion Agent 运行时日志。"""
        payload = {**self._request_context, **fields}
        emit_runtime_log(event, **payload)

    def ask(self, query: str, thread_id: str = "default", recursion_limit: Optional[int] = None) -> str:
        return self._execute(query, thread_id)[0]

    def ask_with_trace(self, query: str, thread_id: str = "default", recursion_limit: Optional[int] = None) -> Dict[str, Any]:
        answer, payload = self._execute(query, thread_id)
        # 兼容 BaseAgent.ask_with_trace 的返回协议，避免上层服务因字段缺失报错。
        execution_log = self._build_execution_log(payload, query)
        return {
            "answer": answer,
            "execution_log": execution_log,
            "payload": payload,
        }

    def check_fast_cache(self, query: str, thread_id: str = "default") -> Optional[str]:
        """检查 Fusion Agent 的内存缓存，兼容现有服务层快速路径。"""
        start_time = time.time()
        result = self._read_cache(query, thread_id)
        duration = time.time() - start_time
        self._log_runtime_event(
            "agent.performance",
            operation="fast_cache_check",
            duration=duration,
            duration_ms=round(duration * 1000, 2),
            hit=result is not None,
        )
        return result

    async def ask_stream(self, query: str, thread_id: str = "default", recursion_limit: Optional[int] = None) -> AsyncGenerator[str, None]:
        cached = self._read_cache(query, thread_id)
        if cached is None:
            cached, _ = await asyncio.to_thread(self._execute, query, thread_id)
        async for chunk in self._stream_chunks(cached):
            yield chunk

    def close(self) -> None:
        self._global_cache.clear()
        self._session_cache.clear()

    def _execute(self, query: str, thread_id: str, *, assumptions: Optional[list[str]] = None, report_type: Optional[str] = None) -> Tuple[str, Dict[str, Any]]:
        self._log_runtime_event(
            "fusion.execute.start",
            thread_id=thread_id,
            query_preview=shorten_text(query)
        )
        cached = self._read_cache(query, thread_id)
        if cached is not None:
            self._log_runtime_event(
                "fusion.execute.cache_hit",
                thread_id=thread_id
            )
            return cached, {"status": "cached", "execution_records": []}
        start_time = time.time()
        payload = self.multi_agent.process_query(query.strip(), assumptions=assumptions, report_type=report_type)
        answer = self._normalize_answer(payload.get("response"))
        # 失败兜底答案不进入缓存，避免快速路径持续放大同一错误。
        if answer != FUSION_EMPTY_ANSWER:
            self._write_cache(query, thread_id, answer)
        self.execution_log = self._build_execution_log(payload, query)
        self._last_payload = payload
        duration = time.time() - start_time
        self._log_runtime_event(
            "fusion.execute.success",
            thread_id=thread_id,
            duration=duration,
            duration_ms=round(duration * 1000, 2),
            execution_record_count=len(payload.get("execution_records", [])),
        )
        return answer, payload

    def _read_cache(self, query: str, thread_id: str) -> Optional[str]:
        key = query.strip()
        return self._global_cache.get(key) or self._session_cache.get(thread_id, {}).get(key)

    def _write_cache(self, query: str, thread_id: str, answer: str) -> None:
        key = query.strip()
        self._global_cache[key] = answer
        self._session_cache.setdefault(thread_id, {})[key] = answer

    @staticmethod
    def _normalize_answer(answer: Any) -> str:
        if isinstance(answer, str) and answer.strip():
            return answer.strip()
        return FUSION_EMPTY_ANSWER if answer is None else str(answer)

    @staticmethod
    def _build_execution_log(payload: Dict[str, Any], query: str) -> list[Dict[str, Any]]:
        """将多智能体执行记录转换为服务层可直接消费的调试日志。"""
        execution_records = payload.get("execution_records", [])
        if execution_records:
            formatted_logs = []
            for record in execution_records:
                if not isinstance(record, dict):
                    formatted_logs.append({
                        "node": "fusion_agent",
                        "timestamp": time.time(),
                        "input": query,
                        "output": str(record),
                    })
                    continue

                # 兼容多智能体执行记录结构，转换为旧前端可展示的调试日志格式。
                task_id = record.get("task_id", "unknown_task")
                worker_type = record.get("worker_type", "unknown_worker")
                tool_names = [
                    tool_call.get("tool_name", "unknown_tool")
                    for tool_call in record.get("tool_calls", [])
                    if isinstance(tool_call, dict)
                ]
                reflection = record.get("reflection") or {}
                metadata = record.get("metadata") or {}
                summary = {
                    "task_id": task_id,
                    "worker_type": worker_type,
                    "tool_calls": tool_names,
                    "evidence_count": len(record.get("evidence", [])),
                    "latency_seconds": metadata.get("latency_seconds", 0.0),
                    "success": reflection.get("success", True),
                    "reasoning": reflection.get("reasoning", ""),
                }
                formatted_logs.append({
                    "node": f"fusion_{worker_type}",
                    "timestamp": record.get("created_at", time.time()),
                    "input": {
                        "query": query,
                        "task_id": task_id,
                        "worker_type": worker_type,
                    },
                    "output": summary,
                })
            return formatted_logs

        # 缓存命中场景没有执行记录，补一条统一格式日志，便于前端展示。
        if payload.get("status") == "cached":
            return [{
                "node": "cache_hit",
                "timestamp": time.time(),
                "input": query,
                "output": "Fusion Agent 内存缓存命中",
            }]

        return []

    async def _stream_chunks(self, answer: str) -> AsyncGenerator[str, None]:
        buffer = ""
        for idx, part in enumerate(re.split(r"([。！？.!?]\s*)", answer)):
            buffer += part
            if (idx % 2 and buffer.strip()) or len(buffer) >= self._flush_threshold:
                yield buffer
                buffer = ""
                await asyncio.sleep(0)
        if buffer.strip():
            yield buffer
