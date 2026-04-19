"""容器启动前的图谱恢复脚本。"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Any

from neo4j import GraphDatabase

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _load_env_file(env_path: Path) -> None:
    """按最小规则解析 `.env`，避免额外运行时依赖。"""
    if not env_path.exists():
        return

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("'\"")
        os.environ.setdefault(key, value)


_load_env_file(PROJECT_ROOT / ".env")

GRAPH_ADMIN_SNAPSHOT_DIR = Path(
    os.getenv(
        "GRAPH_ADMIN_SNAPSHOT_DIR",
        PROJECT_ROOT / "runtime" / "admin" / "snapshots",
    )
).expanduser()


def _get_driver():
    """构造 Neo4j 驱动，避免依赖项目运行时初始化。"""
    neo4j_uri = os.getenv("NEO4J_URI", "").strip()
    neo4j_username = os.getenv("NEO4J_USERNAME", "").strip()
    neo4j_password = os.getenv("NEO4J_PASSWORD", "").strip()
    if not neo4j_uri:
        raise ValueError("未配置 NEO4J_URI")
    return GraphDatabase.driver(
        neo4j_uri,
        auth=(neo4j_username, neo4j_password),
    )


def _get_env_bool(name: str, default: bool) -> bool:
    """解析布尔环境变量。"""
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "y", "on"}


def _wait_for_neo4j(timeout_seconds: int) -> None:
    """等待 Neo4j 可连接，避免应用比数据库更早启动。"""
    deadline = time.time() + timeout_seconds
    last_error: Exception | None = None

    while time.time() < deadline:
        try:
            driver = _get_driver()
            driver.verify_connectivity()
            driver.close()
            return
        except Exception as exc:  # pragma: no cover - 启动探活路径
            last_error = exc
            time.sleep(2)

    raise RuntimeError(f"等待 Neo4j 就绪超时: {last_error}") from last_error


def _resolve_snapshot_path() -> Path | None:
    """解析需要恢复的快照路径，未显式指定时取最新快照。"""
    configured_path = os.getenv("GRAPH_RESTORE_SNAPSHOT_PATH", "").strip()
    if configured_path:
        path = Path(configured_path).expanduser()
        return path if path.exists() else None

    snapshots = sorted(
        GRAPH_ADMIN_SNAPSHOT_DIR.glob("*.json"),
        key=lambda item: item.stat().st_mtime,
        reverse=True,
    )
    return snapshots[0] if snapshots else None


def _get_node_count() -> int:
    """读取当前图数据库节点数。"""
    driver = _get_driver()
    with driver.session() as session:
        record = session.run("MATCH (n) RETURN count(n) AS count").single()
    driver.close()
    return int(record["count"]) if record else 0


def _get_embedding_dimension(label: str) -> int | None:
    """从图中推断 embedding 维度，用于重建向量索引。"""
    driver = _get_driver()
    with driver.session() as session:
        record = session.run(
            f"""
            MATCH (n:`{label}`)
            WHERE n.embedding IS NOT NULL
            RETURN size(n.embedding) AS dims
            LIMIT 1
            """
        ).single()
    driver.close()
    if not record or record["dims"] is None:
        return None
    return int(record["dims"])


def _sanitize_name(name: str, fallback: str) -> str:
    """限制标签和关系名为安全字符，避免拼接 Cypher 时注入。"""
    normalized = "".join(ch for ch in str(name) if ch.isalnum() or ch == "_")
    return normalized or fallback


def _sanitize_labels(labels: list[str]) -> str:
    """拼接安全的标签列表。"""
    return "".join(f":`{_sanitize_name(label, 'Label')}`" for label in labels)


def _restore_snapshot(snapshot: dict[str, Any]) -> dict[str, int]:
    """将 JSON 快照写回 Neo4j。"""
    driver = _get_driver()
    with driver.session() as session:
        session.run("MATCH (n) DETACH DELETE n")

        node_id_map: dict[str, str] = {}
        for node in snapshot.get("nodes", []):
            result = session.run(
                f"CREATE (n{_sanitize_labels(node.get('labels', []))}) "
                "SET n = $properties "
                "RETURN elementId(n) AS node_id",
                properties=node.get("properties", {}) or {},
            ).single()
            if result is None:
                raise RuntimeError("恢复节点失败，未返回 Neo4j 节点 ID")
            node_id_map[str(node["neo4j_id"])] = str(result["node_id"])

        for relation in snapshot.get("relationships", []):
            rel_type = _sanitize_name(relation.get("type", "RELATED_TO"), "RELATED_TO")
            session.run(
                f"""
                MATCH (s), (t)
                WHERE elementId(s) = $source_id AND elementId(t) = $target_id
                CREATE (s)-[r:`{rel_type}`]->(t)
                SET r = $properties
                """,
                source_id=node_id_map[str(relation["source_id"])],
                target_id=node_id_map[str(relation["target_id"])],
                properties=relation.get("properties", {}) or {},
            )
    driver.close()
    return {
        "node_count": len(snapshot.get("nodes", [])),
        "relation_count": len(snapshot.get("relationships", [])),
    }


def _ensure_indexes(snapshot: dict[str, Any]) -> None:
    """根据恢复后的图谱补齐检索所需索引。"""
    labels = {
        label
        for node in snapshot.get("nodes", [])
        for label in node.get("labels", [])
    }
    driver = _get_driver()

    # 这些索引是当前检索链路的基础设施，恢复后需要立即补齐。
    index_queries: list[str] = [
        "CREATE INDEX entity_id IF NOT EXISTS FOR (e:`__Entity__`) ON (e.id)",
    ]
    if "__Chunk__" in labels:
        index_queries.extend(
            [
                "CREATE INDEX chunk_id IF NOT EXISTS FOR (c:`__Chunk__`) ON (c.id)",
                "CREATE INDEX chunk_file_name IF NOT EXISTS FOR (c:`__Chunk__`) ON (c.fileName)",
                "CREATE INDEX chunk_position IF NOT EXISTS FOR (c:`__Chunk__`) ON (c.position)",
            ]
        )

    with driver.session() as session:
        for query in index_queries:
            session.run(query)

        entity_dims = _get_embedding_dimension("__Entity__")
        if entity_dims:
            similarity = os.getenv(
                "GRAPH_RESTORE_VECTOR_SIMILARITY_FUNCTION",
                "cosine",
            ).strip().lower()
            if similarity not in {"cosine", "euclidean"}:
                similarity = "cosine"

            session.run(
                f"""
                CREATE VECTOR INDEX vector IF NOT EXISTS
                FOR (e:`__Entity__`) ON (e.embedding)
                OPTIONS {{
                  indexConfig: {{
                    `vector.dimensions`: {entity_dims},
                    `vector.similarity_function`: '{similarity}'
                  }}
                }}
                """
            )
    driver.close()


def _restore_graph_if_needed() -> int:
    """按配置恢复图谱快照。"""
    if not _get_env_bool("GRAPH_RESTORE_ON_START", True):
        print("[restore_graph] 已关闭启动恢复")
        return 0

    timeout_seconds = int(os.getenv("GRAPH_RESTORE_TIMEOUT_SECONDS", "120"))
    _wait_for_neo4j(timeout_seconds)

    node_count = _get_node_count()
    if node_count > 0 and _get_env_bool("GRAPH_RESTORE_IF_EMPTY_ONLY", True):
        print(f"[restore_graph] 当前库已有 {node_count} 个节点，跳过恢复")
        return 0

    snapshot_path = _resolve_snapshot_path()
    if snapshot_path is None:
        print("[restore_graph] 未找到可用图快照，跳过恢复")
        return 0

    print(f"[restore_graph] 开始恢复图快照: {snapshot_path}")
    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    result = _restore_snapshot(snapshot)
    _ensure_indexes(snapshot)
    print(
        "[restore_graph] 图快照恢复完成，"
        f"节点 {result['node_count']} 个，关系 {result['relation_count']} 条"
    )
    return 0


if __name__ == "__main__":
    try:
        sys.exit(_restore_graph_if_needed())
    except Exception as exc:  # pragma: no cover - 启动失败直接退出
        print(f"[restore_graph] 恢复失败: {exc}", file=sys.stderr)
        sys.exit(1)
