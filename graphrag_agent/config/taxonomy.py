"""工程热力学知识图谱分类标准。

本模块将 `知识分类与标签.xlsx` 中的分类与关系约束固化为代码常量，
作为图谱抽取、构建、检索和后续治理的统一来源。
"""

from typing import Dict, List

# Excel 中定义的总标签。当前项目的图写入链路默认只落一个业务标签，
# 因此这里先作为标准元数据保留，便于后续做索引、权限或治理扩展。
ROOT_ENTITY_LABEL = "ThermodynamicsTerm"

# 主标签列表。这里直接采用表格中的英文标签名，便于与 Neo4j label
# 以及关系类型保持稳定的机器可读语义。
ENTITY_TYPES: List[str] = [
    "Concept",
    "Law",
    "Theorem",
    "Quantity",
    "Process",
    "Cycle",
    "Equipment",
    "Formula",
    "Condition",
    "Other",
]

ENTITY_TYPE_DEFINITIONS: Dict[str, Dict[str, str]] = {
    "Concept": {
        "description": "工程热力学中的基本概念类术语。",
        "examples": "热力学系统、闭口系统、开口系统、平衡态",
    },
    "Law": {
        "description": "工程热力学中的定律类知识。",
        "examples": "热力学第一定律、热力学第二定律",
    },
    "Theorem": {
        "description": "工程热力学中的定理、推论和公理。",
        "examples": "状态公理",
    },
    "Quantity": {
        "description": "工程热力学中的物理量与状态变量。",
        "examples": "温度、压力、内能、焓、熵、热量、功",
    },
    "Process": {
        "description": "工程热力学中的基本热力过程。",
        "examples": "等温过程、等压过程、绝热过程、等熵过程",
    },
    "Cycle": {
        "description": "工程热力学中的热力循环。",
        "examples": "卡诺循环、朗肯循环、布雷顿循环、奥托循环",
    },
    "Equipment": {
        "description": "工程热力学中的设备或装置。",
        "examples": "锅炉、汽轮机、压缩机、冷凝器、换热器",
    },
    "Formula": {
        "description": "工程热力学中的公式、方程和关系式。",
        "examples": "理想气体状态方程、热效率公式、熵变公式",
    },
    "Condition": {
        "description": "工程热力学中的条件、前提和假设。",
        "examples": "闭口系、可逆、绝热、理想气体、等熵",
    },
    "Other": {
        "description": "无法稳定归入上述主标签的少量兜底实体。",
        "examples": "跨类复合对象或语义不完整片段",
    },
}

RELATIONSHIP_TYPES: List[str] = [
    "IS_A",
    "DEFINES",
    "CONSISTS_OF",
    "DEPENDS_ON",
    "DERIVES_FROM",
    "ASSUMES",
    "VALID_UNDER",
    "APPLIES_TO",
    "USES",
    "RELATED_TO",
]

RELATIONSHIP_TYPE_DEFINITIONS: Dict[str, str] = {
    "IS_A": "分类关系，用于表达实体属于某一上位概念或类别。",
    "DEFINES": "定义关系，用于表达定律、公式或概念对目标对象的定义或刻画。",
    "CONSISTS_OF": "包含关系，用于表达系统、设备或循环的组成结构。",
    "DEPENDS_ON": "依赖关系，用于表达量、过程或设备运行依赖的对象。",
    "DERIVES_FROM": "推导关系，用于表达公式、结论或性质的来源。",
    "ASSUMES": "假设关系，用于表达理论、推导或模型所采用的前提。",
    "VALID_UNDER": "适用条件关系，用于表达公式、过程或结论成立的边界。",
    "APPLIES_TO": "应用关系，用于表达公式、定律或方法适用的对象。",
    "USES": "使用关系，用于表达设备、过程或分析方法所使用的量或公式。",
    "RELATED_TO": "兜底关系，仅在无法归入上述关系时使用。",
}

TAXONOMY_CATEGORY_OVERVIEW: List[Dict[str, str]] = [
    {"name": "基础", "examples": "系统、过程、状态变量"},
    {"name": "物理量", "examples": "压力、温度、内能、焓、熵"},
    {"name": "热力过程", "examples": "热、功、熵产"},
    {"name": "热力设备", "examples": "锅炉、汽轮机、压缩机、冷凝器、换热器"},
    {"name": "公式", "examples": "理想气体状态方程、热效率公式、熵变公式"},
    {"name": "条件", "examples": "可逆、绝热等"},
]

__all__ = [
    "ROOT_ENTITY_LABEL",
    "ENTITY_TYPES",
    "ENTITY_TYPE_DEFINITIONS",
    "RELATIONSHIP_TYPES",
    "RELATIONSHIP_TYPE_DEFINITIONS",
    "TAXONOMY_CATEGORY_OVERVIEW",
]
