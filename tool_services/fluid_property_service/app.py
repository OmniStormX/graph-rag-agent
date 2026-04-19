"""流体物性 MCP 风格独立服务。"""

from __future__ import annotations

from typing import Any, Dict

from fastapi import FastAPI

from tool_services.fluid_property_service.core import (
    FluidPropertyEngine,
    INPUT_SCHEMA,
)


app = FastAPI(
    title="Fluid Property MCP Service",
    version="1.0.0",
    description="将流体热物性计算以 MCP 风格 HTTP 工具目录暴露为独立服务。",
)
engine = FluidPropertyEngine()


@app.get("/health")
def health() -> Dict[str, Any]:
    """返回服务健康状态。"""
    return {"status": "ok", "service": "fluid_property_service"}


@app.get("/tools")
def list_tools() -> Dict[str, Any]:
    """返回服务暴露的工具元数据。"""
    return {
        "tools": [
            {
                "name": "fluid_property_calc",
                "description": (
                    "流体物性计算工具。输入 fluid、inputs、outputs 或 query，"
                    "可计算 T/P/H/S/D/Q 等热力性质。"
                ),
                "input_schema": INPUT_SCHEMA,
                "invoke_path": "/tools/fluid_property_calc/invoke",
                "tags": ["thermodynamics", "calculation", "mcp"],
            }
        ]
    }


@app.post("/tools/fluid_property_calc/invoke")
def invoke_fluid_property_tool(payload: Dict[str, Any]) -> Dict[str, Any]:
    """执行流体物性计算。"""
    return engine.structured_search(payload)
