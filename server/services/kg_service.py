import re
import traceback
import hashlib
import threading
from typing import Dict, List, Any, Tuple
from server_config.database import get_db_manager
from utils.keywords import extract_smart_keywords


# 获取数据库连接
db_manager = get_db_manager()
driver = db_manager.driver

# 基于会话与回答内容的轻量知识图谱缓存。
# 当前先使用进程内缓存，便于本地开发验证。
_KG_CACHE_LOCK = threading.RLock()
_KG_MESSAGE_CACHE: Dict[str, Dict[str, Any]] = {}


def build_kg_cache_key(
    *,
    session_id: str | None,
    message: str,
    query: str | None = None,
) -> str:
    """根据会话、回答文本和查询构造稳定缓存键。"""
    message_hash = hashlib.md5((message or "").encode("utf-8")).hexdigest()
    query_hash = hashlib.md5((query or "").encode("utf-8")).hexdigest()
    return f"kg:{session_id or 'global'}:{message_hash}:{query_hash}"


def get_cached_kg_data(
    *,
    kg_cache_key: str | None = None,
    session_id: str | None = None,
    message: str | None = None,
    query: str | None = None,
) -> Dict[str, Any] | None:
    """按缓存键或消息内容获取已缓存的回答相关图谱。"""
    cache_key = kg_cache_key
    if not cache_key and message is not None:
        cache_key = build_kg_cache_key(
            session_id=session_id,
            message=message,
            query=query,
        )

    if not cache_key:
        return None

    with _KG_CACHE_LOCK:
        cached = _KG_MESSAGE_CACHE.get(cache_key)
        if cached is None:
            return None
        return dict(cached)


def cache_kg_data_for_message(
    *,
    session_id: str | None,
    message: str,
    query: str | None,
    kg_data: Dict[str, Any],
) -> str:
    """将回答相关图谱写入缓存，并返回缓存键。"""
    cache_key = build_kg_cache_key(
        session_id=session_id,
        message=message,
        query=query,
    )
    with _KG_CACHE_LOCK:
        _KG_MESSAGE_CACHE[cache_key] = dict(kg_data or {"nodes": [], "links": []})
    return cache_key


def clear_cached_kg_data(session_id: str | None = None) -> None:
    """清理指定会话或全部回答相关图谱缓存。"""
    with _KG_CACHE_LOCK:
        if not session_id:
            _KG_MESSAGE_CACHE.clear()
            return

        prefix = f"kg:{session_id}:"
        cache_keys = [
            cache_key for cache_key in _KG_MESSAGE_CACHE
            if cache_key.startswith(prefix)
        ]
        for cache_key in cache_keys:
            _KG_MESSAGE_CACHE.pop(cache_key, None)


def _deduplicate_ids(values: List[Any]) -> List[Any]:
    """按顺序去重，避免重复查询。"""
    seen = set()
    deduplicated = []
    for value in values:
        key = str(value)
        if not key or key in seen:
            continue
        seen.add(key)
        deduplicated.append(value)
    return deduplicated


def _parse_numeric_or_string(value: str) -> Any:
    """将 ID 尽量转换为数字，否则保留字符串。"""
    clean_value = value.strip().strip("'\"")
    if clean_value.lstrip("-").isdigit():
        try:
            return int(clean_value)
        except ValueError:
            return clean_value
    return clean_value


def _parse_reference_ids_from_message(message: str) -> Tuple[List[Any], List[Any], List[str], List[Any]]:
    """
    从回答文本中解析实体、关系、文本块和报告引用。

    支持格式：
    1. `### 引用数据` 中的 `{'data': {...}}`
    2. `[[ref:关键词|Entities:4]]`
    3. `data-evidence-target="Chunks:xxxx"` 等 HTML 渲染残留
    """
    entity_ids: List[Any] = []
    relationship_ids: List[Any] = []
    chunk_ids: List[str] = []
    report_ids: List[Any] = []

    def _append_by_prefix(raw_id: str):
        """按前缀将引用分发到不同容器。"""
        clean_id = raw_id.strip().strip("'\"")
        if not clean_id:
            return

        prefix_match = re.match(r"^(Entities|Relationships|Reports|Chunks)\s*:\s*(.+)$", clean_id)
        if prefix_match:
            prefix = prefix_match.group(1)
            suffix = prefix_match.group(2).strip()
            if prefix == "Entities":
                entity_ids.append(_parse_numeric_or_string(suffix))
            elif prefix == "Relationships":
                relationship_ids.append(_parse_numeric_or_string(suffix))
            elif prefix == "Reports":
                report_ids.append(_parse_numeric_or_string(suffix))
            elif prefix == "Chunks":
                chunk_ids.append(suffix)
            return

        # 兼容纯 chunk hash 和其他直接实体 ID。
        if re.fullmatch(r"[a-fA-F0-9]{40}", clean_id):
            chunk_ids.append(clean_id)
        else:
            entity_ids.append(_parse_numeric_or_string(clean_id))

    # 解析引用数据块中的列表结构。
    for key, target_list in (
        ("Entities", entity_ids),
        ("Relationships", relationship_ids),
        ("Reports", report_ids),
    ):
        pattern = rf"['\"]?{key}['\"]?\s*:\s*\[(.*?)\]"
        match = re.search(pattern, message, re.DOTALL)
        if match:
            parts = [part.strip() for part in match.group(1).split(",") if part.strip()]
            for part in parts:
                target_list.append(_parse_numeric_or_string(part))

    chunk_match = re.search(r"['\"]?Chunks['\"]?\s*:\s*\[(.*?)\]", message, re.DOTALL)
    if chunk_match:
        chunks_str = chunk_match.group(1).strip()
        if "'" in chunks_str or '"' in chunks_str:
            chunk_ids.extend(re.findall(r"['\"]([^'\"]+)['\"]", chunks_str))
        else:
            chunk_ids.extend([part.strip() for part in chunks_str.split(",") if part.strip()])

    # 解析新的引用协议 [[ref:关键词|...]]。
    for _, raw_id in re.findall(r"\[\[ref:([^|\]]+)\|([^\]]+)\]\]", message):
        _append_by_prefix(raw_id)

    # 解析前端渲染后的 HTML 属性残留。
    for raw_id in re.findall(r"data-evidence-target=['\"]([^'\"]+)['\"]", message):
        _append_by_prefix(raw_id)

    return (
        _deduplicate_ids(entity_ids),
        _deduplicate_ids(relationship_ids),
        _deduplicate_ids(chunk_ids),
        _deduplicate_ids(report_ids),
    )


def _merge_graph_parts(*graph_parts: Dict[str, Any]) -> Dict[str, Any]:
    """合并多个子图，保留唯一节点和关系。"""
    nodes = []
    links = []
    focus_map: Dict[str, List[str]] = {}
    node_ids = set()
    link_keys = set()

    for graph_part in graph_parts:
        if not graph_part:
            continue

        for node in graph_part.get("nodes", []):
            node_id = node.get("id") if isinstance(node, dict) else None
            if not node_id or node_id in node_ids:
                continue
            node_ids.add(node_id)
            nodes.append(node)

        for link in graph_part.get("links", []):
            if not isinstance(link, dict):
                continue
            link_key = (
                str(link.get("source")),
                str(link.get("target")),
                str(link.get("label")),
            )
            if link_key in link_keys:
                continue
            link_keys.add(link_key)
            links.append(link)

        for evidence_id, related_nodes in graph_part.get("focus_map", {}).items():
            focus_map.setdefault(evidence_id, [])
            for node_id in related_nodes:
                if node_id not in focus_map[evidence_id]:
                    focus_map[evidence_id].append(node_id)

    return {
        "nodes": nodes,
        "links": links,
        "focus_map": focus_map,
    }


def _fetch_exact_entity_subgraph(entity_ids: List[Any]) -> Dict[str, Any]:
    """
    从全局图中提取严格子图：
    仅保留指定实体节点，以及这些节点之间真实存在的边。
    """
    try:
        verified_entity_ids = check_entity_existence(_deduplicate_ids(entity_ids))
        if not verified_entity_ids:
            return {"nodes": [], "links": [], "focus_map": {}}

        query = """
        // 第一步：只收集回答中实际命中的实体节点。
        MATCH (e:__Entity__)
        WHERE e.id IN $entity_ids
        WITH collect(DISTINCT e) AS entities

        // 第二步：枚举实体对，并在独立的 WITH 中完成关系聚合，
        // 避免 Neo4j 出现“聚合函数嵌套”语法错误。
        UNWIND entities AS e1
        UNWIND entities AS e2
        WITH entities, e1, e2
        WHERE e1.id < e2.id
        OPTIONAL MATCH (e1)-[r]-(e2)
        WITH entities, e1, e2, collect(r) AS rels

        // 第三步：将每对实体之间的多条边展开为扁平 links 列表。
        WITH entities,
             collect({
                 source: e1.id,
                 target: e2.id,
                 rels: rels
             }) AS relation_groups
        WITH entities,
             [group IN relation_groups WHERE size(group.rels) > 0 |
                [rel IN group.rels | {
                    source: group.source,
                    target: group.target,
                    label: type(rel),
                    weight: CASE WHEN rel.weight IS NULL THEN 1 ELSE rel.weight END
                }]
             ] AS links_nested
        WITH entities,
             REDUCE(acc = [], current IN links_nested | acc + current) AS all_links

        RETURN
        [entity IN entities | {
            id: entity.id,
            label: entity.id,
            description: CASE WHEN entity.description IS NULL THEN '' ELSE entity.description END,
            group: CASE
                WHEN [lbl IN labels(entity) WHERE lbl <> '__Entity__'] <> []
                THEN [lbl IN labels(entity) WHERE lbl <> '__Entity__'][0]
                ELSE 'AnswerEntity'
            END
        }] AS nodes,
        all_links AS links
        """

        result = driver.execute_query(query, {"entity_ids": verified_entity_ids})
        if not result.records:
            return {"nodes": [], "links": [], "focus_map": {}}

        record = result.records[0]
        nodes = record.get("nodes", []) or []
        links = record.get("links", []) or []
        focus_map = {str(entity_id): [entity_id] for entity_id in verified_entity_ids}
        return {"nodes": nodes, "links": links, "focus_map": focus_map}
    except Exception as e:
        print(f"提取严格实体子图失败: {str(e)}")
        return {"nodes": [], "links": [], "focus_map": {}}


def _resolve_answer_entity_ids(
    entity_ids: List[Any],
    relationship_ids: List[Any],
    chunk_ids: List[str],
    report_ids: List[Any],
) -> Tuple[List[Any], Dict[str, List[str]]]:
    """
    将回答中的各类引用统一解析成“回答实际使用的实体节点集合”。

    说明：
        - `Entities:*` 直接视为已使用节点
        - `Relationships:*` 转为其两端实体
        - `Chunks:*` 转为该文本块提到的实体
        - `Reports:*` 暂不扩散为整社区所有实体，避免子图失真
    """
    resolved_entity_ids: List[Any] = list(entity_ids or [])
    focus_map: Dict[str, List[str]] = {}

    # 关系引用 -> 两端实体
    if relationship_ids:
        relationship_graph = get_graph_from_relationships(relationship_ids)
        for rel_id, related_nodes in relationship_graph.get("focus_map", {}).items():
            if related_nodes:
                focus_map[rel_id] = related_nodes
                resolved_entity_ids.extend(related_nodes)

    # 文本块引用 -> 文本块提及的实体
    for chunk_id in chunk_ids or []:
        chunk_entities = get_entities_from_chunk(chunk_id)
        if chunk_entities:
            focus_map[chunk_id] = chunk_entities
            resolved_entity_ids.extend(chunk_entities)

    # 直接实体引用
    for entity_id in entity_ids or []:
        focus_map[str(entity_id)] = [entity_id]

    # Reports 目前不直接扩张为整个社区，避免把回答相关图谱放大成社区图。
    # 保留该引用键，前端若后续需要可据此提示“该引用无法精确映射到实体节点”。
    for report_id in report_ids or []:
        focus_map.setdefault(str(report_id), [])

    return _deduplicate_ids(resolved_entity_ids), focus_map


def extract_kg_from_message(message: str, query: str = None, reference: Dict = None) -> Dict:
    """
    从消息中提取知识图谱实体和关系数据
    
    Args:
        message: 消息文本
        query: 用户查询内容(可选)
        reference: 引用数据(可选)
    
    Returns:
        Dict: 知识图谱数据，包含节点和连接
    """
    try:
        # 如果提供了reference数据，优先使用
        if reference and isinstance(reference, dict):
            # 从reference中直接提取实体、关系和文本块ID
            chunks = reference.get("chunks", [])
            chunk_ids = reference.get("Chunks", [])
            
            # 尝试从chunks中获取更多信息
            for chunk in chunks:
                if "chunk_id" in chunk:
                    chunk_ids.append(chunk["chunk_id"])
                
            # 提取实体和关系ID
            entities = reference.get("entities", [])
            entity_ids = [e.get("id") for e in entities if isinstance(e, dict) and "id" in e]
            
            relationships = reference.get("relationships", [])
            rel_ids = [r.get("id") for r in relationships if isinstance(r, dict) and "id" in r]
            
            # 如果找到了chunk_ids，使用它们获取图谱
            if chunk_ids:
                return get_knowledge_graph_for_ids(entity_ids, rel_ids, chunk_ids)
        
        # 如果没有提供reference或提取失败，回退到消息文本解析
        # 如果消息包含思考过程，需要先移除
        if isinstance(message, str) and "<think>" in message and "</think>" in message:
            # 提取思考过程外的内容
            think_pattern = r'<think>.*?</think>'
            message = re.sub(think_pattern, '', message, flags=re.DOTALL).strip()
        
        # 统一解析回答中的引用结构，兼容旧 `引用数据` 和新 `[[ref:...|...]]`。
        entity_ids, rel_ids, chunk_ids, report_ids = _parse_reference_ids_from_message(message)
        
        # 提取关键词 (可选)
        query_keywords = []
        if query:
            query_keywords = extract_smart_keywords(query)
        
        # 构造“回答相关图谱”：
        # 在全局图中仅保留回答实际使用的节点，以及这些节点之间已有的边。
        answer_entity_ids, answer_focus_map = _resolve_answer_entity_ids(
            entity_ids=entity_ids,
            relationship_ids=rel_ids,
            chunk_ids=chunk_ids,
            report_ids=report_ids,
        )
        subgraph = _fetch_exact_entity_subgraph(answer_entity_ids)

        # 合并证据到节点的映射，供前端聚焦使用。
        for evidence_id, node_ids in answer_focus_map.items():
            subgraph.setdefault("focus_map", {})
            subgraph["focus_map"].setdefault(evidence_id, [])
            for node_id in node_ids:
                if node_id not in subgraph["focus_map"][evidence_id]:
                    subgraph["focus_map"][evidence_id].append(node_id)

        return subgraph
        
    except Exception as e:
        print(f"提取知识图谱数据失败: {str(e)}")
        traceback.print_exc()
        return {"nodes": [], "links": []}
    
# 辅助函数，用于从有思考过程的内容中提取实际回答
def extract_answer_from_thinking(content: str) -> str:
    """
    从带有思考过程的内容中提取实际回答
    
    Args:
        content: 带思考过程的内容
        
    Returns:
        str: 提取出的实际回答
    """
    if not isinstance(content, str):
        return content
        
    # 如果包含思考过程，提取出实际回答部分
    if "<think>" in content and "</think>" in content:
        # 使用正则表达式提取思考过程
        think_match = re.search(r'<think>(.*?)</think>', content, re.DOTALL)
        if think_match:
            # 移除思考过程，保留实际回答
            return content.replace(f"<think>{think_match.group(1)}</think>", "").strip()
    
    # 如果没有思考过程或提取失败，返回原内容
    return content


def check_entity_existence(entity_ids: List[Any]) -> List:
    """
    检查实体ID是否存在于数据库中
    
    Args:
        entity_ids: 实体ID列表
    
    Returns:
        List: 确认存在的实体ID列表
    """
    try:
        # 尝试多种格式查询，确保能找到实体
        query = """
        // 尝试不同格式匹配实体ID
        UNWIND $ids AS id
        OPTIONAL MATCH (e:__Entity__) 
        WHERE e.id = id OR 
              e.id = toString(id) OR
              toString(e.id) = toString(id)
        RETURN id AS input_id, e.id AS found_id, labels(e) AS labels
        """
        
        params = {"ids": entity_ids}
        
        result = driver.execute_query(query, params)
        
        if result.records:
            found_entities = [r.get("found_id") for r in result.records if r.get("found_id") is not None]
            return found_entities
        else:
            print("没有找到任何匹配的实体")
            return []
            
    except Exception as e:
        print(f"检查实体ID时出错: {str(e)}")
        return []


def get_entities_from_chunk(chunk_id: str) -> List:
    """
    根据文本块ID查询相关联的实体
    
    Args:
        chunk_id: 文本块ID
    
    Returns:
        List: 与该文本块关联的实体ID列表
    """
    try:
        query = """
        MATCH (c:__Chunk__)-[:MENTIONS]->(e:__Entity__)
        WHERE c.id = $chunk_id
        RETURN collect(distinct e.id) AS entity_ids
        """
        
        params = {"chunk_id": chunk_id}
        
        result = driver.execute_query(query, params)
        
        if result.records and len(result.records) > 0:
            entity_ids = result.records[0].get("entity_ids", [])
            return entity_ids
        else:
            print(f"文本块 {chunk_id} 没有关联的实体")
            return []
            
    except Exception as e:
        print(f"查询文本块关联实体时出错: {str(e)}")
        return []


def get_graph_from_chunks(chunk_ids: List[str]) -> Dict:
    """
    直接从文本块获取知识图谱
    
    Args:
        chunk_ids: 文本块ID列表
    
    Returns:
        Dict: 知识图谱数据，包含节点和连接
    """
    try:
        print(f"从文本块获取知识图谱: {chunk_ids}")
        
        query = """
        // 通过文本块直接查询相关实体
        MATCH (c:__Chunk__)-[:MENTIONS]->(e:__Entity__)
        WHERE c.id IN $chunk_ids
        
        // 获取这些实体集合
        WITH collect(DISTINCT e) AS entities
        
        // 处理实体间的关系 - 只处理每对实体一次
        UNWIND entities AS e1
        UNWIND entities AS e2
        // 确保只处理每对实体一次
        WITH entities, e1, e2 
        WHERE e1.id < e2.id
        OPTIONAL MATCH (e1)-[r]-(e2)
        
        // 收集关系
        WITH entities, e1, e2, collect(r) AS rels
        
        // 构建去重的关系集合
        WITH entities, 
             collect({
                 source: e1.id, 
                 target: e2.id, 
                 rels: rels
             }) AS relations
        
        // 扁平化和去重关系
        WITH entities,
             [rel IN relations WHERE size(rel.rels) > 0 |
              // 为每种类型的关系创建唯一记录
              [r IN rel.rels | {
                source: rel.source,
                target: rel.target,
                relType: type(r),
                label: type(r),
                weight: 1
              }]
             ] AS links_nested
             
        // 扁平化嵌套关系
        WITH entities,
             REDUCE(acc = [], list IN links_nested | acc + list) AS all_links
        
        // 最终去重，基于源、目标和关系类型
        WITH entities,
             [link IN all_links | 
              link.source + '_' + link.target + '_' + link.relType
             ] AS link_keys,
             all_links
        
        // 只保留唯一的关系
        WITH entities,
             [i IN RANGE(0, size(all_links)-1) WHERE 
              i = REDUCE(min_i = i, j IN RANGE(0, size(all_links)-1) |
                   CASE WHEN link_keys[j] = link_keys[i] AND j < min_i
                        THEN j ELSE min_i END)
             | all_links[i]
             ] AS unique_links
             
        // 收集结果
        RETURN 
        [e IN entities | {
            id: e.id,
            label: e.id,
            description: CASE WHEN e.description IS NULL THEN '' ELSE e.description END,
            group: CASE 
                WHEN [lbl IN labels(e) WHERE lbl <> '__Entity__'] <> []
                THEN [lbl IN labels(e) WHERE lbl <> '__Entity__'][0]
                ELSE 'Unknown'
            END
        }] AS nodes,
        [link IN unique_links | {
            source: link.source,
            target: link.target,
            label: link.label,
            weight: link.weight
        }] AS links
        """
        
        result = driver.execute_query(query, {"chunk_ids": chunk_ids})
        
        if not result.records or len(result.records) == 0:
            print("从文本块查询结果为空")
            return {"nodes": [], "links": []}
            
        record = result.records[0]
        nodes = record.get("nodes", [])
        links = record.get("links", [])
        print(f"从文本块查询结果: {len(nodes)} 个节点, {len(links)} 个连接")

        node_ids = {node.get("id") for node in nodes if isinstance(node, dict)}
        focus_map = {}
        for chunk_id in chunk_ids:
            chunk_entities = get_entities_from_chunk(chunk_id)
            matched_entities = [entity_id for entity_id in chunk_entities if entity_id in node_ids]
            if matched_entities:
                focus_map[chunk_id] = matched_entities
        
        return {
            "nodes": nodes,
            "links": links,
            "focus_map": focus_map,
        }
        
    except Exception as e:
        print(f"从文本块获取知识图谱失败: {str(e)}")
        return {"nodes": [], "links": []}


def get_graph_from_relationships(relationship_ids: List[Any]) -> Dict:
    """
    根据关系 ID 获取相关实体和边。

    说明：
        这里的关系 ID 来自回答中的 Relationships 引用，优先尝试匹配 `r.id`，
        兼容部分图中关系 ID 存为数值或字符串的情况。
    """
    try:
        if not relationship_ids:
            return {"nodes": [], "links": [], "focus_map": {}}

        normalized_ids = [_parse_numeric_or_string(str(rel_id)) for rel_id in relationship_ids]
        query = """
        UNWIND $relationship_ids AS rel_id
        MATCH (source:__Entity__)-[r]-(target:__Entity__)
        WHERE r.id = rel_id
           OR toString(r.id) = toString(rel_id)
           OR toString(id(r)) = toString(rel_id)
        RETURN DISTINCT
            rel_id AS rel_id,
            source.id AS source_id,
            target.id AS target_id,
            type(r) AS relation_type,
            CASE WHEN r.weight IS NULL THEN 1 ELSE r.weight END AS weight,
            source.description AS source_description,
            target.description AS target_description
        """
        result = driver.execute_query(query, {"relationship_ids": normalized_ids})

        if not result.records:
            return {"nodes": [], "links": [], "focus_map": {}}

        nodes = []
        links = []
        node_map = {}
        focus_map: Dict[str, List[str]] = {}

        for record in result.records:
            source_id = record.get("source_id")
            target_id = record.get("target_id")
            relation_type = record.get("relation_type")
            rel_id = str(record.get("rel_id"))

            if source_id and source_id not in node_map:
                node_data = {
                    "id": source_id,
                    "label": source_id,
                    "description": record.get("source_description", "") or "",
                    "group": "RelationshipSource",
                }
                node_map[source_id] = node_data
                nodes.append(node_data)

            if target_id and target_id not in node_map:
                node_data = {
                    "id": target_id,
                    "label": target_id,
                    "description": record.get("target_description", "") or "",
                    "group": "RelationshipTarget",
                }
                node_map[target_id] = node_data
                nodes.append(node_data)

            if source_id and target_id and relation_type:
                links.append({
                    "source": source_id,
                    "target": target_id,
                    "label": relation_type,
                    "weight": record.get("weight", 1),
                })

            focus_map[rel_id] = [node_id for node_id in [source_id, target_id] if node_id]

        return {"nodes": nodes, "links": links, "focus_map": focus_map}
    except Exception as e:
        print(f"根据关系ID获取图谱失败: {str(e)}")
        return {"nodes": [], "links": [], "focus_map": {}}


def get_graph_from_reports(report_ids: List[Any]) -> Dict:
    """
    根据报告/社区引用获取相关图谱。

    说明：
        Reports 在现有问答中通常代表社区级摘要引用，这里尝试按社区节点 ID、
        字符串形式或 community_rank 进行匹配，并展开到所属实体。
    """
    try:
        if not report_ids:
            return {"nodes": [], "links": [], "focus_map": {}}

        normalized_ids = [_parse_numeric_or_string(str(report_id)) for report_id in report_ids]
        query = """
        UNWIND $report_ids AS report_id
        MATCH (c:__Community__)
        WHERE c.id = report_id
           OR toString(c.id) = toString(report_id)
           OR toString(c.community_rank) = toString(report_id)
        OPTIONAL MATCH (entity:__Entity__)-[:IN_COMMUNITY]->(c)
        RETURN report_id,
               c.id AS community_id,
               c.summary AS community_summary,
               collect(DISTINCT entity.id) AS entity_ids,
               collect(DISTINCT entity.description) AS entity_descriptions
        """
        result = driver.execute_query(query, {"report_ids": normalized_ids})

        if not result.records:
            return {"nodes": [], "links": [], "focus_map": {}}

        community_nodes = []
        community_links = []
        focus_map: Dict[str, List[str]] = {}
        entity_ids: List[Any] = []

        for record in result.records:
            community_id = record.get("community_id")
            report_id = str(record.get("report_id"))
            member_entities = [entity_id for entity_id in record.get("entity_ids", []) if entity_id]

            if community_id:
                community_nodes.append({
                    "id": f"Community:{community_id}",
                    "label": f"Community:{community_id}",
                    "description": record.get("community_summary", "") or "",
                    "group": "Report",
                })
                for entity_id in member_entities:
                    community_links.append({
                        "source": f"Community:{community_id}",
                        "target": entity_id,
                        "label": "IN_COMMUNITY",
                        "weight": 1,
                    })
                focus_map[report_id] = [f"Community:{community_id}"] + member_entities
                entity_ids.extend(member_entities)

        entity_graph = get_knowledge_graph_for_ids(entity_ids=_deduplicate_ids(entity_ids))
        return _merge_graph_parts(
            {"nodes": community_nodes, "links": community_links, "focus_map": focus_map},
            entity_graph,
        )
    except Exception as e:
        print(f"根据报告ID获取图谱失败: {str(e)}")
        return {"nodes": [], "links": [], "focus_map": {}}


def get_knowledge_graph_for_ids(entity_ids=None, relationship_ids=None, chunk_ids=None, report_ids=None) -> Dict:
    """
    根据ID获取知识图谱数据
    
    Args:
        entity_ids: 实体ID列表(可选)
        relationship_ids: 关系ID列表(可选)
        chunk_ids: 文本块ID列表(可选)
        report_ids: 报告/社区引用ID列表(可选)
    
    Returns:
        Dict: 知识图谱数据，包含节点和连接
    """
    try:
        # 确保所有参数都有默认值，避免None
        entity_ids = entity_ids or []
        relationship_ids = relationship_ids or []
        chunk_ids = chunk_ids or []
        report_ids = report_ids or []
        
        # 如果提供了文本块ID，但没有实体ID，尝试从文本块获取实体
        if chunk_ids and not entity_ids:
            for chunk_id in chunk_ids:
                chunk_entities = get_entities_from_chunk(chunk_id)
                entity_ids.extend(chunk_entities)
            
            # 去重
            entity_ids = list(set(entity_ids))
        
        if not entity_ids and not chunk_ids and not relationship_ids and not report_ids:
            return {"nodes": [], "links": []}

        graph_parts = []

        # 先展开关系引用和报告引用，补充实体上下文。
        if relationship_ids:
            relationship_graph = get_graph_from_relationships(relationship_ids)
            graph_parts.append(relationship_graph)

            # 将关系端点并入实体ID，便于后续一跳扩展。
            for node_ids in relationship_graph.get("focus_map", {}).values():
                entity_ids.extend(node_ids)

        if report_ids:
            report_graph = get_graph_from_reports(report_ids)
            graph_parts.append(report_graph)

            for node_ids in report_graph.get("focus_map", {}).values():
                for node_id in node_ids:
                    if isinstance(node_id, str) and node_id.startswith("Community:"):
                        continue
                    entity_ids.append(node_id)

        # 检查实体ID是否存在
        verified_entity_ids = check_entity_existence(_deduplicate_ids(entity_ids))
        if not verified_entity_ids:
            # 尝试直接使用文本块查询
            if chunk_ids:
                graph_parts.append(get_graph_from_chunks(chunk_ids))
                return _merge_graph_parts(*graph_parts)
            return _merge_graph_parts(*graph_parts)
        
        # 使用确认存在的实体ID进行查询
        params = {
            "entity_ids": verified_entity_ids,
            "max_distance": 1
        }
        
        # 局部查询的Cypher
        query = """
        // 匹配指定的实体ID
        MATCH (e:__Entity__)
        WHERE e.id IN $entity_ids
        
        // 收集基础实体
        WITH collect(e) AS base_entities
        
        // 匹配实体之间的关系，只处理每对实体一次
        UNWIND base_entities AS e1
        UNWIND base_entities AS e2
        // 确保只处理每对实体一次
        WITH base_entities, e1, e2 
        WHERE e1.id < e2.id
        OPTIONAL MATCH (e1)-[r]-(e2)
        
        // 收集关系
        WITH base_entities, e1, e2, collect(r) AS rels
        
        // 获取一跳邻居，排除已经处理过的实体对
        UNWIND base_entities AS base_entity
        OPTIONAL MATCH (base_entity)-[r1]-(neighbor:__Entity__)
        WHERE NOT neighbor IN base_entities
        
        // 收集所有实体和关系
        WITH base_entities, 
             collect(DISTINCT {source: e1.id, target: e2.id, rels: rels}) AS internal_rels,
             collect(DISTINCT neighbor) AS neighbors,
             collect(DISTINCT {source: base_entity.id, target: neighbor.id, rel: r1}) AS external_rels
        
        // 合并所有实体
        WITH base_entities + neighbors AS all_entities, 
             internal_rels, external_rels
        
        // 构建去重的内部关系
        WITH all_entities,
             [rel IN internal_rels WHERE size(rel.rels) > 0 |
              // 为每种类型的关系创建一个唯一记录
              [r IN rel.rels | {
                source: rel.source,
                target: rel.target,
                label: type(r),
                relType: type(r),
                weight: CASE WHEN r.weight IS NULL THEN 1 ELSE r.weight END
              }]
             ] AS internal_links_nested,
             
             // 构建去重的外部关系
             [rel IN external_rels WHERE rel.rel IS NOT NULL |
              {
                source: rel.source,
                target: rel.target,
                label: type(rel.rel),
                relType: type(rel.rel),
                weight: CASE WHEN rel.rel.weight IS NULL THEN 1 ELSE rel.rel.weight END
              }
             ] AS external_links
        
        // 扁平化内部关系并合并
        WITH all_entities,
             [link IN external_links | link] + 
             [link IN REDUCE(acc = [], list IN internal_links_nested | acc + list) | link]
             AS all_links_raw
        
        // 最终去重，基于源、目标和关系类型
        WITH all_entities,
             [link IN all_links_raw | 
              link.source + '_' + link.target + '_' + link.relType
             ] AS link_keys,
             all_links_raw
        
        // 只保留唯一的关系
        WITH all_entities,
             [i IN RANGE(0, size(all_links_raw)-1) WHERE 
              i = REDUCE(min_i = i, j IN RANGE(0, size(all_links_raw)-1) |
                   CASE WHEN link_keys[j] = link_keys[i] AND j < min_i
                        THEN j ELSE min_i END)
             | all_links_raw[i]
             ] AS unique_links
        
        // 返回结果
        RETURN 
        [n IN all_entities | {
            id: n.id, 
            label: CASE WHEN n.id IS NULL THEN "未知" ELSE n.id END, 
            description: CASE WHEN n.description IS NULL THEN '' ELSE n.description END,
            group: CASE 
                WHEN [lbl IN labels(n) WHERE lbl <> '__Entity__'] <> []
                THEN [lbl IN labels(n) WHERE lbl <> '__Entity__'][0]
                ELSE 'Unknown'
            END
        }] AS nodes,
        [link IN unique_links | {
            source: link.source,
            target: link.target,
            label: link.label,
            weight: link.weight
        }] AS links
        """
        
        # 执行查询
        result = driver.execute_query(query, params)
        
        if not result.records or len(result.records) == 0:
            # 尝试直接使用文本块查询
            if chunk_ids:
                return get_graph_from_chunks(chunk_ids)
            return {"nodes": [], "links": []}
            
        record = result.records[0]
        nodes = record.get("nodes", [])
        links = record.get("links", [])
        node_ids = {node.get("id") for node in nodes if isinstance(node, dict)}
        focus_map = {}

        # 为证据定位保留证据到实体节点的映射，前端可据此自动聚焦。
        for entity_id in verified_entity_ids:
            if entity_id in node_ids:
                focus_map[str(entity_id)] = [entity_id]

        for chunk_id in chunk_ids:
            chunk_entities = get_entities_from_chunk(chunk_id)
            matched_entities = [entity_id for entity_id in chunk_entities if entity_id in node_ids]
            if matched_entities:
                focus_map[chunk_id] = matched_entities
        
        graph_parts.append({
            "nodes": nodes,
            "links": links,
            "focus_map": focus_map,
        })

        if chunk_ids:
            graph_parts.append(get_graph_from_chunks(chunk_ids))

        return _merge_graph_parts(*graph_parts)
        
    except Exception as e:
        print(f"获取知识图谱失败: {str(e)}")
        
        # 尝试直接使用文本块查询
        if chunk_ids:
            graph_parts.append(get_graph_from_chunks(chunk_ids))
            return _merge_graph_parts(*graph_parts)
        return _merge_graph_parts(*graph_parts)


def get_knowledge_graph(limit: int = 100, query: str = None) -> Dict:
    """
    获取知识图谱数据
    
    Args:
        limit: 节点数量限制
        query: 查询条件(可选)
    
    Returns:
        Dict: 知识图谱数据，包含节点和连接
    """
    try:
        # 确保limit是整数
        limit = int(limit) if limit else 100
        
        # 构建查询条件
        query_conditions = ""
        params = {"limit": limit}
        
        if query:
            query_conditions = """
            WHERE n.id CONTAINS $query OR 
                  n.description CONTAINS $query
            """
            params["query"] = query
        else:
            query_conditions = ""
            
        # 构建节点查询 - 动态获取节点类型
        node_query = f"""
        // 获取实体
        MATCH (n:__Entity__)
        {query_conditions}
        WITH n LIMIT $limit
        
        // 收集所有实体
        WITH collect(n) AS entities
        
        // 获取实体间的关系
        CALL {{
            WITH entities
            MATCH (e1:__Entity__)-[r]-(e2:__Entity__)
            WHERE e1 IN entities AND e2 IN entities
                AND e1.id < e2.id  // 避免重复关系
            RETURN collect(r) AS relationships
        }}
        
        // 返回结果
        RETURN 
        [entity IN entities | {{
            id: entity.id,
            label: entity.id,
            description: entity.description,
            // 动态使用实体标签作为组
            group: CASE 
                WHEN [lbl IN labels(entity) WHERE lbl <> '__Entity__'] <> []
                THEN [lbl IN labels(entity) WHERE lbl <> '__Entity__'][0]
                ELSE 'Unknown'
            END
        }}] AS nodes,
        [r IN relationships | {{
            source: startNode(r).id,
            target: endNode(r).id,
            label: type(r),
            weight: CASE WHEN r.weight IS NOT NULL THEN r.weight ELSE 1 END
        }}] AS links
        """
        
        result = driver.execute_query(node_query, params)
        
        if not result or not result.records:
            return {"nodes": [], "links": []}
            
        record = result.records[0]
        
        # 处理可能的None值
        nodes = record["nodes"] or []
        links = record["links"] or []
        
        # 返回标准格式
        return {
            "nodes": nodes,
            "links": links
        }
        
    except Exception as e:
        print(f"获取知识图谱数据失败: {str(e)}")
        return {"error": str(e), "nodes": [], "links": []}

def get_source_content(source_id: str) -> Dict[str, Any]:
    """
    根据源ID获取内容
    
    Args:
        source_id: 源ID
        
    Returns:
        Dict[str, Any]: 结构化源内容
    """
    try:
        if not source_id:
            return {
                "source_id": source_id,
                "source_type": "unknown",
                "content": "未提供有效的源ID",
                "error": "未提供有效的源ID",
            }
        
        # 检查ID是否为Chunk ID (直接使用)
        if len(source_id) == 40:  # SHA1哈希的长度
            query = """
            MATCH (n:__Chunk__) 
            WHERE n.id = $id 
            RETURN n.fileName AS fileName, n.text AS text,
                   n.position AS position, n.length AS length,
                   n.content_offset AS content_offset, n.id AS chunk_id
            """
            params = {"id": source_id}
            source_type = "chunk"
        else:
            # 尝试解析复合ID
            id_parts = source_id.split(",")
            
            if len(id_parts) >= 2 and id_parts[0] == "2":  # 文本块查询
                query = """
                MATCH (n:__Chunk__) 
                WHERE n.id = $id 
                RETURN n.fileName AS fileName, n.text AS text,
                       n.position AS position, n.length AS length,
                       n.content_offset AS content_offset, n.id AS chunk_id
                """
                params = {"id": id_parts[-1]}
                source_type = "chunk"
            else:  # 社区查询
                query = """
                MATCH (n:__Community__) 
                WHERE n.id = $id 
                RETURN n.id AS community_id, n.summary AS summary, n.full_content AS full_content
                """
                params = {"id": id_parts[1] if len(id_parts) > 1 else source_id}
                source_type = "community"
        
        from neo4j import Result
        result = driver.execute_query(
            query,
            params,
            result_transformer_=Result.to_df
        )
        
        if result is not None and result.shape[0] > 0:
            if "text" in result.columns:
                row = result.iloc[0]
                file_name = row.get("fileName")
                text = row.get("text") or ""
                position = row.get("position")
                length = row.get("length")
                content_offset = row.get("content_offset")
                chunk_id = row.get("chunk_id")
                title = f"文本块原文 · {file_name or '未知文件'}"
                meta_lines = [f"文件名: {file_name or '未知文件'}"]
                if position is not None:
                    meta_lines.append(f"块序号: {position}")
                if length is not None:
                    meta_lines.append(f"长度: {length}")
                if content_offset is not None:
                    meta_lines.append(f"偏移量: {content_offset}")

                return {
                    "source_id": source_id,
                    "source_type": source_type,
                    "title": title,
                    "file_name": file_name,
                    "chunk_id": chunk_id,
                    "text": text,
                    "position": int(position) if position is not None else None,
                    "length": int(length) if length is not None else None,
                    "content_offset": int(content_offset) if content_offset is not None else None,
                    "content": "\n".join(meta_lines) + "\n\n" + str(text),
                }
            else:
                row = result.iloc[0]
                summary = row.get("summary") or ""
                full_content = row.get("full_content") or ""
                community_id = row.get("community_id")
                title = f"社区原文 · {community_id or source_id}"
                return {
                    "source_id": source_id,
                    "source_type": source_type,
                    "title": title,
                    "community_id": str(community_id or ""),
                    "summary": str(summary),
                    "full_content": str(full_content),
                    "content": f"摘要:\n{summary}\n\n全文:\n{full_content}",
                }

        return {
            "source_id": source_id,
            "source_type": source_type,
            "content": f"未找到相关内容: 源ID {source_id}",
            "error": "未找到相关内容",
        }
    except Exception as e:
        print(f"获取源内容时出错: {str(e)}")
        return {
            "source_id": source_id,
            "source_type": "unknown",
            "content": f"检索源内容时发生错误: {str(e)}",
            "error": str(e),
        }
    

def get_source_file_info(source_id: str) -> dict:
    """
    获取源ID对应的文件信息
    
    Args:
        source_id: 源ID
        
    Returns:
        Dict: 包含文件名等信息的字典
    """
    try:
        if not source_id:
            return {"file_name": "未知文件"}
        
        # 检查ID是否为Chunk ID (直接使用)
        if len(source_id) == 40:  # SHA1哈希的长度
            query = """
            MATCH (n:__Chunk__) 
            WHERE n.id = $id 
            RETURN n.fileName AS fileName
            """
            params = {"id": source_id}
        else:
            # 尝试解析复合ID
            id_parts = source_id.split(",")
            
            if len(id_parts) >= 2 and id_parts[0] == "2":  # 文本块查询
                query = """
                MATCH (n:__Chunk__) 
                WHERE n.id = $id 
                RETURN n.fileName AS fileName
                """
                params = {"id": id_parts[-1]}
            else:  # 社区查询
                query = """
                MATCH (n:__Community__) 
                WHERE n.id = $id 
                RETURN "社区摘要" AS fileName
                """
                params = {"id": id_parts[1] if len(id_parts) > 1 else source_id}
        
        from neo4j import Result
        result = driver.execute_query(
            query,
            params,
            result_transformer_=Result.to_df
        )
        
        if result is not None and result.shape[0] > 0 and "fileName" in result.columns:
            file_name = result.iloc[0]['fileName']
            # 获取文件名的基本名称（不含路径）
            import os
            base_name = os.path.basename(file_name) if file_name else "未知文件"
            return {"file_name": base_name}
        else:
            return {"file_name": f"源文本 {source_id}"}
            
    except Exception as e:
        print(f"获取源文件信息时出错: {str(e)}")
        return {"file_name": f"源文本 {source_id}"}


def get_chunks(limit: int = 10, offset: int = 0):
    """
    获取数据库中的文本块
    
    Args:
        limit: 返回数量限制
        offset: 偏移量
        
    Returns:
        Dict: 文本块数据和总数
    """
    try:
        query = """
        MATCH (c:__Chunk__)
        RETURN c.id AS id, c.fileName AS fileName, c.text AS text
        ORDER BY c.fileName, c.id
        SKIP $offset
        LIMIT $limit
        """
        
        from neo4j import Result
        result = driver.execute_query(
            query, 
            parameters={"limit": int(limit), "offset": int(offset)},
            result_transformer_=Result.to_df
        )
        
        if result is not None and not result.empty:
            chunks = result.to_dict(orient='records')
            return {"chunks": chunks, "total": len(chunks)}
        else:
            return {"chunks": [], "total": 0}
            
    except Exception as e:
        print(f"获取文本块失败: {str(e)}")
        return {"error": str(e), "chunks": []}
    

def get_shortest_path(driver, entity_a, entity_b, max_hops=3):
    """查询实体A和实体B之间的最短路径"""
    try:
        # 根据max_hops构建相应的路径模式
        if max_hops == 1:
            path_pattern = "[*..1]"
        elif max_hops == 2:
            path_pattern = "[*..2]"
        elif max_hops == 3:
            path_pattern = "[*..3]"
        elif max_hops == 4:
            path_pattern = "[*..4]"
        elif max_hops >= 5:
            path_pattern = "[*..5]"
        else:
            path_pattern = "[*..3]"
        
        query = f"""
        MATCH (a:__Entity__), (b:__Entity__)
        WHERE a.id = $entity_a AND b.id = $entity_b
        MATCH p = shortestPath((a)-{path_pattern}-(b))
        RETURN p
        """
        
        result = driver.execute_query(query, {
            "entity_a": entity_a,
            "entity_b": entity_b
        })
        
        # 转换结果为可视化格式
        nodes = []
        links = []
        node_ids = set()
        path_info = f"从 {entity_a} 到 {entity_b} 的最短路径"
        path_length = 0
        
        if result.records and len(result.records) > 0:
            path = result.records[0].get("p")
            if path:
                # 处理节点
                for node in path.nodes:
                    node_id = node.get("id")
                    if node_id not in node_ids:
                        node_ids.add(node_id)
                        group = [label for label in node.labels if label != "__Entity__"]
                        group = group[0] if group else "Unknown"
                        
                        nodes.append({
                            "id": node_id,
                            "label": node_id,
                            "description": node.get("description", ""),
                            "group": group
                        })
                
                # 处理关系
                for rel in path.relationships:
                    links.append({
                        "source": rel.start_node.get("id"),
                        "target": rel.end_node.get("id"),
                        "label": rel.type,
                        "weight": 1
                    })
                    path_length += 1
        
        return {
            "nodes": nodes,
            "links": links,
            "path_info": path_info,
            "path_length": path_length
        }
        
    except Exception as e:
        print(f"获取最短路径失败: {str(e)}")
        return {"nodes": [], "links": [], "error": str(e)}

def get_one_two_hop_paths(driver, entity_a, entity_b):
    """
    获取实体A到实体B的一到两步关系路径
    """
    try:
        query = """
        MATCH p = (a:__Entity__)-[*1..2]-(b:__Entity__)
        WHERE a.id = $entity_a AND b.id = $entity_b
        RETURN p
        """
        
        result = driver.execute_query(query, {
            "entity_a": entity_a,
            "entity_b": entity_b
        })
        
        # 转换结果为可视化格式
        nodes = []
        links = []
        paths_info = []
        node_map = {}
        link_map = {}
        
        for record in result.records:
            path = record.get("p")
            if path:
                path_desc = []
                
                # 处理节点
                for node in path.nodes:
                    node_id = node.get("id")
                    if node_id not in node_map:
                        group = [label for label in node.labels if label != "__Entity__"]
                        group = group[0] if group else "Unknown"
                        
                        node_data = {
                            "id": node_id,
                            "label": node_id,
                            "description": node.get("description", ""),
                            "group": group
                        }
                        nodes.append(node_data)
                        node_map[node_id] = node_data
                
                # 处理关系并构建路径描述
                prev_node = None
                for i, node in enumerate(path.nodes):
                    current_id = node.get("id")
                    if prev_node:
                        # 找到这两个节点之间的关系
                        for rel in path.relationships:
                            start_id = rel.start_node.get("id")
                            end_id = rel.end_node.get("id")
                            if (start_id == prev_node and end_id == current_id) or \
                               (start_id == current_id and end_id == prev_node):
                                
                                link_key = f"{start_id}_{end_id}_{rel.type}"
                                if link_key not in link_map:
                                    link_data = {
                                        "source": start_id,
                                        "target": end_id,
                                        "label": rel.type,
                                        "weight": 1
                                    }
                                    links.append(link_data)
                                    link_map[link_key] = link_data
                                
                                # 添加到路径描述
                                path_desc.append(f"{prev_node} -[{rel.type}]-> {current_id}")
                    
                    prev_node = current_id
                
                # 添加完整路径描述
                if path_desc:
                    path_str = " ".join(path_desc)
                    if path_str not in paths_info:
                        paths_info.append(path_str)
        
        return {
            "nodes": nodes,
            "links": links,
            "paths_info": paths_info,
            "path_count": len(paths_info)
        }
        
    except Exception as e:
        print(f"获取一到两跳路径失败: {str(e)}")
        return {"nodes": [], "links": [], "error": str(e)}

def get_common_neighbors(driver, entity_a, entity_b):
    """
    找出与实体A和实体B相关联的实体（共同邻居）
    """
    try:
        query = """
        MATCH (a:__Entity__ {id: $entity_a})--(x)--(b:__Entity__ {id: $entity_b})
        RETURN DISTINCT x
        """
        
        result = driver.execute_query(query, {
            "entity_a": entity_a,
            "entity_b": entity_b
        })
        
        # 转换结果为可视化格式
        nodes = []
        links = []
        common_neighbors = []
        node_ids = {entity_a, entity_b}
        
        # 首先添加A和B节点
        a_node = {"id": entity_a, "label": entity_a, "group": "Source", "description": ""}
        b_node = {"id": entity_b, "label": entity_b, "group": "Target", "description": ""}
        nodes.append(a_node)
        nodes.append(b_node)
        
        # 处理共同邻居
        for record in result.records:
            neighbor = record.get("x")
            if neighbor:
                neighbor_id = neighbor.get("id")
                common_neighbors.append(neighbor_id)
                
                if neighbor_id not in node_ids:
                    node_ids.add(neighbor_id)
                    group = [label for label in neighbor.labels if label != "__Entity__"]
                    group = group[0] if group else "Common"
                    
                    # 添加邻居节点
                    nodes.append({
                        "id": neighbor_id,
                        "label": neighbor_id,
                        "description": neighbor.get("description", ""),
                        "group": group
                    })
                
                # 添加到A和B的连接
                links.append({
                    "source": entity_a,
                    "target": neighbor_id,
                    "label": "连接",
                    "weight": 1
                })
                
                links.append({
                    "source": neighbor_id,
                    "target": entity_b,
                    "label": "连接",
                    "weight": 1
                })
        
        return {
            "nodes": nodes,
            "links": links,
            "common_neighbors": common_neighbors,
            "neighbor_count": len(common_neighbors)
        }
        
    except Exception as e:
        print(f"获取共同邻居失败: {str(e)}")
        return {"nodes": [], "links": [], "error": str(e)}

def get_all_paths(driver, entity_a, entity_b, max_depth=3):
    """查询两个实体之间的所有路径（有深度限制）"""
    try: 
        # 验证实体存在性
        check_query = """
        MATCH (a:__Entity__), (b:__Entity__)
        WHERE a.id = $entity_a AND b.id = $entity_b
        RETURN a.id AS id_a, b.id AS id_b
        """
        
        check_result = driver.execute_query(check_query, {
            "entity_a": entity_a,
            "entity_b": entity_b
        })
        
        if not check_result.records or len(check_result.records) == 0:
            return {
                "error": f"实体 '{entity_a}' 或 '{entity_b}' 不存在",
                "nodes": [],
                "links": []
            }
        
        # 根据max_depth的值构建不同的查询
        # Neo4j不允许在路径模式[*1..n]中使用参数，所以我们需要动态构建查询
        if max_depth == 1:
            path_pattern = "[*1..1]"
        elif max_depth == 2:
            path_pattern = "[*1..2]"
        elif max_depth == 3:
            path_pattern = "[*1..3]"
        elif max_depth == 4:
            path_pattern = "[*1..4]"
        elif max_depth >= 5:
            path_pattern = "[*1..5]"  # 限制最大深度为5
        else:
            path_pattern = "[*1..3]"  # 默认值
            
        query = f"""
        MATCH p = (a:__Entity__)-{path_pattern}-(b:__Entity__)
        WHERE a.id = $entity_a AND b.id = $entity_b
        RETURN p
        LIMIT 10
        """
        
        print(f"执行查询: {query}")
        result = driver.execute_query(query, {
            "entity_a": entity_a,
            "entity_b": entity_b
        })
        
        # 转换结果为可视化格式
        nodes = []
        links = []
        paths_info = []
        node_map = {}
        link_map = {}
        
        for record in result.records:
            path = record.get("p")
            if path:
                path_desc = []
                
                # 处理节点
                for node in path.nodes:
                    node_id = node.get("id")
                    if node_id not in node_map:
                        group = [label for label in node.labels if label != "__Entity__"]
                        group = group[0] if group else "Unknown"
                        
                        node_data = {
                            "id": node_id,
                            "label": node_id,
                            "description": node.get("description", ""),
                            "group": group
                        }
                        nodes.append(node_data)
                        node_map[node_id] = node_data
                
                # 处理关系并构建路径描述
                path_rels = []
                for rel in path.relationships:
                    start_id = rel.start_node.get("id")
                    end_id = rel.end_node.get("id")
                    
                    link_key = f"{start_id}_{end_id}_{rel.type}"
                    if link_key not in link_map:
                        link_data = {
                            "source": start_id,
                            "target": end_id,
                            "label": rel.type,
                            "weight": 1
                        }
                        links.append(link_data)
                        link_map[link_key] = link_data
                    
                    path_rels.append((start_id, rel.type, end_id))
                
                # 构建路径描述
                if path_rels:
                    path_str = " -> ".join([f"{start} -[{rel}]-> {end}" for start, rel, end in path_rels])
                    if path_str not in paths_info:
                        paths_info.append(path_str)
        
        return {
            "nodes": nodes,
            "links": links,
            "paths_info": paths_info,
            "path_count": len(paths_info)
        }
    except Exception as e:
        print(f"获取所有路径失败: {str(e)}")
        return {"nodes": [], "links": [], "error": str(e)}

def get_entity_cycles(driver, entity_id, max_depth=4):
    """查找实体的环路"""
    try:
        # 根据max_depth构建适当的路径模式
        if max_depth == 1:
            path_pattern = "[*1..1]"
        elif max_depth == 2:
            path_pattern = "[*1..2]"
        elif max_depth == 3:
            path_pattern = "[*1..3]"
        elif max_depth == 4:
            path_pattern = "[*1..4]"
        else:
            path_pattern = "[*1..4]"  # 限制最大为4，防止查询过于复杂
        
        query = f"""
        MATCH p = (a:__Entity__)-{path_pattern}->(a)
        WHERE a.id = $entity_id
        RETURN p
        LIMIT 10
        """
        
        result = driver.execute_query(query, {
            "entity_id": entity_id
        })
        
        nodes = []
        links = []
        cycles_info = []
        node_map = {}
        link_map = {}
        
        for record in result.records:
            path = record.get("p")
            if path:
                cycle_desc = []
                
                # 处理节点
                for node in path.nodes:
                    node_id = node.get("id")
                    if node_id not in node_map:
                        group = [label for label in node.labels if label != "__Entity__"]
                        group = group[0] if group else "Unknown"
                        
                        node_data = {
                            "id": node_id,
                            "label": node_id,
                            "description": node.get("description", ""),
                            "group": group
                        }
                        nodes.append(node_data)
                        node_map[node_id] = node_data
                
                # 处理关系并构建环路描述
                cycle_rels = []
                for rel in path.relationships:
                    start_id = rel.start_node.get("id")
                    end_id = rel.end_node.get("id")
                    
                    link_key = f"{start_id}_{end_id}_{rel.type}"
                    if link_key not in link_map:
                        link_data = {
                            "source": start_id,
                            "target": end_id,
                            "label": rel.type,
                            "weight": 1
                        }
                        links.append(link_data)
                        link_map[link_key] = link_data
                    
                    cycle_rels.append((start_id, rel.type, end_id))
                
                # 构建环路描述
                if cycle_rels:
                    cycle_str = " -> ".join([f"{start} -[{rel}]-> {end}" for start, rel, end in cycle_rels])
                    cycle_length = len(cycle_rels)
                    cycle_info = {
                        "description": cycle_str,
                        "length": cycle_length
                    }
                    if cycle_str not in [c["description"] for c in cycles_info]:
                        cycles_info.append(cycle_info)
        
        return {
            "nodes": nodes,
            "links": links,
            "cycles_info": cycles_info,
            "cycle_count": len(cycles_info)
        }
    except Exception as e:
        print(f"查找环路失败: {str(e)}")
        return {"nodes": [], "links": [], "error": str(e)}

def get_entity_influence(driver, entity_id, max_depth=2):
    """分析实体的影响范围"""
    try:
        # 根据max_depth构建路径模式
        if max_depth == 1:
            path_pattern = "[*1..1]"
        elif max_depth == 2:
            path_pattern = "[*1..2]"
        elif max_depth == 3:
            path_pattern = "[*1..3]"
        else:
            path_pattern = "[*1..2]"  # 默认值
        
        query = f"""
        MATCH p = (a:__Entity__)-{path_pattern}-(b:__Entity__)
        WHERE a.id = $entity_id
        RETURN p
        LIMIT 100
        """
        
        result = driver.execute_query(query, {
            "entity_id": entity_id
        })

        nodes = []
        links = []
        node_map = {}
        link_map = {}
        direct_connections = set()
        connection_types = {}
        
        # 首先添加中心实体
        center_node = {
            "id": entity_id,
            "label": entity_id,
            "description": "",
            "group": "Center"
        }
        nodes.append(center_node)
        node_map[entity_id] = center_node
        
        for record in result.records:
            path = record.get("p")
            if path:
                # 处理节点
                for node in path.nodes:
                    node_id = node.get("id")
                    if node_id != entity_id and node_id not in node_map:
                        group = [label for label in node.labels if label != "__Entity__"]
                        group = group[0] if group else "Unknown"
                        
                        # 根据与中心实体的距离设置不同的组
                        for i, path_node in enumerate(path.nodes):
                            if path_node.get("id") == node_id:
                                # 计算到中心节点的距离
                                if i == 1 or i == len(path.nodes) - 2:  # 直接相邻
                                    group = "Level1"
                                    direct_connections.add(node_id)
                                else:
                                    group = f"Level{min(i, len(path.nodes) - i - 1)}"
                                break
                        
                        node_data = {
                            "id": node_id,
                            "label": node_id,
                            "description": node.get("description", ""),
                            "group": group
                        }
                        nodes.append(node_data)
                        node_map[node_id] = node_data
                
                # 处理关系
                for rel in path.relationships:
                    start_id = rel.start_node.get("id")
                    end_id = rel.end_node.get("id")
                    rel_type = rel.type
                    
                    # 统计关系类型
                    if rel_type not in connection_types:
                        connection_types[rel_type] = 0
                    connection_types[rel_type] += 1
                    
                    link_key = f"{start_id}_{end_id}_{rel_type}"
                    if link_key not in link_map:
                        link_data = {
                            "source": start_id,
                            "target": end_id,
                            "label": rel_type,
                            "weight": 1
                        }
                        links.append(link_data)
                        link_map[link_key] = link_data
        
        # 构建返回结果
        influence_stats = {
            "direct_connections": len(direct_connections),
            "total_connections": len(nodes) - 1,  # 减去中心节点自身
            "connection_types": [{"type": k, "count": v} for k, v in connection_types.items()],
            "relation_distribution": connection_types
        }
        
        return {
            "nodes": nodes,
            "links": links,
            "influence_stats": influence_stats
        }
    except Exception as e:
        print(f"分析实体影响范围失败: {str(e)}")
        return {"nodes": [], "links": [], "error": str(e)}

def get_simplified_community(driver, entity_id, max_depth=2):
    """使用简化的方法获取实体所属社区"""
    try:
        # 验证实体存在性
        check_query = """
        MATCH (a:__Entity__)
        WHERE a.id = $entity_id
        RETURN a.id AS id, labels(a) AS labels
        """
        
        check_result = driver.execute_query(check_query, {
            "entity_id": entity_id
        })
        
        # 如果实体不存在，返回错误信息
        if not check_result.records or len(check_result.records) == 0:
            print(f"实体不存在: {entity_id}")
            return {
                "error": f"实体 '{entity_id}' 不存在",
                "nodes": [],
                "links": []
            }
            
        entity_record = check_result.records[0]
        print(f"实体存在: {entity_record['id']}, 标签: {entity_record['labels']}")
        
        # 根据max_depth构建路径模式
        if max_depth == 1:
            path_pattern = "[*0..1]"
        elif max_depth == 2:
            path_pattern = "[*0..2]"
        elif max_depth == 3:
            path_pattern = "[*0..3]"
        else:
            path_pattern = "[*0..2]"  # 默认值
        
        # 获取实体所在的N跳邻居
        neighbors_query = f"""
        MATCH p = (a:__Entity__)-{path_pattern}-(b:__Entity__)
        WHERE a.id = $entity_id
        RETURN DISTINCT b
        LIMIT 100
        """
        
        # 执行查询并处理结果
        neighbors_result = driver.execute_query(neighbors_query, {
            "entity_id": entity_id
        })
        
        print(f"获取到 {len(neighbors_result.records)} 个邻居")
        
        # 提取邻居ID
        entity_ids = []
        nodes = []
        node_map = {}
        
        for record in neighbors_result.records:
            entity = record.get("b")
            if entity:
                # 处理返回的实体数据
                try:
                    node_id = None
                    node_labels = []
                    
                    # 检查是否为节点对象或字典
                    if hasattr(entity, 'get'):  # 字典类型
                        node_id = entity.get("id")
                        # 尝试获取标签，可能存在不同形式
                        if "labels" in entity:
                            node_labels = entity["labels"]
                        elif "_labels" in entity:
                            node_labels = entity["_labels"]
                    elif hasattr(entity, 'id'):  # 节点对象
                        node_id = entity.id
                        if hasattr(entity, 'labels'):
                            node_labels = entity.labels
                    else:
                        # 如果是其他类型，尝试转为字符串
                        node_id = str(entity)
                
                    if node_id and node_id not in node_map:
                        # 从标签中确定组类型
                        group = "Unknown"
                        if isinstance(node_labels, list):
                            non_entity_labels = [lbl for lbl in node_labels if lbl != "__Entity__"]
                            if non_entity_labels:
                                group = non_entity_labels[0]
                        elif isinstance(node_labels, (str, dict)):
                            # 处理其他可能的标签格式
                            group = str(node_labels)
                        
                        # 标记中心实体
                        if node_id == entity_id:
                            group = "Center"
                        
                        # 获取描述，安全方式
                        description = ""
                        if hasattr(entity, 'get'):
                            description = entity.get("description", "")
                        elif hasattr(entity, 'description'):
                            description = entity.description
                        
                        node_data = {
                            "id": node_id,
                            "label": node_id,
                            "description": description,
                            "group": group,
                            "community": None  # 先初始化为None
                        }
                        nodes.append(node_data)
                        node_map[node_id] = node_data
                        entity_ids.append(node_id)
                except Exception as e:
                    print(f"处理节点数据时出错: {e}")
                    continue
        
        # 获取这些邻居之间的关系
        relations_query = """
        MATCH (a:__Entity__)-[r]-(b:__Entity__)
        WHERE a.id IN $entity_ids AND b.id IN $entity_ids AND a.id <> b.id
        RETURN DISTINCT a.id as source, b.id as target, type(r) as rel_type
        LIMIT 500
        """
        
        relations_result = driver.execute_query(relations_query, {
            "entity_ids": entity_ids
        })
        
        print(f"获取到 {len(relations_result.records)} 条关系")
        
        # 提取关系
        links = []
        link_map = {}
        
        for record in relations_result.records:
            source_id = record.get("source")
            target_id = record.get("target") 
            rel_type = record.get("rel_type")
            
            if source_id and target_id and rel_type:
                link_key = f"{source_id}_{target_id}_{rel_type}"
                if link_key not in link_map:
                    link_data = {
                        "source": source_id,
                        "target": target_id,
                        "label": rel_type,
                        "weight": 1
                    }
                    links.append(link_data)
                    link_map[link_key] = link_data
        
        # 使用简单的社区检测模拟
        communities = {}
        node_communities = {}
        
        # 计算节点的邻居集
        neighbors = {}
        for link in links:
            source = link["source"]
            target = link["target"]
            
            if source not in neighbors:
                neighbors[source] = set()
            if target not in neighbors:
                neighbors[target] = set()
                
            neighbors[source].add(target)
            neighbors[target].add(source)
        
        # 分配社区ID（基于连通分量的简单社区检测）
        community_id = 0
        visited = set()
        min_community_size = 2
        
         # 先识别主要社区
        for node_id in entity_ids:
            if node_id not in visited and len(neighbors.get(node_id, [])) >= 1:  # 至少有一个邻居
                # 开始一个新社区
                temp_community = []
                queue = [node_id]
                temp_visited = set([node_id])
                
                while queue:
                    current = queue.pop(0)
                    temp_community.append(current)
                    
                    # 检查邻居
                    for neighbor in neighbors.get(current, []):
                        if neighbor not in temp_visited:
                            temp_visited.add(neighbor)
                            queue.append(neighbor)
                
                # 只有社区大小达到阈值才保留
                if len(temp_community) >= min_community_size:
                    community_id += 1
                    communities[community_id] = temp_community
                    for member in temp_community:
                        node_communities[member] = community_id
                        visited.add(member)
        
        # 处理剩余孤立节点，将它们归入最近的社区或中心实体的社区
        for node_id in entity_ids:
            if node_id not in visited:
                # 如果是中心实体，创建自己的社区
                if node_id == entity_id:
                    community_id += 1
                    communities[community_id] = [node_id]
                    node_communities[node_id] = community_id
                    visited.add(node_id)
                else:
                    # 查找与该节点最相关的社区
                    best_community = None
                    best_score = 0
                    
                    for comm_id, members in communities.items():
                        score = 0
                        for member in members:
                            if member in neighbors.get(node_id, []):
                                score += 1
                        
                        if score > best_score:
                            best_score = score
                            best_community = comm_id
                    
                    # 如果找到相关社区，加入该社区
                    if best_community and best_score > 0:
                        communities[best_community].append(node_id)
                        node_communities[node_id] = best_community
                        visited.add(node_id)
                    # 否则，如果有中心实体社区，加入中心实体社区
                    elif entity_id in node_communities:
                        center_community = node_communities[entity_id]
                        communities[center_community].append(node_id)
                        node_communities[node_id] = center_community
                        visited.add(node_id)
        
        # 更新节点的社区信息
        for node in nodes:
            node_id = node["id"]
            if node_id in node_communities:
                node["community"] = node_communities[node_id]
                # 更新节点组以反映社区
                if node_id != entity_id:  # 保持中心节点的组
                    node["group"] = f"Community{node_communities[node_id]}"
        
        # 汇总社区统计信息
        community_stats = []
        for comm_id, members in communities.items():
            if members:
                is_center_in = entity_id in members
                comm_links = [link for link in links if link["source"] in members and link["target"] in members]
                
                # 计算密度 (在大型图中可能需要进一步优化)
                member_count = len(members)
                possible_links = max(1, member_count * (member_count - 1) / 2)
                density = len(comm_links) / possible_links
                
                community_stats.append({
                    "id": comm_id,
                    "size": member_count,
                    "density": density,
                    "contains_center": is_center_in,
                    "sample_members": members[:min(5, member_count)]
                })
        
        # 过滤微小社区（只有一个成员且不包含中心实体）
        filtered_communities = {}
        filtered_stats = []
        filtered_count = 0

        for comm_id, members in communities.items():
            # 保留包含中心实体的社区或成员数大于1的社区
            if entity_id in members or len(members) > 1:
                filtered_communities[filtered_count + 1] = members
                
                # 更新对应的社区统计信息
                for stat in community_stats:
                    if stat["id"] == comm_id:
                        stat_copy = stat.copy()
                        stat_copy["id"] = filtered_count + 1
                        filtered_stats.append(stat_copy)
                        break
                        
                filtered_count += 1

        # 使用过滤后的社区数据
        return {
            "nodes": nodes,
            "links": links,
            "communities": filtered_stats,
            "community_count": filtered_count,
            "entity_community": 1 if entity_id in node_communities else None
        }
    except Exception as e:
        print(f"简化社区检测失败: {str(e)}")
        traceback.print_exc()
        return {"nodes": [], "links": [], "error": str(e)}
