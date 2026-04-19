"""MCP 风格工具发现入口。"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional

from graphrag_agent.mcp.adapter import build_remote_tool
from graphrag_agent.mcp.http_client import HttpMCPToolClient
from graphrag_agent.mcp.models import MCPToolDescriptor


def _parse_endpoint_list(raw_value: str) -> List[str]:
    """解析环境变量中的端点列表。"""
    value = raw_value.strip()
    if not value:
        return []

    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        parsed = None

    if isinstance(parsed, list):
        return [str(item).strip() for item in parsed if str(item).strip()]

    return [item.strip() for item in value.split(",") if item.strip()]


def get_mcp_tool_endpoints() -> List[str]:
    """读取当前配置下的 MCP 工具服务地址。"""
    endpoints = _parse_endpoint_list(os.getenv("MCP_TOOL_ENDPOINTS", ""))
    fluid_service_url = str(os.getenv("FLUID_PROPERTY_SERVICE_URL", "")).strip()
    if fluid_service_url and fluid_service_url not in endpoints:
        endpoints.append(fluid_service_url)
    return endpoints


def discover_mcp_tools(endpoints: Optional[List[str]] = None) -> Dict[str, MCPToolDescriptor]:
    """发现所有 MCP 风格工具，并按名称返回。"""
    descriptors: Dict[str, MCPToolDescriptor] = {}
    for endpoint in endpoints or get_mcp_tool_endpoints():
        try:
            client = HttpMCPToolClient(endpoint=endpoint)
            for descriptor in client.list_tools():
                descriptors[descriptor.name] = descriptor
        except Exception:
            # 发现失败不阻塞主流程，保持工具层可降级。
            continue
    return descriptors


def build_dynamic_extra_tool_factories(
    endpoints: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """将远程工具目录转换为本地可实例化工厂。"""
    descriptors = discover_mcp_tools(endpoints=endpoints)
    factories: Dict[str, Any] = {}

    for tool_name, descriptor in descriptors.items():
        factories[tool_name] = (
            lambda current_descriptor=descriptor: build_remote_tool(current_descriptor)
        )
    return factories


def build_langchain_tools_from_endpoints(
    endpoints: Optional[List[str]] = None,
    exclude_names: Optional[set[str]] = None,
) -> List[Any]:
    """批量构建 LangChain 可绑定工具。"""
    exclude_names = exclude_names or set()
    tools: List[Any] = []
    for tool_name, factory in build_dynamic_extra_tool_factories(endpoints=endpoints).items():
        if tool_name in exclude_names:
            continue
        try:
            tool = factory()
            if hasattr(tool, "get_tool"):
                tools.append(tool.get_tool())
        except Exception:
            continue
    return tools
