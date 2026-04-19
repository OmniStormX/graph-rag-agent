"""MCP 风格工具元数据模型。"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class MCPToolDescriptor(BaseModel):
    """描述一个可远程调用的 MCP 风格工具。"""

    name: str = Field(description="工具唯一名称")
    description: str = Field(default="", description="工具用途描述")
    input_schema: Dict[str, Any] = Field(
        default_factory=dict,
        description="工具输入 JSON Schema",
    )
    invoke_path: str = Field(default="", description="工具调用路径")
    endpoint: Optional[str] = Field(default=None, description="工具所在服务地址")
    tags: List[str] = Field(default_factory=list, description="工具标签")

    @property
    def invoke_url(self) -> str:
        """返回工具实际调用地址。"""
        if not self.endpoint:
            return self.invoke_path
        base = self.endpoint.rstrip("/")
        path = self.invoke_path.strip()
        if not path:
            return f"{base}/tools/{self.name}/invoke"
        if path.startswith("http://") or path.startswith("https://"):
            return path
        if not path.startswith("/"):
            path = f"/{path}"
        return f"{base}{path}"
