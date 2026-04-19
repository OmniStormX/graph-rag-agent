"""
图谱构建与社区摘要提示模板集合。

这些模板用于图谱索引的构建与维护流程。
"""

system_template_build_graph = """
你负责工程热力学知识图谱抽取。

要求：
1. 只抽取文本中有明确证据的实体和关系，宁缺毋滥。
2. 实体类型必须从 [{entity_types}] 中选择。
3. 关系类型必须从 [{relationship_types}] 中选择；无法准确归类时用 RELATED_TO。
4. 优先抽取定律、公式、物理量、过程、循环、设备、条件及其强语义关系。
5. 忽略目录、页眉页脚、题号、图注、编号碎片和泛泛叙事。
6. 所有说明文字使用中文，实体名保留原文，不要强制转大写。

输出格式：
1. 实体：("entity"{tuple_delimiter}<entity_name>{tuple_delimiter}<entity_type>{tuple_delimiter}<entity_description>)
2. 关系：("relationship"{tuple_delimiter}<source_entity>{tuple_delimiter}<target_entity>{tuple_delimiter}<relationship_type>{tuple_delimiter}<relationship_description>{tuple_delimiter}<relationship_strength>)
3. 多条记录之间使用 {record_delimiter} 分隔。
4. 结束时输出 {completion_delimiter}
5. 若没有可抽取内容，只输出 {completion_delimiter}
"""

human_template_build_graph = """
实体类型：{entity_types}
关系类型：{relationship_types}
文本：
{input_text}
输出：
"""

system_template_build_graph_batch = """
你负责批量抽取工程热力学知识图谱。

要求：
1. 输入包含多个 chunk，每个 chunk 都有唯一编号。
2. 对每个 chunk 独立抽取，不要跨 chunk 合并实体或关系。
3. 只抽取有明确证据的实体和关系，忽略目录、页眉页脚、图注和低价值碎片。
4. 实体类型必须从 [{entity_types}] 中选择。
5. 关系类型必须从 [{relationship_types}] 中选择；无法准确归类时用 RELATED_TO。
6. 所有说明文字使用中文，实体名保留原文。

输出协议：
1. 每个 chunk 的结果必须包裹在 [RESULT_START:{{chunk_id}}] 和 [RESULT_END:{{chunk_id}}] 之间。
2. 结果块内部使用以下记录格式：
("entity"{tuple_delimiter}<entity_name>{tuple_delimiter}<entity_type>{tuple_delimiter}<entity_description>)
("relationship"{tuple_delimiter}<source_entity>{tuple_delimiter}<target_entity>{tuple_delimiter}<relationship_type>{tuple_delimiter}<relationship_description>{tuple_delimiter}<relationship_strength>)
3. 同一 chunk 内多条记录使用 {record_delimiter} 分隔。
4. 若某个 chunk 无有效结果，仍需输出对应编号的空结果块，即 [RESULT_START:{{chunk_id}}] [RESULT_END:{{chunk_id}}]。
"""

human_template_build_graph_batch = """
实体类型：{entity_types}
关系类型：{relationship_types}
以下是多个 chunk，请逐个独立处理：
{input_text}
输出：
"""

system_template_build_index = """
你是一名数据处理助理。您的任务是识别列表中的重复实体，并决定应合并哪些实体。 
这些实体在格式或内容上可能略有不同，但本质上指的是同一个实体。运用你的分析技能来确定重复的实体。 
以下是识别重复实体的规则： 
1.语义上差异较小的实体应被视为重复。 
2.格式不同但内容相同的实体应被视为重复。 
3.引用同一现实世界对象或概念的实体，即使描述不同，也应被视为重复。 
4.如果它指的是不同的数字、日期或产品型号，请不要合并实体。
输出格式：
1.将要合并的实体输出为Python列表的格式，输出时保持它们输入时的原文。
2.如果有多组可以合并的实体，每组输出为一个单独的列表，每组分开输出为一行。
3.如果没有要合并的实体，就输出一个空的列表。
4.只输出列表即可，不需要其它的说明。
5.不要输出嵌套的列表，只输出列表。
###################### 
-示例- 
###################### 
Example 1:
['Star Ocean The Second Story R', 'Star Ocean: The Second Story R', 'Star Ocean: A Research Journey']
#############
Output:
['Star Ocean The Second Story R', 'Star Ocean: The Second Story R']
#############################
Example 2:
['Sony', 'Sony Inc', 'Google', 'Google Inc', 'OpenAI']
#############
Output:
['Sony', 'Sony Inc']
['Google', 'Google Inc']
#############################
Example 3:
['December 16, 2023', 'December 2, 2023', 'December 23, 2023', 'December 26, 2023']
Output:
[]
#############################
"""

user_template_build_index = """
以下是要处理的实体列表： 
{entities} 
请识别重复的实体，提供可以合并的实体列表。
输出：
"""

community_template = """
基于所提供的属于同一图社区的节点和关系， 
生成所提供图社区信息的自然语言摘要： 
{community_info} 
摘要：
"""

COMMUNITY_SUMMARY_PROMPT = """
你负责为知识图谱社区生成结构化主题概括。

请严格输出 JSON 对象，不要添加任何额外说明、Markdown 代码块或前后缀。

输出格式：
{{
  "topic": "不超过18个中文字符的社区主题标题",
  "summary": "1到3句中文摘要，概括该社区的核心对象、关系与主题"
}}

要求：
1. `topic` 必须像标题，适合作为社区节点名称。
2. `summary` 应概括社区讨论的主要概念、关键关系和上下文，不要泛泛而谈。
3. 如果信息不足，也必须尽量给出一个可读的主题与简短摘要。
"""

entity_alignment_prompt = """
Given these entities that should refer to the same concept:
{entity_desc}

Which entity ID best represents the canonical form? Reply with only the entity ID.
"""

__all__ = [
    "system_template_build_graph",
    "human_template_build_graph",
    "system_template_build_graph_batch",
    "human_template_build_graph_batch",
    "system_template_build_index",
    "user_template_build_index",
    "community_template",
    "COMMUNITY_SUMMARY_PROMPT",
    "entity_alignment_prompt",
]
