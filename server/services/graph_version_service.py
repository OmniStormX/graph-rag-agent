"""图谱版本快照服务。"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List

from graphrag_agent.config.settings import GRAPH_ADMIN_SNAPSHOT_DIR
from graphrag_agent.runtime_logging import emit_runtime_log
from server_config.database import get_db_manager


_SAFE_NAME_PATTERN = re.compile(r"^[A-Za-z0-9_]+$")


class GraphVersionService:
    """负责导出、读取、恢复和比较图谱快照。"""

    def __init__(self) -> None:
        self._db_manager = get_db_manager()
        GRAPH_ADMIN_SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)

    def export_current_graph(self, version_id: str) -> Dict[str, Any]:
        """导出当前 Neo4j 图谱为 JSON 快照。"""
        graph = self._db_manager.get_graph()
        node_rows = graph.query(
            """
            MATCH (n)
            RETURN elementId(n) AS neo4j_id, labels(n) AS labels, properties(n) AS properties
            ORDER BY elementId(n)
            """
        )
        rel_rows = graph.query(
            """
            MATCH (a)-[r]->(b)
            RETURN elementId(a) AS source_id, elementId(b) AS target_id,
                   type(r) AS rel_type, properties(r) AS properties
            ORDER BY elementId(a), elementId(b)
            """
        )

        snapshot = {
            "version_id": version_id,
            "nodes": [
                {
                    "neo4j_id": self._normalize_value(row["neo4j_id"]),
                    "labels": self._normalize_value(row.get("labels", [])),
                    "properties": self._normalize_value(row.get("properties", {}) or {}),
                }
                for row in node_rows
            ],
            "relationships": [
                {
                    "source_id": self._normalize_value(row["source_id"]),
                    "target_id": self._normalize_value(row["target_id"]),
                    "type": self._normalize_value(row.get("rel_type", "")),
                    "properties": self._normalize_value(row.get("properties", {}) or {}),
                }
                for row in rel_rows
            ],
        }
        snapshot_path = GRAPH_ADMIN_SNAPSHOT_DIR / f"{version_id}.json"
        snapshot_path.write_text(
            json.dumps(snapshot, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        emit_runtime_log(
            "admin.graph.snapshot.exported",
            version_id=version_id,
            node_count=len(snapshot["nodes"]),
            relation_count=len(snapshot["relationships"]),
            snapshot_path=str(snapshot_path),
        )
        return {
            "snapshot_path": str(snapshot_path),
            "snapshot_data": json.dumps(snapshot, ensure_ascii=False),
            "entity_count": len(snapshot["nodes"]),
            "relation_count": len(snapshot["relationships"]),
        }

    def delete_snapshot(self, snapshot_path: str | Path | None) -> None:
        """删除快照文件。

        Args:
            snapshot_path: 快照文件路径。
        """
        if not snapshot_path:
            return
        snapshot_file = Path(snapshot_path)
        if snapshot_file.exists():
            snapshot_file.unlink()

    def load_snapshot(
        self,
        snapshot_path: str | Path | None,
        snapshot_data: str | None = None,
    ) -> Dict[str, Any]:
        """读取指定图谱快照，文件缺失时回退到元数据库快照。"""
        if snapshot_path:
            snapshot_file = Path(snapshot_path)
            if snapshot_file.exists():
                return json.loads(snapshot_file.read_text(encoding="utf-8"))
        if snapshot_data:
            return json.loads(snapshot_data)
        raise FileNotFoundError(f"图谱快照不存在: {snapshot_path}")

    def restore_snapshot(
        self,
        snapshot_path: str | Path | None,
        snapshot_data: str | None = None,
    ) -> Dict[str, Any]:
        """将图谱快照恢复到 Neo4j。"""
        snapshot = self.load_snapshot(snapshot_path, snapshot_data)
        driver = self._db_manager.get_driver()

        with driver.session() as session:
            session.run("MATCH (n) DETACH DELETE n")

            node_id_map: Dict[str, str] = {}
            for node in snapshot.get("nodes", []):
                labels = self._sanitize_labels(node.get("labels", []))
                result = session.run(
                    f"CREATE (n{labels}) SET n = $properties RETURN elementId(n) AS node_id",
                    properties=node.get("properties", {}),
                ).single()
                node_id_map[str(node["neo4j_id"])] = str(result["node_id"])

            for relation in snapshot.get("relationships", []):
                rel_type = self._sanitize_name(relation.get("type", "RELATED_TO"))
                session.run(
                    f"""
                    MATCH (s), (t)
                    WHERE elementId(s) = $source_id AND elementId(t) = $target_id
                    CREATE (s)-[r:`{rel_type}`]->(t)
                    SET r = $properties
                    """,
                    source_id=node_id_map[str(relation["source_id"])],
                    target_id=node_id_map[str(relation["target_id"])],
                    properties=relation.get("properties", {}),
                )

        emit_runtime_log(
            "admin.graph.snapshot.restored",
            snapshot_path=str(snapshot_path),
            node_count=len(snapshot.get("nodes", [])),
            relation_count=len(snapshot.get("relationships", [])),
        )
        return {
            "node_count": len(snapshot.get("nodes", [])),
            "relation_count": len(snapshot.get("relationships", [])),
        }

    def build_visualization_payload(
        self,
        snapshot_path: str | Path | None,
        snapshot_data: str | None = None,
    ) -> Dict[str, Any]:
        """将快照转换为前端可视化结构。"""
        snapshot = self.load_snapshot(snapshot_path, snapshot_data)
        nodes: List[Dict[str, Any]] = []
        links: List[Dict[str, Any]] = []

        for node in snapshot.get("nodes", []):
            properties = node.get("properties", {}) or {}
            labels = node.get("labels", [])
            node_id = properties.get("id") or f"neo4j:{node['neo4j_id']}"
            nodes.append(
                {
                    "id": str(node_id),
                    "label": self._build_node_label(properties, labels, str(node_id)),
                    "group": self._build_node_group(labels),
                    "description": properties.get("description", ""),
                    "properties": properties,
                    "labels": labels,
                }
            )

        id_lookup = {
            str(node["neo4j_id"]): str(node.get("properties", {}).get("id") or f"neo4j:{node['neo4j_id']}")
            for node in snapshot.get("nodes", [])
        }
        for relation in snapshot.get("relationships", []):
            links.append(
                {
                    "source": id_lookup.get(str(relation["source_id"]), str(relation["source_id"])),
                    "target": id_lookup.get(str(relation["target_id"]), str(relation["target_id"])),
                    "label": relation.get("type", "RELATED_TO"),
                    "properties": relation.get("properties", {}),
                }
            )

        return {
            "nodes": nodes,
            "links": links,
            "raw": snapshot,
        }

    def build_diff(
        self,
        left_snapshot_path: str | Path | None,
        right_snapshot_path: str | Path | None,
        left_snapshot_data: str | None = None,
        right_snapshot_data: str | None = None,
    ) -> Dict[str, Any]:
        """比较两个图谱版本快照。"""
        left = self.load_snapshot(left_snapshot_path, left_snapshot_data)
        right = self.load_snapshot(right_snapshot_path, right_snapshot_data)

        left_nodes = {
            self._node_key(node): node
            for node in left.get("nodes", [])
        }
        right_nodes = {
            self._node_key(node): node
            for node in right.get("nodes", [])
        }

        left_rels = {
            self._rel_key(rel): rel
            for rel in left.get("relationships", [])
        }
        right_rels = {
            self._rel_key(rel): rel
            for rel in right.get("relationships", [])
        }

        added_nodes = [right_nodes[key] for key in sorted(set(right_nodes) - set(left_nodes))]
        removed_nodes = [left_nodes[key] for key in sorted(set(left_nodes) - set(right_nodes))]
        added_relationships = [right_rels[key] for key in sorted(set(right_rels) - set(left_rels))]
        removed_relationships = [left_rels[key] for key in sorted(set(left_rels) - set(right_rels))]

        return {
            "summary": {
                "added_nodes": len(added_nodes),
                "removed_nodes": len(removed_nodes),
                "added_relationships": len(added_relationships),
                "removed_relationships": len(removed_relationships),
            },
            "added_nodes": added_nodes,
            "removed_nodes": removed_nodes,
            "added_relationships": added_relationships,
            "removed_relationships": removed_relationships,
        }

    def _node_key(self, node: Dict[str, Any]) -> str:
        properties = node.get("properties", {}) or {}
        return str(properties.get("id") or properties.get("name") or node.get("neo4j_id"))

    def _build_node_label(
        self,
        properties: Dict[str, Any],
        labels: List[str],
        fallback_id: str,
    ) -> str:
        """为可视化构造更友好的节点标签。"""
        if "__Chunk__" in labels:
            chunk_text = str(properties.get("text") or "").strip()
            if chunk_text:
                return self._truncate_text(chunk_text, limit=30)

        return str(properties.get("name") or properties.get("id") or fallback_id)

    def _build_node_group(self, labels: List[str]) -> str:
        """为图例和节点着色挑选更适合展示的分组标签。"""
        normalized_labels = [str(label) for label in labels if label]
        preferred_labels = [
            label
            for label in normalized_labels
            if not label.startswith("__")
        ]
        if preferred_labels:
            return preferred_labels[0]
        if normalized_labels:
            return normalized_labels[0]
        return "Unknown"

    def _rel_key(self, relation: Dict[str, Any]) -> str:
        return "::".join(
            [
                str(relation.get("source_id")),
                str(relation.get("type")),
                str(relation.get("target_id")),
            ]
        )

    def _sanitize_labels(self, labels: List[str]) -> str:
        safe_labels = [self._sanitize_name(label) for label in labels if label]
        return "".join([f":`{label}`" for label in safe_labels])

    def _sanitize_name(self, raw_name: str) -> str:
        name = str(raw_name or "").replace("`", "").strip()
        if not name:
            return "Unknown"
        if not _SAFE_NAME_PATTERN.fullmatch(name):
            name = re.sub(r"[^A-Za-z0-9_]", "_", name)
        return name or "Unknown"

    def _truncate_text(self, text: str, limit: int = 30) -> str:
        """截断文本，便于在图节点上展示。"""
        normalized = " ".join(str(text).split())
        if len(normalized) <= limit:
            return normalized
        return normalized[:limit] + "..."

    def _normalize_value(self, value: Any) -> Any:
        """将 Neo4j 返回值递归转换为可写入 JSON 的结构。"""
        if value is None:
            return None
        if isinstance(value, (str, int, float, bool)):
            return value
        if isinstance(value, dict):
            return {
                str(key): self._normalize_value(item)
                for key, item in value.items()
            }
        if isinstance(value, (list, tuple, set)):
            return [self._normalize_value(item) for item in value]
        if hasattr(value, "isoformat"):
            try:
                return value.isoformat()
            except TypeError:
                pass
        if hasattr(value, "to_native"):
            try:
                return self._normalize_value(value.to_native())
            except Exception:  # noqa: BLE001
                pass
        return str(value)


graph_version_service = GraphVersionService()
