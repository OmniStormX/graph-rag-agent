"""流体物性计算工具。"""

from __future__ import annotations

import os
from typing import Any, Callable, Dict

import requests
from langchain_core.tools import BaseTool

from tool_services.fluid_property_service.core import (
    FluidPropertyEngine,
    INPUT_SCHEMA,
    UNIT_HINTS,
    load_props_si as _service_load_props_si,
)


def _load_props_si() -> Callable[..., float]:
    """兼容旧测试入口，转发到独立服务共享核心。"""
    return _service_load_props_si()


class FluidPropertyTool:
    """面向 Agent 的流体物性计算工具。"""

    name: str = "fluid_property_calc"

    def __init__(self) -> None:
        """初始化工具，并按配置决定是否优先走远程服务。"""
        self.service_url = str(os.getenv("FLUID_PROPERTY_SERVICE_URL", "")).strip()
        self.timeout = float(os.getenv("FLUID_PROPERTY_SERVICE_TIMEOUT", "20") or 20)
        # 通过自定义 loader 保持 `_load_props_si` 可被单测打桩。
        self._engine = FluidPropertyEngine(props_loader=lambda: _load_props_si())
        self._default_extract_with_llm_fallback = self._engine._extract_with_llm_fallback  # noqa: SLF001

    def _remote_invoke(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """调用独立流体物性服务。"""
        if not self.service_url:
            raise RuntimeError("未配置 FLUID_PROPERTY_SERVICE_URL")
        response = requests.post(
            f"{self.service_url.rstrip('/')}/tools/{self.name}/invoke",
            json=payload,
            timeout=self.timeout,
        )
        response.raise_for_status()
        result = response.json()
        if isinstance(result, dict):
            return result
        return {
            "success": True,
            "results": result,
            "metadata": {},
            "error": None,
            "retrieval_results": [],
        }

    def _canonicalize_fluid_name(self, fluid: Any) -> str:
        """委托共享引擎执行工质名称归一化。"""
        return self._engine._canonicalize_fluid_name(fluid)  # noqa: SLF001

    def _canonicalize_outputs(self, outputs: Any) -> list[str]:
        """委托共享引擎执行输出字段归一化。"""
        return self._engine._canonicalize_outputs(outputs)  # noqa: SLF001

    def _normalize_candidate_payload(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """委托共享引擎规范化候选载荷。"""
        return self._engine._normalize_candidate_payload(payload)  # noqa: SLF001

    def _build_llm_fallback_prompt(self, query: str) -> str:
        """委托共享引擎生成兜底提示词。"""
        return self._engine._build_llm_fallback_prompt(query)  # noqa: SLF001

    def _extract_json_object(self, text: str) -> Dict[str, Any]:
        """委托共享引擎提取 JSON。"""
        return self._engine._extract_json_object(text)  # noqa: SLF001

    def _extract_with_llm_fallback(self, query: str) -> Dict[str, Any]:
        """委托共享引擎使用 LLM 做结构化补全。"""
        return self._default_extract_with_llm_fallback(query)

    def _extract_from_query(self, query: str) -> Dict[str, Any]:
        """委托共享引擎解析自然语言。"""
        original_fallback = self._engine._extract_with_llm_fallback  # noqa: SLF001
        self._engine._extract_with_llm_fallback = (  # noqa: SLF001
            lambda current_query: type(self)._extract_with_llm_fallback(self, current_query)
        )
        try:
            return self._engine._extract_from_query(query)  # noqa: SLF001
        finally:
            self._engine._extract_with_llm_fallback = original_fallback  # noqa: SLF001

    def _normalize_request(self, request: Dict[str, Any]) -> Dict[str, Any]:
        """兼容旧接口，规范化输入请求。"""
        payload = request
        if not isinstance(payload, dict):
            raise ValueError("request 必须是字典")

        nested_payload = payload.get("query") or payload.get("input")
        if isinstance(nested_payload, dict):
            payload = nested_payload
        elif isinstance(nested_payload, str):
            extracted_payload = self._extract_from_query(nested_payload)
            payload = {**payload, **extracted_payload}

        payload = self._normalize_candidate_payload(payload)

        fluid = str(payload.get("fluid", "")).strip()
        inputs = payload.get("inputs", {})
        outputs = payload.get("outputs", [])

        if not fluid:
            raise ValueError("fluid 不能为空")
        if not isinstance(inputs, dict) or len(inputs) != 2:
            raise ValueError("inputs 必须且只能提供两个状态参数，例如 {'T': 300, 'P': 101.325}")
        if not isinstance(outputs, list) or not outputs:
            raise ValueError("outputs 必须是非空列表，例如 ['H', 'S']")

        return {
            "fluid": fluid,
            "inputs": inputs,
            "outputs": outputs,
        }

    def calculate(self, request: Dict[str, Any]) -> Dict[str, Any]:
        """执行流体物性计算。"""
        if self.service_url:
            try:
                return self._remote_invoke(request)
            except Exception:
                # 远程服务不可用时回退本地计算，避免阻塞主流程。
                pass
        try:
            normalized = self._normalize_request(request)
        except Exception as exc:  # noqa: BLE001
            return {
                "success": False,
                "results": {},
                "metadata": {"notes": []},
                "error": str(exc),
            }
        return self._engine.calculate(normalized)

    def structured_search(self, request: Dict[str, Any]) -> Dict[str, Any]:
        """兼容多 Agent 检索执行器的结构化返回协议。"""
        if self.service_url:
            try:
                return self._remote_invoke(request)
            except Exception:
                pass
        calc_result = self.calculate(request)
        normalized = request if isinstance(request, dict) else {}
        try:
            normalized = self._normalize_request(normalized)
        except Exception:
            normalized = request if isinstance(request, dict) else {}
        query_text = (
            f"fluid={normalized.get('fluid', '')}, "
            f"inputs={normalized.get('inputs', {})}, "
            f"outputs={normalized.get('outputs', [])}"
        )
        return {
            "query": query_text,
            "answer": (
                f"流体物性计算成功: {calc_result['results']}"
                if calc_result["success"]
                else f"流体物性计算失败: {calc_result['error']}"
            ),
            "success": calc_result["success"],
            "results": calc_result["results"],
            "metadata": calc_result.get("metadata", {}),
            "error": calc_result["error"],
            "retrieval_results": [],
        }

    def search(self, request: Dict[str, Any]) -> Dict[str, Any]:
        """兼容额外工具工厂的统一调用入口。"""
        return self.structured_search(request)

    def get_tool(self) -> BaseTool:
        """返回可供 LangChain/LangGraph 调用的工具对象。"""
        outer = self

        class FluidPropertyLCTool(BaseTool):
            """流体物性计算 LangChain 工具。"""

            name: str = "fluid_property_calc"
            description: str = (
                "流体物性计算工具。"
                "输入字段包括 fluid、inputs、outputs 或 query。"
                "inputs 必须提供两个状态量，支持 T(K)、P(kPa)、H(kJ/kg)、"
                "S(kJ/(kg*K))、D(kg/m^3)、Q(0-1)。"
                "outputs 为需要计算的目标物性列表，例如 ['H', 'S']。"
                "该工具适用于焓熵、压力温度、密度干度等定量热力学计算。"
            )

            def _run(self, request: Any, **kwargs: Any) -> Dict[str, Any]:
                """同步调用流体物性计算。"""
                payload: Dict[str, Any]
                if isinstance(request, dict):
                    payload = dict(request)
                else:
                    payload = {}
                payload.update(kwargs)
                if not payload and isinstance(request, dict):
                    payload = request
                return outer.calculate(payload)

            def _arun(self, *args: Any, **kwargs: Any) -> Any:
                """当前仅支持同步调用。"""
                raise NotImplementedError("异步执行未实现")

        return FluidPropertyLCTool()

    @staticmethod
    def get_input_schema() -> Dict[str, Any]:
        """返回工具输入模式，便于外部服务注册。"""
        return dict(INPUT_SCHEMA)

    @staticmethod
    def get_supported_units() -> Dict[str, str]:
        """返回当前接口使用的工程单位说明。"""
        return dict(UNIT_HINTS)
