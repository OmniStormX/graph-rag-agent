"""社区压缩图构建工具。"""

from __future__ import annotations

from collections import Counter, defaultdict, deque
from typing import Any, Dict, Iterable, List, Optional, Tuple


def build_community_overview_visualization(raw_snapshot: Dict[str, Any]) -> Dict[str, Any]:
    """基于快照构建真正压缩后的社区全局图谱。

    设计原则：
        1. 全局图谱只展示社区层，不直接混入实体节点。
        2. 使用实体间真实关系聚合出社区之间的超边。
        3. 优先选择“仍有多个社区”的最高层级，避免展示过细的底层社区。

    Args:
        raw_snapshot: 图谱快照原始载荷。

    Returns:
        Dict[str, Any]: PyVis 可直接消费的图谱数据。
    """
    raw_nodes = raw_snapshot.get("nodes", []) or []
    raw_links = raw_snapshot.get("relationships", []) or []
    if not raw_nodes:
        return _empty_payload(reason="empty_snapshot")

    node_lookup = {str(node.get("neo4j_id")): node for node in raw_nodes}
    visual_id_lookup = {
        str(node.get("neo4j_id")): str(
            node.get("properties", {}).get("id") or f"neo4j:{node.get('neo4j_id')}"
        )
        for node in raw_nodes
    }

    community_lookup: Dict[str, Dict[str, Any]] = {}
    entity_lookup: Dict[str, Dict[str, Any]] = {}
    level_counts: Counter[int] = Counter()

    for node in raw_nodes:
        neo4j_id = str(node.get("neo4j_id"))
        labels = node.get("labels", []) or []
        properties = node.get("properties", {}) or {}
        if "__Community__" in labels:
            level = _parse_level(properties.get("level"))
            visual_id = visual_id_lookup[neo4j_id]
            community_lookup[visual_id] = {
                "neo4j_id": neo4j_id,
                "visual_id": visual_id,
                "labels": labels,
                "properties": properties,
                "level": level,
            }
            level_counts[level] += 1
        elif "__Entity__" in labels:
            entity_lookup[neo4j_id] = {
                "neo4j_id": neo4j_id,
                "visual_id": visual_id_lookup[neo4j_id],
                "labels": labels,
                "properties": properties,
                "name": str(properties.get("name") or properties.get("id") or visual_id_lookup[neo4j_id]),
            }

    if not community_lookup:
        return _empty_payload(reason="missing_community_nodes")

    display_level = _select_display_level(level_counts)
    selected_communities = {
        community_id: community
        for community_id, community in community_lookup.items()
        if community["level"] == display_level
    }
    if not selected_communities:
        return _empty_payload(reason="missing_selected_level", display_level=display_level)

    community_membership_edges = _build_outgoing_membership_map(raw_links)
    entity_to_community: Dict[str, Optional[str]] = {}
    community_members: Dict[str, List[str]] = defaultdict(list)

    for entity_neo4j_id in entity_lookup:
        selected_community_id = _resolve_entity_display_community(
            entity_neo4j_id=entity_neo4j_id,
            membership_edges=community_membership_edges,
            node_lookup=node_lookup,
            visual_id_lookup=visual_id_lookup,
            selected_communities=selected_communities,
            community_lookup=community_lookup,
        )
        entity_to_community[entity_neo4j_id] = selected_community_id
        if selected_community_id:
            community_members[selected_community_id].append(entity_neo4j_id)

    aggregate_edges: Dict[Tuple[str, str], Dict[str, Any]] = {}
    internal_relation_counts: Counter[str] = Counter()
    external_relation_counts: Counter[str] = Counter()

    for link in raw_links:
        if str(link.get("type") or "") == "IN_COMMUNITY":
            continue

        source_id = str(link.get("source_id"))
        target_id = str(link.get("target_id"))
        source_node = node_lookup.get(source_id, {})
        target_node = node_lookup.get(target_id, {})
        source_labels = source_node.get("labels", []) or []
        target_labels = target_node.get("labels", []) or []

        if "__Entity__" not in source_labels or "__Entity__" not in target_labels:
            continue

        source_community = entity_to_community.get(source_id)
        target_community = entity_to_community.get(target_id)
        if not source_community or not target_community:
            continue

        relation_type = str(link.get("type") or "RELATED_TO")
        relation_weight = _parse_weight(link.get("properties", {}).get("weight"))

        if source_community == target_community:
            internal_relation_counts[source_community] += 1
            continue

        edge_key = tuple(sorted((source_community, target_community)))
        edge_payload = aggregate_edges.setdefault(
            edge_key,
            {
                "source": edge_key[0],
                "target": edge_key[1],
                "relation_count": 0,
                "weight": 0.0,
                "types": Counter(),
            },
        )
        edge_payload["relation_count"] += 1
        edge_payload["weight"] += relation_weight
        edge_payload["types"][relation_type] += 1
        external_relation_counts[source_community] += 1
        external_relation_counts[target_community] += 1

    overview_nodes: List[Dict[str, Any]] = []
    for community_id, community in sorted(
        selected_communities.items(),
        key=lambda item: (
            -len(community_members.get(item[0], [])),
            -_parse_rank(item[1]["properties"].get("community_rank")),
            item[0],
        ),
    ):
        properties = community.get("properties", {}) or {}
        topic_text = str(
            properties.get("topic")
            or properties.get("summary")
            or properties.get("full_content")
            or properties.get("description")
            or properties.get("id")
            or community_id
        )
        summary_text = str(
            properties.get("summary")
            or properties.get("full_content")
            or properties.get("description")
            or properties.get("id")
            or community_id
        )
        member_entity_ids = community_members.get(community_id, [])
        member_names = [
            entity_lookup[entity_id]["name"]
            for entity_id in member_entity_ids
            if entity_id in entity_lookup
        ]
        overview_nodes.append(
            {
                "id": community_id,
                "label": f"{_truncate_display_text(topic_text, 24)}\n{len(member_entity_ids)} 个成员",
                "group": f"CommunityLevel{display_level}",
                "description": _build_community_description(
                    community_id=community_id,
                    topic_text=topic_text,
                    summary_text=summary_text,
                    member_names=member_names,
                    internal_relation_count=int(internal_relation_counts.get(community_id, 0)),
                    external_relation_count=int(external_relation_counts.get(community_id, 0)),
                    level=display_level,
                ),
                "size": _scale_node_size(len(member_entity_ids)),
                "properties": {
                    **properties,
                    "topic": properties.get("topic"),
                    "display_level": display_level,
                    "member_count": len(member_entity_ids),
                    "internal_relation_count": int(internal_relation_counts.get(community_id, 0)),
                    "external_relation_count": int(external_relation_counts.get(community_id, 0)),
                    "child_count": _count_direct_children(community_id, raw_links, node_lookup, visual_id_lookup),
                },
                "labels": community.get("labels", []),
            }
        )

    overview_links = [
        {
            "source": edge["source"],
            "target": edge["target"],
            "label": str(edge["relation_count"]),
            "title": _build_edge_title(edge["relation_count"], edge["types"]),
            "weight": max(1.0, float(edge["relation_count"])),
        }
        for edge in sorted(
            aggregate_edges.values(),
            key=lambda item: (-item["relation_count"], item["source"], item["target"]),
        )
    ]

    return {
        "nodes": overview_nodes,
        "links": overview_links,
        "directed": False,
        "meta": {
            "mode": "compressed_community_graph",
            "display_level": display_level,
            "community_count": len(overview_nodes),
            "aggregated_edge_count": len(overview_links),
            "source_entity_count": len(entity_lookup),
        },
    }


def build_community_drilldown_visualization(
    raw_snapshot: Dict[str, Any],
    *,
    community_path: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """基于社区路径构建可递归下钻的社区子图。"""
    state = _build_hierarchy_state(raw_snapshot)
    if not state["communities"]:
        return _empty_payload(reason="missing_community_nodes")

    normalized_path = _normalize_community_path(community_path or [], state)
    current_parent_id = normalized_path[-1] if normalized_path else None

    if current_parent_id:
        current_community_ids = list(state["children_map"].get(current_parent_id, []))
        if not current_community_ids:
            current_community_ids = [current_parent_id]
    else:
        current_community_ids = [
            community_id
            for community_id, community in state["communities"].items()
            if community["level"] == state["display_level"]
        ]

    current_communities = {
        community_id: state["communities"][community_id]
        for community_id in current_community_ids
        if community_id in state["communities"]
    }
    if not current_communities:
        return _empty_payload(reason="missing_current_communities")

    entity_to_community: Dict[str, Optional[str]] = {}
    community_members: Dict[str, List[str]] = defaultdict(list)
    for entity_neo4j_id in state["entities"]:
        selected_community_id = _resolve_entity_display_community(
            entity_neo4j_id=entity_neo4j_id,
            membership_edges=state["membership_edges"],
            node_lookup=state["node_lookup"],
            visual_id_lookup=state["visual_id_lookup"],
            selected_communities=current_communities,
            community_lookup=state["communities"],
        )
        entity_to_community[entity_neo4j_id] = selected_community_id
        if selected_community_id:
            community_members[selected_community_id].append(entity_neo4j_id)

    aggregated_graph = _build_aggregated_graph(
        current_communities=current_communities,
        entity_lookup=state["entities"],
        entity_to_community=entity_to_community,
        community_members=community_members,
        raw_links=state["raw_links"],
        raw_node_lookup=state["node_lookup"],
        raw_visual_id_lookup=state["visual_id_lookup"],
        children_map=state["children_map"],
    )
    aggregated_graph["meta"] = {
        **(aggregated_graph.get("meta", {}) or {}),
        "path": normalized_path,
        "current_parent_id": current_parent_id,
        "path_labels": [
            _community_display_name(state["communities"][community_id]["properties"], community_id)
            for community_id in normalized_path
            if community_id in state["communities"]
        ],
        "expandable_node_ids": [
            node["id"]
            for node in aggregated_graph.get("nodes", [])
            if int(node.get("properties", {}).get("child_count") or 0) > 0
        ],
    }
    return aggregated_graph


def _empty_payload(
    *,
    reason: str,
    display_level: Optional[int] = None,
) -> Dict[str, Any]:
    """返回空图谱载荷。"""
    return {
        "nodes": [],
        "links": [],
        "directed": False,
        "meta": {
            "mode": "compressed_community_graph",
            "reason": reason,
            "display_level": display_level,
            "community_count": 0,
            "aggregated_edge_count": 0,
        },
    }


def _build_hierarchy_state(raw_snapshot: Dict[str, Any]) -> Dict[str, Any]:
    """构建社区层级解析状态。"""
    raw_nodes = raw_snapshot.get("nodes", []) or []
    raw_links = raw_snapshot.get("relationships", []) or []
    node_lookup = {str(node.get("neo4j_id")): node for node in raw_nodes}
    visual_id_lookup = {
        str(node.get("neo4j_id")): str(
            node.get("properties", {}).get("id") or f"neo4j:{node.get('neo4j_id')}"
        )
        for node in raw_nodes
    }
    communities: Dict[str, Dict[str, Any]] = {}
    entities: Dict[str, Dict[str, Any]] = {}
    level_counts: Counter[int] = Counter()

    for node in raw_nodes:
        neo4j_id = str(node.get("neo4j_id"))
        labels = node.get("labels", []) or []
        properties = node.get("properties", {}) or {}
        if "__Community__" in labels:
            level = _parse_level(properties.get("level"))
            visual_id = visual_id_lookup[neo4j_id]
            communities[visual_id] = {
                "neo4j_id": neo4j_id,
                "visual_id": visual_id,
                "labels": labels,
                "properties": properties,
                "level": level,
            }
            level_counts[level] += 1
        elif "__Entity__" in labels:
            entities[neo4j_id] = {
                "neo4j_id": neo4j_id,
                "visual_id": visual_id_lookup[neo4j_id],
                "labels": labels,
                "properties": properties,
                "name": str(properties.get("name") or properties.get("id") or visual_id_lookup[neo4j_id]),
            }

    membership_edges = _build_outgoing_membership_map(raw_links)
    children_map: Dict[str, List[str]] = defaultdict(list)
    parent_map: Dict[str, str] = {}
    for source_neo4j_id, target_ids in membership_edges.items():
        source_node = node_lookup.get(source_neo4j_id, {})
        source_labels = source_node.get("labels", []) or []
        if "__Community__" not in source_labels:
            continue
        source_visual_id = visual_id_lookup.get(source_neo4j_id, source_neo4j_id)
        for target_neo4j_id in target_ids:
            target_node = node_lookup.get(target_neo4j_id, {})
            target_labels = target_node.get("labels", []) or []
            if "__Community__" not in target_labels:
                continue
            target_visual_id = visual_id_lookup.get(target_neo4j_id, target_neo4j_id)
            children_map[target_visual_id].append(source_visual_id)
            parent_map[source_visual_id] = target_visual_id

    for parent_id, child_ids in children_map.items():
        # 保持层级顺序稳定，避免前端每次重绘跳动。
        children_map[parent_id] = sorted(
            set(child_ids),
            key=lambda community_id: (
                communities.get(community_id, {}).get("level", 0),
                community_id,
            ),
        )

    return {
        "raw_links": raw_links,
        "node_lookup": node_lookup,
        "visual_id_lookup": visual_id_lookup,
        "communities": communities,
        "entities": entities,
        "membership_edges": membership_edges,
        "children_map": dict(children_map),
        "parent_map": parent_map,
        "display_level": _select_display_level(level_counts),
    }


def _normalize_community_path(
    community_path: List[str],
    state: Dict[str, Any],
) -> List[str]:
    """规范化社区下钻路径，保证层级连续。"""
    communities = state["communities"]
    children_map = state["children_map"]
    normalized_path: List[str] = []
    current_valid_children = {
        community_id
        for community_id, community in communities.items()
        if community["level"] == state["display_level"]
    }

    for community_id in community_path:
        if community_id not in current_valid_children:
            break
        normalized_path.append(community_id)
        current_valid_children = set(children_map.get(community_id, []))
        if not current_valid_children:
            break

    return normalized_path


def _build_aggregated_graph(
    *,
    current_communities: Dict[str, Dict[str, Any]],
    entity_lookup: Dict[str, Dict[str, Any]],
    entity_to_community: Dict[str, Optional[str]],
    community_members: Dict[str, List[str]],
    raw_links: List[Dict[str, Any]],
    raw_node_lookup: Dict[str, Dict[str, Any]],
    raw_visual_id_lookup: Dict[str, str],
    children_map: Dict[str, List[str]],
) -> Dict[str, Any]:
    """针对当前社区集合构建聚合图。"""
    aggregate_edges: Dict[Tuple[str, str], Dict[str, Any]] = {}
    internal_relation_counts: Counter[str] = Counter()
    external_relation_counts: Counter[str] = Counter()

    for link in raw_links:
        if str(link.get("type") or "") == "IN_COMMUNITY":
            continue

        source_id = str(link.get("source_id"))
        target_id = str(link.get("target_id"))
        source_node = raw_node_lookup.get(source_id, {})
        target_node = raw_node_lookup.get(target_id, {})
        source_labels = source_node.get("labels", []) or []
        target_labels = target_node.get("labels", []) or []
        if "__Entity__" not in source_labels or "__Entity__" not in target_labels:
            continue

        source_community = entity_to_community.get(source_id)
        target_community = entity_to_community.get(target_id)
        if not source_community or not target_community:
            continue

        relation_type = str(link.get("type") or "RELATED_TO")
        relation_weight = _parse_weight(link.get("properties", {}).get("weight"))

        if source_community == target_community:
            internal_relation_counts[source_community] += 1
            continue

        edge_key = tuple(sorted((source_community, target_community)))
        edge_payload = aggregate_edges.setdefault(
            edge_key,
            {
                "source": edge_key[0],
                "target": edge_key[1],
                "relation_count": 0,
                "weight": 0.0,
                "types": Counter(),
            },
        )
        edge_payload["relation_count"] += 1
        edge_payload["weight"] += relation_weight
        edge_payload["types"][relation_type] += 1
        external_relation_counts[source_community] += 1
        external_relation_counts[target_community] += 1

    overview_nodes: List[Dict[str, Any]] = []
    for community_id, community in sorted(
        current_communities.items(),
        key=lambda item: (
            -len(community_members.get(item[0], [])),
            -_parse_rank(item[1]["properties"].get("community_rank")),
            item[0],
        ),
    ):
        properties = community.get("properties", {}) or {}
        topic_text = str(
            properties.get("topic")
            or properties.get("summary")
            or properties.get("full_content")
            or properties.get("description")
            or properties.get("id")
            or community_id
        )
        summary_text = str(
            properties.get("summary")
            or properties.get("full_content")
            or properties.get("description")
            or properties.get("id")
            or community_id
        )
        member_entity_ids = community_members.get(community_id, [])
        member_names = [
            entity_lookup[entity_id]["name"]
            for entity_id in member_entity_ids
            if entity_id in entity_lookup
        ]
        overview_nodes.append(
            {
                "id": community_id,
                "label": f"{_truncate_display_text(topic_text, 24)}\n{len(member_entity_ids)} 个成员",
                "group": f"CommunityLevel{community.get('level', 0)}",
                "description": _build_community_description(
                    community_id=community_id,
                    topic_text=topic_text,
                    summary_text=summary_text,
                    member_names=member_names,
                    internal_relation_count=int(internal_relation_counts.get(community_id, 0)),
                    external_relation_count=int(external_relation_counts.get(community_id, 0)),
                    level=int(community.get("level", 0)),
                ),
                "size": _scale_node_size(len(member_entity_ids)),
                "properties": {
                    **properties,
                    "topic": properties.get("topic"),
                    "display_level": int(community.get("level", 0)),
                    "member_count": len(member_entity_ids),
                    "internal_relation_count": int(internal_relation_counts.get(community_id, 0)),
                    "external_relation_count": int(external_relation_counts.get(community_id, 0)),
                    "child_count": len(children_map.get(community_id, [])),
                },
                "labels": community.get("labels", []),
            }
        )

    overview_links = [
        {
            "source": edge["source"],
            "target": edge["target"],
            "label": str(edge["relation_count"]),
            "title": _build_edge_title(edge["relation_count"], edge["types"]),
            "weight": max(1.0, float(edge["relation_count"])),
        }
        for edge in sorted(
            aggregate_edges.values(),
            key=lambda item: (-item["relation_count"], item["source"], item["target"]),
        )
    ]

    current_levels = {
        int(community.get("level", 0))
        for community in current_communities.values()
    }
    return {
        "nodes": overview_nodes,
        "links": overview_links,
        "directed": False,
        "meta": {
            "mode": "compressed_community_graph",
            "display_level": min(current_levels) if current_levels else 0,
            "community_count": len(overview_nodes),
            "aggregated_edge_count": len(overview_links),
            "source_entity_count": len(entity_lookup),
        },
    }


def _build_outgoing_membership_map(raw_links: Iterable[Dict[str, Any]]) -> Dict[str, List[str]]:
    """构建 `IN_COMMUNITY` 的出边索引。"""
    outgoing_map: Dict[str, List[str]] = defaultdict(list)
    for link in raw_links:
        if str(link.get("type") or "") != "IN_COMMUNITY":
            continue
        source_id = str(link.get("source_id"))
        target_id = str(link.get("target_id"))
        outgoing_map[source_id].append(target_id)
    return dict(outgoing_map)


def _resolve_entity_display_community(
    *,
    entity_neo4j_id: str,
    membership_edges: Dict[str, List[str]],
    node_lookup: Dict[str, Dict[str, Any]],
    visual_id_lookup: Dict[str, str],
    selected_communities: Dict[str, Dict[str, Any]],
    community_lookup: Dict[str, Dict[str, Any]],
) -> Optional[str]:
    """为实体解析其在展示层级上的主社区。"""
    queue = deque(membership_edges.get(entity_neo4j_id, []))
    visited = set()
    candidates: List[str] = []

    while queue:
        node_id = queue.popleft()
        if node_id in visited:
            continue
        visited.add(node_id)

        node = node_lookup.get(node_id, {})
        labels = node.get("labels", []) or []
        if "__Community__" not in labels:
            continue

        visual_id = visual_id_lookup.get(node_id, node_id)
        if visual_id in selected_communities:
            candidates.append(visual_id)
            continue

        queue.extend(membership_edges.get(node_id, []))

    if not candidates:
        return None

    return _pick_primary_community(candidates, community_lookup)


def _pick_primary_community(
    community_ids: List[str],
    community_lookup: Dict[str, Dict[str, Any]],
) -> str:
    """在多归属场景下为实体挑选稳定的主社区。"""
    unique_ids = sorted(set(community_ids))
    return max(
        unique_ids,
        key=lambda community_id: (
            _parse_rank(community_lookup.get(community_id, {}).get("properties", {}).get("community_rank")),
            community_id,
        ),
    )


def _select_display_level(level_counts: Counter[int]) -> int:
    """选择默认展示的社区层级。

    规则：
        1. 优先选择仍然存在至少两个社区的最高层级。
        2. 若所有更高层都已经收敛为一个社区，则回退到底层社区。
    """
    viable_levels = [level for level, count in level_counts.items() if count >= 2]
    if viable_levels:
        return max(viable_levels)
    return min(level_counts) if level_counts else 0


def _build_community_description(
    *,
    community_id: str,
    topic_text: str,
    summary_text: str,
    member_names: List[str],
    internal_relation_count: int,
    external_relation_count: int,
    level: int,
) -> str:
    """构建社区节点提示文案。"""
    representative_members = "、".join(member_names[:6]) if member_names else "暂无成员样本"
    return (
        f"社区ID: {community_id}\n"
        f"主题: {topic_text}\n"
        f"展示层级: {level}\n"
        f"成员数: {len(member_names)}\n"
        f"内部关系数: {internal_relation_count}\n"
        f"跨社区关系数: {external_relation_count}\n"
        f"代表成员: {representative_members}\n"
        f"摘要: {summary_text}"
    )


def _build_edge_title(relation_count: int, type_counter: Counter[str]) -> str:
    """构建社区聚合边提示文案。"""
    top_types = "、".join(
        f"{relation_type}×{count}"
        for relation_type, count in type_counter.most_common(3)
    )
    if not top_types:
        top_types = "未识别关系类型"
    return f"跨社区关系数: {relation_count}\n关系构成: {top_types}"


def _parse_level(value: Any) -> int:
    """解析社区层级。"""
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _parse_rank(value: Any) -> float:
    """解析社区排序分数。"""
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _parse_weight(value: Any) -> float:
    """解析关系权重。"""
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return 1.0
    return parsed if parsed > 0 else 1.0


def _scale_node_size(member_count: int) -> int:
    """按成员规模缩放社区节点大小。"""
    return max(20, min(46, 20 + member_count // 2))


def _count_direct_children(
    community_id: str,
    raw_links: List[Dict[str, Any]],
    node_lookup: Dict[str, Dict[str, Any]],
    visual_id_lookup: Dict[str, str],
) -> int:
    """统计社区的直接子社区数量。"""
    child_ids = set()
    for link in raw_links:
        if str(link.get("type") or "") != "IN_COMMUNITY":
            continue
        source_id = str(link.get("source_id"))
        target_id = str(link.get("target_id"))
        source_node = node_lookup.get(source_id, {})
        target_node = node_lookup.get(target_id, {})
        if "__Community__" not in (source_node.get("labels", []) or []):
            continue
        if "__Community__" not in (target_node.get("labels", []) or []):
            continue
        if visual_id_lookup.get(target_id, target_id) != community_id:
            continue
        child_ids.add(visual_id_lookup.get(source_id, source_id))
    return len(child_ids)


def _community_display_name(properties: Dict[str, Any], community_id: str) -> str:
    """返回适合面包屑展示的社区名称。"""
    return str(
        properties.get("topic")
        or properties.get("summary")
        or properties.get("id")
        or community_id
    )


def _truncate_display_text(text: str, limit: int = 30) -> str:
    """截断展示文本，避免节点标签过长。"""
    normalized = " ".join(str(text).split())
    if len(normalized) <= limit:
        return normalized
    return normalized[:limit] + "..."
