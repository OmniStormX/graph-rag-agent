"""社区摘要结构化解析工具。"""

from __future__ import annotations

import json
from typing import Any, Dict


def parse_community_summary_payload(
    raw_output: str,
    *,
    fallback_text: str = "",
) -> Dict[str, str]:
    """将 LLM 输出解析为结构化社区主题与摘要。

    Args:
        raw_output: 模型原始输出。
        fallback_text: 当输出不规范时，用于兜底生成主题的文本。

    Returns:
        Dict[str, str]: 结构化结果，包含 ``topic`` 与 ``summary``。
    """
    normalized_output = str(raw_output or "").strip()
    fallback_source = str(fallback_text or "").strip()
    payload = _try_parse_json_object(normalized_output)

    if payload:
        topic = _normalize_text(
            payload.get("topic")
            or payload.get("title")
            or payload.get("theme")
        )
        summary = _normalize_text(
            payload.get("summary")
            or payload.get("description")
            or payload.get("content")
        )
    else:
        topic = ""
        summary = normalized_output

    if not summary:
        summary = fallback_source or normalized_output or "此社区暂无足够信息。"
    if not topic:
        topic = derive_topic_from_text(summary or fallback_source)

    return {
        "topic": topic,
        "summary": summary,
    }


def derive_topic_from_text(text: str, *, limit: int = 24) -> str:
    """从自然语言中提取适合作为标题的短主题。"""
    normalized = _normalize_text(text)
    if not normalized:
        return "未命名社区"

    for separator in ("\n", "。", "；", ";", ":", "：", ",", "，"):
        if separator in normalized:
            normalized = normalized.split(separator, 1)[0].strip()
            break

    if len(normalized) <= limit:
        return normalized
    return normalized[:limit].rstrip() + "..."


def _try_parse_json_object(raw_output: str) -> Dict[str, Any]:
    """尝试从文本中提取 JSON 对象。"""
    if not raw_output:
        return {}

    candidate = raw_output.strip()
    try:
        parsed = json.loads(candidate)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass

    start = candidate.find("{")
    end = candidate.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return {}

    try:
        parsed = json.loads(candidate[start:end + 1])
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _normalize_text(value: Any) -> str:
    """统一清洗文本字段。"""
    return " ".join(str(value or "").split()).strip()
