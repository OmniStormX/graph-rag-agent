"""搜索工具注册表。"""

from typing import Any, Dict, List, Optional, Type

from graphrag_agent.mcp.discovery import (
    build_dynamic_extra_tool_factories,
    discover_mcp_tools,
)
from graphrag_agent.search.tool.base import BaseSearchTool
from graphrag_agent.search.tool.local_search_tool import LocalSearchTool
from graphrag_agent.search.tool.global_search_tool import GlobalSearchTool
from graphrag_agent.search.tool.hybrid_tool import HybridSearchTool
from graphrag_agent.search.tool.naive_search_tool import NaiveSearchTool
from graphrag_agent.search.tool.deep_research_tool import DeepResearchTool
from graphrag_agent.search.tool.deeper_research_tool import DeeperResearchTool
from graphrag_agent.search.tool.chain_exploration_tool import ChainOfExplorationTool
from graphrag_agent.search.tool.hypothesis_tool import HypothesisGeneratorTool
from graphrag_agent.search.tool.fluid_property_tool import FluidPropertyTool
from graphrag_agent.search.tool.validation_tool import AnswerValidationTool

TOOL_REGISTRY: Dict[str, Type[BaseSearchTool]] = {
    "local_search": LocalSearchTool,
    "global_search": GlobalSearchTool,
    "hybrid_search": HybridSearchTool,
    "naive_search": NaiveSearchTool,
    "deep_research": DeepResearchTool,
    "deeper_research": DeeperResearchTool,
}

# 额外暴露的专用工具（不继承BaseSearchTool）
EXTRA_TOOL_FACTORIES: Dict[str, Any] = {
    "chain_exploration": ChainOfExplorationTool,
    "hypothesis_generator": HypothesisGeneratorTool,
    "fluid_property_calc": FluidPropertyTool,
    "answer_validator": AnswerValidationTool,
}


def get_dynamic_extra_tool_factories() -> Dict[str, Any]:
    """返回通过 MCP 风格目录发现的动态工具工厂。"""
    return build_dynamic_extra_tool_factories()


def get_tool_class(tool_name: str) -> Type[BaseSearchTool]:
    """根据名称获取工具类，若不存在则抛出KeyError"""
    return TOOL_REGISTRY[tool_name]


def available_tools() -> Dict[str, Type[BaseSearchTool]]:
    """返回注册表的浅拷贝"""
    return dict(TOOL_REGISTRY)


def available_extra_tools() -> Dict[str, Any]:
    """返回额外工具工厂的浅拷贝，动态工具优先覆盖同名静态项。"""
    return {
        **dict(EXTRA_TOOL_FACTORIES),
        **get_dynamic_extra_tool_factories(),
    }


def create_extra_tool(tool_name: str) -> Any:
    """根据名称创建额外工具实例。"""
    factories = available_extra_tools()
    factory = factories[tool_name]
    return factory()


def get_langchain_extra_tools(
    *,
    include_builtin_names: Optional[List[str]] = None,
    exclude_names: Optional[set[str]] = None,
) -> List[Any]:
    """构建 Agent 可直接绑定的额外工具列表。"""
    include_builtin_names = include_builtin_names or ["fluid_property_calc"]
    exclude_names = exclude_names or set()
    tools: List[Any] = []
    discovered_descriptors = discover_mcp_tools()
    discovered_names = set(discovered_descriptors.keys())
    dynamic_factories = get_dynamic_extra_tool_factories()

    # 先挂载内置兼容工具；若远程目录中存在同名工具，则由动态工具接管。
    for tool_name in include_builtin_names:
        if tool_name in exclude_names or tool_name in discovered_names:
            continue
        if tool_name not in EXTRA_TOOL_FACTORIES:
            continue
        tool_instance = EXTRA_TOOL_FACTORIES[tool_name]()
        if hasattr(tool_instance, "get_tool"):
            tools.append(tool_instance.get_tool())

    for tool_name, factory in dynamic_factories.items():
        if tool_name in exclude_names:
            continue
        tool_instance = factory()
        if hasattr(tool_instance, "get_tool"):
            tools.append(tool_instance.get_tool())

    return tools


__all__ = [
    "TOOL_REGISTRY",
    "EXTRA_TOOL_FACTORIES",
    "get_dynamic_extra_tool_factories",
    "get_tool_class",
    "available_tools",
    "available_extra_tools",
    "create_extra_tool",
    "get_langchain_extra_tools",
]
