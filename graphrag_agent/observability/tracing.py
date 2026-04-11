"""本地可部署可观测性产品的统一追踪适配层。"""

from __future__ import annotations

import os
import warnings
from typing import Any, Callable, TypeVar

F = TypeVar("F", bound=Callable[..., Any])

_IMPORT_ERROR: Exception | None = None
_WARNED = False

try:
    # Langfuse 4.x 推荐使用顶层 observe 接口。
    from langfuse import observe as _langfuse_observe
except ImportError:
    try:
        # 兼容部分旧版本 SDK 的 decorators 路径。
        from langfuse.decorators import observe as _langfuse_observe  # type: ignore[attr-defined]
    except ImportError as exc:  # pragma: no cover - 依赖缺失时进入兜底
        _langfuse_observe = None
        _IMPORT_ERROR = exc


def _is_langfuse_enabled() -> bool:
    """判断是否启用 Langfuse 本地追踪。"""
    enabled = os.getenv("LANGFUSE_ENABLED", "").strip().lower()
    if enabled not in {"1", "true", "yes", "y", "on"}:
        return False

    public_key = os.getenv("LANGFUSE_PUBLIC_KEY", "").strip()
    secret_key = os.getenv("LANGFUSE_SECRET_KEY", "").strip()
    host = (
        os.getenv("LANGFUSE_HOST", "").strip()
        or os.getenv("LANGFUSE_BASE_URL", "").strip()
    )
    return bool(public_key and secret_key and host)


def _warn_once(message: str) -> None:
    """仅告警一次，避免在高频调用中刷屏。"""
    global _WARNED
    if _WARNED:
        return
    warnings.warn(message, RuntimeWarning, stacklevel=2)
    _WARNED = True


def _noop_observe(*_args: Any, **_kwargs: Any) -> Callable[[F], F]:
    """返回空操作装饰器，保证未启用追踪时业务逻辑不受影响。"""

    def decorator(func: F) -> F:
        return func

    return decorator


def observe(*args: Any, **kwargs: Any) -> Callable[[F], F]:
    """统一暴露追踪装饰器，默认优先接入 Langfuse。"""
    if not _is_langfuse_enabled():
        return _noop_observe(*args, **kwargs)

    if _langfuse_observe is None:
        _warn_once(
            f"LANGFUSE_ENABLED=true，但当前环境未安装 langfuse SDK：{_IMPORT_ERROR}"
        )
        return _noop_observe(*args, **kwargs)

    return _langfuse_observe(*args, **kwargs)
