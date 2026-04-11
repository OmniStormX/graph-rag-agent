"""后台管理系统前端 API 封装。"""

from __future__ import annotations

from typing import Any, Dict, Optional

import requests

from frontend_config.settings import ADMIN_API_URL


def get_admin_health() -> Dict[str, Any]:
    return _get("/admin/health")


def get_admin_status() -> Dict[str, Any]:
    return _get("/admin/status")


def get_documents() -> Dict[str, Any]:
    return _get("/admin/documents")


def upload_document(file_name: str, content: bytes) -> Dict[str, Any]:
    response = requests.post(
        f"{ADMIN_API_URL}/admin/documents/upload",
        files={"file": (file_name, content, "application/pdf")},
        timeout=120,
    )
    response.raise_for_status()
    return response.json()


def create_incremental_build(
    version_name: Optional[str],
    revision_ids: list[str],
) -> Dict[str, Any]:
    return _post(
        "/admin/builds/incremental",
        {
            "version_name": version_name,
            "document_revision_ids": revision_ids,
        },
    )


def create_full_rebuild(
    version_name: Optional[str],
    revision_ids: list[str],
) -> Dict[str, Any]:
    return _post(
        "/admin/builds/full-rebuild",
        {
            "version_name": version_name,
            "document_revision_ids": revision_ids,
        },
    )


def get_builds(
    page: int = 1,
    page_size: int = 20,
    keyword: Optional[str] = None,
    status: Optional[str] = None,
) -> Dict[str, Any]:
    return _get(
        "/admin/builds",
        params={
            "page": page,
            "page_size": page_size,
            "keyword": keyword,
            "status": status,
        },
    )


def get_build(job_id: str) -> Dict[str, Any]:
    return _get(f"/admin/builds/{job_id}")


def get_build_logs(job_id: str, lines: int = 200) -> Dict[str, Any]:
    return _get(f"/admin/builds/{job_id}/logs", params={"lines": lines})


def get_graph_versions() -> Dict[str, Any]:
    return _get("/admin/graph/versions")


def get_graph_version(version_id: str) -> Dict[str, Any]:
    return _get(f"/admin/graph/versions/{version_id}")


def get_graph_visualization(version_id: str) -> Dict[str, Any]:
    return _get(f"/admin/graph/versions/{version_id}/visualization")


def get_graph_diff(left_version_id: str, right_version_id: str) -> Dict[str, Any]:
    return _get(
        "/admin/graph/versions/diff",
        params={"left": left_version_id, "right": right_version_id},
    )


def activate_graph_version(version_id: str) -> Dict[str, Any]:
    return _post(f"/admin/graph/versions/{version_id}/activate", {"activate": True})


def rollback_graph_version(version_id: str) -> Dict[str, Any]:
    return _post(f"/admin/graph/versions/{version_id}/rollback", {})


def rebuild_graph_version_communities(version_id: str) -> Dict[str, Any]:
    return _post(f"/admin/graph/versions/{version_id}/rebuild-communities", {})


def delete_graph_version(version_id: str) -> Dict[str, Any]:
    response = requests.delete(f"{ADMIN_API_URL}/admin/graph/versions/{version_id}", timeout=120)
    response.raise_for_status()
    return response.json()


def get_corrections() -> Dict[str, Any]:
    return _get("/admin/corrections")


def create_correction(
    *,
    rule_type: str,
    title: str,
    content: str,
    scope_type: str,
    scope_id: Optional[str],
    enabled: bool,
) -> Dict[str, Any]:
    return _post(
        "/admin/corrections",
        {
            "rule_type": rule_type,
            "title": title,
            "content": content,
            "scope_type": scope_type,
            "scope_id": scope_id,
            "enabled": enabled,
        },
    )


def get_backend_logs(lines: int = 200) -> Dict[str, Any]:
    return _get("/admin/logs/backend", params={"lines": lines})


def get_frontend_logs(lines: int = 200) -> Dict[str, Any]:
    return _get("/admin/logs/frontend", params={"lines": lines})


def get_admin_processes() -> Dict[str, Any]:
    return _get("/admin/ops/processes")


def trigger_admin_action(target: str, action: str) -> Dict[str, Any]:
    return _post("/admin/ops/actions", {"target": target, "action": action})


def reset_admin_state(confirm: bool = True) -> Dict[str, Any]:
    return _post("/admin/ops/reset", {"confirm": confirm})


def _get(path: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    response = requests.get(f"{ADMIN_API_URL}{path}", params=params, timeout=60)
    response.raise_for_status()
    return response.json()


def _post(path: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    response = requests.post(f"{ADMIN_API_URL}{path}", json=payload, timeout=120)
    response.raise_for_status()
    return response.json()
