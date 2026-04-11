"""向量索引选择与诊断工具。"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional


def normalize_index_name(name: Any) -> str:
    """标准化索引名，兼容环境变量中的空白与包裹引号。"""
    text = str(name or "").strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in {"'", '"'}:
        return text[1:-1].strip()
    return text


def normalize_vector_index_rows(rows: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """规范化 `SHOW INDEXES` 的结果行。"""
    normalized_rows: List[Dict[str, Any]] = []
    for row in rows:
        labels = row.get("labelsOrTypes") or []
        properties = row.get("properties") or []
        normalized_rows.append(
            {
                "name": normalize_index_name(row.get("name")),
                "type": str(row.get("type") or ""),
                "state": str(row.get("state") or ""),
                "entity_type": str(row.get("entityType") or ""),
                "labels_or_types": [str(item) for item in labels],
                "properties": [str(item) for item in properties],
                "failure_message": str(row.get("failureMessage") or ""),
            }
        )
    return normalized_rows


def resolve_vector_index_name(
    rows: Iterable[Dict[str, Any]],
    *,
    preferred_name: str,
    preferred_label: str = "__Entity__",
    preferred_property: str = "embedding",
) -> Optional[str]:
    """从可用索引中挑选最适合本地检索的向量索引名。"""
    normalized_rows = normalize_vector_index_rows(rows)
    normalized_preferred_name = normalize_index_name(preferred_name)
    online_rows = [
        row for row in normalized_rows
        if row["type"].upper() == "VECTOR" and row["state"].upper() == "ONLINE"
    ]
    if not online_rows:
        return None

    for row in online_rows:
        if row["name"] == normalized_preferred_name:
            return row["name"]

    entity_rows = [
        row
        for row in online_rows
        if preferred_label in row["labels_or_types"] and preferred_property in row["properties"]
    ]
    if entity_rows:
        preferred_order = ["vector", "entity_embedding", "entity_vector"]
        for candidate_name in preferred_order:
            for row in entity_rows:
                if row["name"] == candidate_name:
                    return row["name"]
        return entity_rows[0]["name"]

    return online_rows[0]["name"]


def build_missing_vector_index_message(
    *,
    preferred_name: str,
    rows: Iterable[Dict[str, Any]],
) -> str:
    """构建更易读的向量索引缺失提示。"""
    normalized_rows = normalize_vector_index_rows(rows)
    normalized_preferred_name = normalize_index_name(preferred_name)
    vector_rows = [
        row for row in normalized_rows if row["type"].upper() == "VECTOR"
    ]
    if vector_rows:
        preferred_rows = [
            row for row in vector_rows if row["name"] == normalized_preferred_name
        ]
        if preferred_rows:
            matched_row = preferred_rows[0]
            state = matched_row["state"] or "UNKNOWN"
            details = (
                f"标签/类型={matched_row['labels_or_types']}, "
                f"属性={matched_row['properties']}"
            )
            failure_message = matched_row["failure_message"].strip()
            extra = f" 失败原因: {failure_message}" if failure_message else ""
            return (
                f"本地检索配置的向量索引 `{normalized_preferred_name}` 已存在，"
                f"但当前状态为 `{state}`，未达到 `ONLINE`。"
                f" {details}.{extra}"
                " 请等待索引构建完成，或重建实体向量索引。"
            )

        available_names = [
            f"{row['name']}({row['state'] or 'UNKNOWN'})"
            for row in sorted(vector_rows, key=lambda item: item["name"])
        ]
        return (
            f"本地检索需要的向量索引 `{normalized_preferred_name}` 不存在，"
            f"当前可用向量索引为: {', '.join(sorted(available_names))}。"
            " 请检查 `LOCAL_SEARCH_INDEX_NAME` 或重新构建实体向量索引。"
        )
    return (
        f"本地检索需要的向量索引 `{normalized_preferred_name}` 不存在，"
        "当前数据库中没有任何 ONLINE 的向量索引。"
        " 请先执行实体索引重建或全量/增量构建。"
    )
