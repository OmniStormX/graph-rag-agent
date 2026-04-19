"""应用容器健康检查脚本。"""

from __future__ import annotations

import sys
import urllib.error
import urllib.request


def _check(url: str) -> bool:
    """检查目标地址是否返回 2xx/3xx。"""
    try:
        with urllib.request.urlopen(url, timeout=5) as response:
            return 200 <= response.status < 400
    except (urllib.error.URLError, TimeoutError):
        return False


def main() -> int:
    """依次检查后端与两个 Streamlit 端口。"""
    checks = [
        "http://127.0.0.1:8000/docs",
        "http://127.0.0.1:8501/_stcore/health",
        "http://127.0.0.1:8502/_stcore/health",
    ]
    return 0 if all(_check(url) for url in checks) else 1


if __name__ == "__main__":
    sys.exit(main())
