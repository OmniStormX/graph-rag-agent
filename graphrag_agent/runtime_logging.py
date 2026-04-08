"""运行时日志工具。

该模块为问答链路提供统一的单行结构化日志输出，便于在服务端、
容器环境和 Kubernetes 日志采集中快速定位请求耗时与故障阶段。
"""

from __future__ import annotations

import json
import time
from typing import Any, Dict


def shorten_text(text: Any, limit: int = 120) -> str:
    """截断日志中的长文本，避免控制台被大字段淹没。"""
    if text is None:
        return ""

    value = str(text).replace("\n", "\\n")
    if len(value) <= limit:
        return value
    return f"{value[:limit]}..."


def _normalize_value(value: Any) -> Any:
    """将值转换为便于 JSON 输出的形式。"""
    if value is None:
        return None

    if isinstance(value, (str, int, float, bool)):
        return value

    if isinstance(value, dict):
        return {str(k): _normalize_value(v) for k, v in value.items()}

    if isinstance(value, (list, tuple, set)):
        return [_normalize_value(item) for item in value]

    return shorten_text(value, limit=200)


def emit_runtime_log(event: str, **fields: Any) -> None:
    """输出统一格式的运行时日志。"""
    payload: Dict[str, Any] = {
        "ts": round(time.time(), 6),
        "event": event,
    }

    for key, value in fields.items():
        payload[key] = _normalize_value(value)

    print(
        "[GraphRAG] "
        + json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    )
