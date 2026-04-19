"""将 MCP 工具描述适配为项目内工具对象。"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple, Type

from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field, create_model

from graphrag_agent.mcp.http_client import HttpMCPToolClient
from graphrag_agent.mcp.models import MCPToolDescriptor


def _json_schema_to_field(schema: Dict[str, Any], required: bool) -> Tuple[Any, Any]:
    """将简化版 JSON Schema 字段转换为 Pydantic 字段。"""
    field_type_map = {
        "string": str,
        "number": float,
        "integer": int,
        "boolean": bool,
        "object": dict,
        "array": list,
    }
    schema_type = str(schema.get("type", "string")).lower()
    python_type = field_type_map.get(schema_type, Any)
    description = str(schema.get("description", "")).strip()
    default = ... if required else schema.get("default", None)
    return python_type, Field(default=default, description=description)


def create_args_schema(tool_name: str, input_schema: Dict[str, Any]) -> Type[BaseModel]:
    """根据 JSON Schema 动态生成 LangChain 工具参数模型。"""
    properties = input_schema.get("properties", {}) if isinstance(input_schema, dict) else {}
    required_fields = set(input_schema.get("required", []) or [])
    fields: Dict[str, Tuple[Any, Any]] = {}

    for field_name, field_schema in properties.items():
        if not isinstance(field_schema, dict):
            continue
        fields[field_name] = _json_schema_to_field(
            field_schema,
            required=field_name in required_fields,
        )

    if not fields:
        fields["input"] = (
            dict,
            Field(
                default_factory=dict,
                description="通用输入载荷，适用于未显式声明输入模式的工具。",
            ),
        )

    model_name = "".join(part.capitalize() for part in tool_name.split("_")) + "Args"
    return create_model(model_name, **fields)  # type: ignore[return-value]


class MCPRemoteTool:
    """项目内统一的远程工具代理。"""

    def __init__(
        self,
        descriptor: MCPToolDescriptor,
        client: HttpMCPToolClient,
    ) -> None:
        """初始化远程工具代理。"""
        self.descriptor = descriptor
        self.client = client
        self.name = descriptor.name
        self.description = descriptor.description
        self.args_schema = create_args_schema(descriptor.name, descriptor.input_schema)

    def invoke_remote(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """执行远程工具调用。"""
        return self.client.invoke_tool(self.descriptor, payload)

    def structured_search(self, request: Dict[str, Any]) -> Dict[str, Any]:
        """兼容检索执行器的结构化返回。"""
        payload = request if isinstance(request, dict) else {"input": request}
        return self.invoke_remote(payload)

    def search(self, request: Dict[str, Any]) -> Dict[str, Any]:
        """兼容既有工具调用路径。"""
        return self.structured_search(request)

    def get_tool(self) -> BaseTool:
        """生成可被 LangChain 绑定的工具对象。"""
        outer = self
        tool_args_schema = self.args_schema

        class MCPRemoteLCTool(BaseTool):
            """基于 MCP HTTP 服务的 LangChain 工具。"""

            name: str = outer.name
            description: str = outer.description or f"远程工具 {outer.name}"

            def _run(self, *args: Any, **kwargs: Any) -> Dict[str, Any]:
                """同步调用远程工具。"""
                payload: Dict[str, Any] = {}
                if args and isinstance(args[0], dict):
                    payload.update(args[0])
                elif args:
                    payload["input"] = args[0]
                payload.update(kwargs)
                return outer.invoke_remote(payload)

            def _arun(self, *args: Any, **kwargs: Any) -> Any:
                """当前仅实现同步调用。"""
                raise NotImplementedError("异步 MCP 工具调用暂未实现")

        # 类体内无法直接引用外层局部变量，这里在类创建完成后补齐参数模型。
        MCPRemoteLCTool.args_schema = tool_args_schema
        return MCPRemoteLCTool()


def build_remote_tool(descriptor: MCPToolDescriptor) -> MCPRemoteTool:
    """根据描述对象构造远程工具代理。"""
    endpoint = descriptor.endpoint or ""
    return MCPRemoteTool(
        descriptor=descriptor,
        client=HttpMCPToolClient(endpoint=endpoint),
    )
