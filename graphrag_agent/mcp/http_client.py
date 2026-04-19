"""基于 HTTP 的 MCP 风格工具客户端。"""

from __future__ import annotations

from typing import Any, Dict, List

import requests

from graphrag_agent.mcp.models import MCPToolDescriptor


class HttpMCPToolClient:
    """读取远程工具目录并负责调用工具。"""

    def __init__(self, endpoint: str, timeout: float = 10.0) -> None:
        """初始化 MCP HTTP 客户端。"""
        self.endpoint = endpoint.rstrip("/")
        self.timeout = timeout

    def list_tools(self) -> List[MCPToolDescriptor]:
        """读取服务暴露的工具列表。"""
        response = requests.get(
            f"{self.endpoint}/tools",
            timeout=self.timeout,
        )
        response.raise_for_status()
        payload = response.json()
        raw_tools = payload.get("tools", payload) if isinstance(payload, dict) else payload
        if not isinstance(raw_tools, list):
            return []

        descriptors: List[MCPToolDescriptor] = []
        for item in raw_tools:
            if not isinstance(item, dict):
                continue
            descriptor = MCPToolDescriptor(
                name=str(item.get("name", "")).strip(),
                description=str(item.get("description", "")).strip(),
                input_schema=item.get("input_schema", {}) or {},
                invoke_path=str(
                    item.get("invoke_path") or f"/tools/{item.get('name', '')}/invoke"
                ).strip(),
                endpoint=self.endpoint,
                tags=item.get("tags", []) or [],
            )
            if descriptor.name:
                descriptors.append(descriptor)
        return descriptors

    def invoke_tool(self, descriptor: MCPToolDescriptor, payload: Dict[str, Any]) -> Dict[str, Any]:
        """调用远程工具。"""
        response = requests.post(
            descriptor.invoke_url,
            json=payload,
            timeout=self.timeout,
        )
        response.raise_for_status()
        result = response.json()
        if isinstance(result, dict):
            return result
        return {
            "success": True,
            "result": result,
            "error": None,
        }
