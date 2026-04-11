"""图谱后台管理路由。"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, File, HTTPException, Query, UploadFile

from graphrag_agent.config.settings import (
    GRAPH_ADMIN_BACKEND_LOG_PATH,
    GRAPH_ADMIN_ENABLED,
    GRAPH_ADMIN_FRONTEND_LOG_PATH,
    GRAPH_ADMIN_MAX_LOG_LINES,
)
from models.schemas import (
    AdminActionRequest,
    AdminResetRequest,
    ActivateVersionRequest,
    AdminStatusResponse,
    BuildRequest,
    BuildJobPageResponse,
    CorrectionRuleCreateRequest,
    LogResponse,
)
from server_config.database import get_db_manager
from services.admin_build_service import admin_build_service
from services.admin_metadata_service import metadata_service
from services.admin_ops_service import admin_ops_service
from services.graph_version_service import graph_version_service


router = APIRouter(prefix="/admin")


@router.get("/health")
async def admin_health() -> Dict[str, Any]:
    """返回后台管理系统健康状态。"""
    neo4j_connected = _check_neo4j_connectivity()
    return {
        "enabled": GRAPH_ADMIN_ENABLED,
        "metadata_enabled": metadata_service.available,
        "neo4j_connected": neo4j_connected,
    }


@router.get("/status", response_model=AdminStatusResponse)
async def admin_status() -> AdminStatusResponse:
    """返回后台系统总体状态。"""
    active_version = metadata_service.get_active_graph_version()
    jobs = metadata_service.list_build_jobs()
    latest_job = jobs[0] if jobs else None
    return AdminStatusResponse(
        metadata_db_connected=metadata_service.available,
        neo4j_connected=_check_neo4j_connectivity(),
        active_version_id=active_version["version_id"] if active_version else None,
        active_version_name=active_version["version_name"] if active_version else None,
        latest_job=latest_job,
        document_count=len(metadata_service.list_documents()),
        version_count=len(metadata_service.list_graph_versions()),
    )


@router.get("/documents")
async def list_documents() -> Dict[str, Any]:
    """返回文档及其修订版本。"""
    documents = metadata_service.list_documents()
    revisions = metadata_service.list_document_revisions()
    return {
        "documents": documents,
        "revisions": revisions,
    }


@router.get("/documents/{document_id}/revisions")
async def list_document_revisions(document_id: str) -> Dict[str, Any]:
    """返回指定文档的修订版本。"""
    return {
        "document_id": document_id,
        "revisions": metadata_service.list_document_revisions(document_id=document_id),
    }


@router.post("/documents/upload")
async def upload_document(file: UploadFile = File(...)) -> Dict[str, Any]:
    """上传 PDF 文档并登记为新的修订版本。"""
    if not GRAPH_ADMIN_ENABLED:
        raise HTTPException(status_code=404, detail="后台管理系统未启用")
    if not file.filename:
        raise HTTPException(status_code=400, detail="缺少上传文件名")
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="当前仅支持上传 PDF 文件")

    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="上传文件为空")

    try:
        metadata = admin_build_service.save_uploaded_file(
            file_name=file.filename,
            content=content,
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return metadata


@router.post("/builds/incremental")
async def trigger_incremental_build(request: BuildRequest) -> Dict[str, Any]:
    """触发增量构建任务。"""
    return _create_build(
        build_type="incremental",
        request=request,
    )


@router.post("/builds/full-rebuild")
async def trigger_full_rebuild(request: BuildRequest) -> Dict[str, Any]:
    """触发全量重建任务。"""
    return _create_build(
        build_type="full_rebuild",
        request=request,
    )


@router.get("/builds", response_model=BuildJobPageResponse)
async def list_builds(
    page: int = Query(1, ge=1, description="页码，从 1 开始"),
    page_size: int = Query(20, ge=1, le=200, description="每页任务数"),
    keyword: Optional[str] = Query(None, description="任务关键字过滤"),
    status: Optional[str] = Query(None, description="任务状态过滤"),
) -> BuildJobPageResponse:
    """返回构建任务分页列表。"""
    return BuildJobPageResponse(
        **metadata_service.list_build_jobs_paginated(
            page=page,
            page_size=page_size,
            keyword=keyword,
            status=status,
        )
    )


@router.get("/builds/{job_id}")
async def get_build(job_id: str) -> Dict[str, Any]:
    """返回单个构建任务详情。"""
    job = metadata_service.get_build_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="构建任务不存在")
    return {"job": job}


@router.get("/builds/{job_id}/logs", response_model=LogResponse)
async def get_build_logs(job_id: str, lines: Optional[int] = None) -> LogResponse:
    """读取指定构建任务日志。"""
    job = metadata_service.get_build_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="构建任务不存在")
    return _read_log_file(job.get("log_path") or "", lines)


@router.get("/graph/versions")
async def list_graph_versions() -> Dict[str, List[Dict[str, Any]]]:
    """返回图谱版本列表。"""
    return {
        "items": metadata_service.list_graph_versions(),
    }


@router.get("/graph/versions/{version_id}")
async def get_graph_version(version_id: str) -> Dict[str, Any]:
    """返回单个图谱版本详情。"""
    version = metadata_service.get_graph_version(version_id)
    if not version:
        raise HTTPException(status_code=404, detail="图谱版本不存在")

    snapshot_path = version.get("snapshot_path")
    snapshot = None
    if snapshot_path or version.get("snapshot_data"):
        snapshot = graph_version_service.load_snapshot(
            snapshot_path,
            version.get("snapshot_data"),
        )

    build_jobs = metadata_service.list_build_jobs_by_version(version_id)
    revision_rows: List[Dict[str, Any]] = []
    for build_job in build_jobs:
        revision_rows.extend(metadata_service.list_job_revisions(build_job["job_id"]))

    # 版本下的 revision 可能被多个任务重复引用，这里按 revision_id 去重，便于前端展示。
    deduplicated_revisions = list(
        {
            item["revision_id"]: item
            for item in revision_rows
            if item.get("revision_id")
        }.values()
    )

    return {
        "version": version,
        "snapshot": snapshot,
        "build_jobs": build_jobs,
        "document_revisions": deduplicated_revisions,
        "documents": metadata_service.list_version_documents(version_id),
    }


@router.get("/graph/versions/{version_id}/visualization")
async def get_graph_visualization(version_id: str) -> Dict[str, Any]:
    """返回前端可直接渲染的图谱可视化数据。"""
    version = metadata_service.get_graph_version(version_id)
    if not version:
        raise HTTPException(status_code=404, detail="图谱版本不存在")
    snapshot_path = version.get("snapshot_path")
    snapshot_data = version.get("snapshot_data")
    if not snapshot_path and not snapshot_data:
        raise HTTPException(status_code=400, detail="当前图谱版本尚未生成快照")
    return graph_version_service.build_visualization_payload(snapshot_path, snapshot_data)


@router.get("/graph/versions/diff")
async def get_graph_diff(
    left: str = Query(..., description="左侧版本 ID"),
    right: str = Query(..., description="右侧版本 ID"),
) -> Dict[str, Any]:
    """比较两个图谱版本的差异。"""
    left_version = metadata_service.get_graph_version(left)
    right_version = metadata_service.get_graph_version(right)
    if not left_version or not right_version:
        raise HTTPException(status_code=404, detail="待比较的图谱版本不存在")
    if (
        not left_version.get("snapshot_path")
        and not left_version.get("snapshot_data")
    ) or (
        not right_version.get("snapshot_path")
        and not right_version.get("snapshot_data")
    ):
        raise HTTPException(status_code=400, detail="待比较版本缺少快照")

    return graph_version_service.build_diff(
        left_version["snapshot_path"],
        right_version["snapshot_path"],
        left_version.get("snapshot_data"),
        right_version.get("snapshot_data"),
    )


@router.post("/graph/versions/{version_id}/activate")
async def activate_graph_version(
    version_id: str,
    request: ActivateVersionRequest,
) -> Dict[str, Any]:
    """激活指定图谱版本。"""
    if not request.activate:
        return {"status": "skipped", "version_id": version_id}
    return _restore_and_activate_version(version_id)


@router.post("/graph/versions/{version_id}/rollback")
async def rollback_graph_version(version_id: str) -> Dict[str, Any]:
    """回滚到指定图谱版本。"""
    try:
        result = admin_build_service.rollback_to_version(version_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {
        "status": "ok",
        "version_id": version_id,
        **result,
    }


@router.delete("/graph/versions/{version_id}")
async def delete_graph_version(version_id: str) -> Dict[str, Any]:
    """删除指定图谱版本。"""
    try:
        result = admin_build_service.delete_version(version_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {
        "status": "ok",
        **result,
    }


@router.post("/graph/versions/{version_id}/rebuild-communities")
async def rebuild_graph_version_communities(version_id: str) -> Dict[str, Any]:
    """手动重构当前激活版本的社区结构。"""
    try:
        result = admin_build_service.rebuild_active_version_communities(version_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {
        "status": "ok",
        **result,
    }


@router.get("/corrections")
async def list_corrections() -> Dict[str, List[Dict[str, Any]]]:
    """返回人工修正规则列表。"""
    return {
        "items": metadata_service.list_correction_rules(),
    }


@router.post("/corrections")
async def create_correction(request: CorrectionRuleCreateRequest) -> Dict[str, Any]:
    """新增人工修正规则。"""
    try:
        rule = metadata_service.create_correction_rule(
            rule_type=request.rule_type,
            title=request.title,
            content=request.content,
            scope_type=request.scope_type,
            scope_id=request.scope_id,
            enabled=request.enabled,
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return rule


@router.get("/logs/backend", response_model=LogResponse)
async def read_backend_logs(lines: Optional[int] = None) -> LogResponse:
    """读取后端日志。"""
    return _read_log_file(GRAPH_ADMIN_BACKEND_LOG_PATH, lines)


@router.get("/logs/frontend", response_model=LogResponse)
async def read_frontend_logs(lines: Optional[int] = None) -> LogResponse:
    """读取前端日志。"""
    return _read_log_file(GRAPH_ADMIN_FRONTEND_LOG_PATH, lines)


@router.get("/ops/processes")
async def list_admin_processes() -> Dict[str, List[Dict[str, Any]]]:
    """返回后台可管理服务的运行状态。"""
    return {"items": admin_ops_service.list_processes()}


@router.post("/ops/actions")
async def trigger_admin_action(request: AdminActionRequest) -> Dict[str, Any]:
    """执行后台服务启动或关闭。"""
    try:
        return admin_ops_service.control_process(
            target=request.target,
            action=request.action,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/ops/reset")
async def reset_admin_state(request: AdminResetRequest) -> Dict[str, Any]:
    """清空图数据库、元数据库与缓存。"""
    if not request.confirm:
        raise HTTPException(status_code=400, detail="请先确认清空操作")
    try:
        return admin_ops_service.reset_all_state()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc)) from exc


def _create_build(build_type: str, request: BuildRequest) -> Dict[str, Any]:
    """统一创建后台构建任务。"""
    try:
        return admin_build_service.trigger_build(
            build_type=build_type,
            version_name=request.version_name,
            revision_ids=request.document_revision_ids,
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc)) from exc


def _restore_and_activate_version(version_id: str) -> Dict[str, Any]:
    """将指定版本恢复到当前图谱并切换为激活状态。"""
    try:
        result = admin_build_service.rollback_to_version(version_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {
        "status": "ok",
        "version_id": version_id,
        **result,
    }


def _read_log_file(path: str, lines: Optional[int]) -> LogResponse:
    """读取日志文件尾部内容。"""
    max_lines = min(lines or GRAPH_ADMIN_MAX_LOG_LINES, GRAPH_ADMIN_MAX_LOG_LINES)
    log_path = Path(path).expanduser() if path else None
    if not log_path:
        return LogResponse(path=None, lines=["未配置日志路径"])
    if not log_path.exists():
        return LogResponse(path=str(log_path), lines=["日志文件不存在"])

    content = log_path.read_text(encoding="utf-8", errors="ignore").splitlines()
    return LogResponse(
        path=str(log_path),
        lines=content[-max_lines:],
    )


def _check_neo4j_connectivity() -> bool:
    """检查 Neo4j 连通性。"""
    try:
        driver = get_db_manager().get_driver()
        driver.verify_connectivity()
        return True
    except Exception:  # noqa: BLE001
        return False
