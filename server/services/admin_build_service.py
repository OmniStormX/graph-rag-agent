"""图谱后台构建服务。"""

from __future__ import annotations

import hashlib
import json
import threading
import traceback
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
import shutil
from typing import Any, Dict, List, Optional

from graphrag_agent.config.settings import (
    FILES_DIR,
    GRAPH_ADMIN_BUILD_LOG_DIR,
    GRAPH_ADMIN_UPLOAD_DIR,
)
from graphrag_agent.runtime_logging import emit_runtime_log
from services.admin_metadata_service import metadata_service
from services.graph_version_service import graph_version_service


class AdminBuildService:
    """负责上传文档、触发构建和回滚版本。"""

    def __init__(self) -> None:
        self._job_threads: Dict[str, threading.Thread] = {}
        self._job_runtime_state: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.RLock()
        GRAPH_ADMIN_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
        GRAPH_ADMIN_BUILD_LOG_DIR.mkdir(parents=True, exist_ok=True)
        FILES_DIR.mkdir(parents=True, exist_ok=True)

    def save_uploaded_file(self, *, file_name: str, content: bytes) -> Dict[str, Any]:
        """保存上传文件并创建文档 revision。"""
        if not metadata_service.available:
            raise RuntimeError("后台元数据库不可用，无法保存上传文件。")

        safe_name = Path(file_name).name
        content_hash = hashlib.sha256(content).hexdigest()
        target_path = GRAPH_ADMIN_UPLOAD_DIR / f"{content_hash[:12]}_{safe_name}"
        target_path.write_bytes(content)

        live_path = FILES_DIR / safe_name
        live_path = self._sync_content_to_live_path(
            target_path=target_path,
            preferred_path=live_path,
            content_hash=content_hash,
        )

        metadata = metadata_service.create_or_update_document(
            file_name=safe_name,
            file_path=str(target_path),
            file_hash=content_hash,
            file_size=len(content),
        )
        emit_runtime_log(
            "admin.document.uploaded",
            file_name=safe_name,
            document_id=metadata["document_id"],
            revision_id=metadata["revision_id"],
        )
        return {
            **metadata,
            "live_path": str(live_path),
        }

    def trigger_build(
        self,
        *,
        build_type: str,
        version_name: Optional[str],
        revision_ids: Optional[List[str]],
    ) -> Dict[str, Any]:
        """触发全量或增量构建。"""
        if not metadata_service.available:
            raise RuntimeError("后台元数据库不可用，无法创建构建任务。")

        active_version = metadata_service.get_active_graph_version()
        document_count = self._count_files_in_runtime_dir() if build_type == "full_rebuild" else len(revision_ids or [])
        version = metadata_service.create_graph_version(
            version_name=version_name or f"{build_type}_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}",
            build_type=build_type,
            base_version_id=active_version["version_id"] if active_version else None,
            document_count=document_count,
        )
        log_path = str((GRAPH_ADMIN_BUILD_LOG_DIR / f"{version['version_id']}.log").resolve())
        job = metadata_service.create_build_job(
            version_id=version["version_id"],
            job_type=build_type,
            log_path=log_path,
            revision_ids=revision_ids or [],
        )

        worker = threading.Thread(
            target=self._run_build_job,
            kwargs={
                "job_id": job["job_id"],
                "version_id": version["version_id"],
                "build_type": build_type,
                "revision_ids": revision_ids or [],
                "log_path": log_path,
            },
            daemon=True,
        )
        with self._lock:
            self._job_threads[job["job_id"]] = worker
        worker.start()
        return {
            "job": job,
            "version": version,
        }

    def rollback_to_version(self, version_id: str) -> Dict[str, Any]:
        """回滚到指定图谱版本。"""
        version = metadata_service.get_graph_version(version_id)
        if not version:
            raise ValueError(f"未找到图谱版本: {version_id}")
        snapshot_path = version.get("snapshot_path")
        snapshot_data = version.get("snapshot_data")
        if not snapshot_path and not snapshot_data:
            raise ValueError(f"图谱版本 {version_id} 缺少快照，无法回滚")

        restore_result = graph_version_service.restore_snapshot(snapshot_path, snapshot_data)
        metadata_service.activate_graph_version(version_id)
        metadata_service.update_graph_version(version_id, status="active")
        emit_runtime_log(
            "admin.graph.rollback",
            version_id=version_id,
            node_count=restore_result["node_count"],
            relation_count=restore_result["relation_count"],
        )
        return restore_result

    def rebuild_active_version_communities(self, version_id: str) -> Dict[str, Any]:
        """基于当前激活图谱的节点与关系手动重构社区。

        说明：
            社区结构属于派生数据，允许后台在确认节点与关系已经稳定后，
            对当前激活版本执行一次手动社区重建，并同步刷新该版本快照。

        Args:
            version_id: 需要重构社区的图谱版本 ID。

        Returns:
            Dict[str, Any]: 社区重构后的摘要信息。
        """
        version = metadata_service.get_graph_version(version_id)
        if not version:
            raise ValueError(f"未找到图谱版本: {version_id}")

        active_version = metadata_service.get_active_graph_version()
        if not active_version or active_version.get("version_id") != version_id:
            active_label = active_version.get("version_name") if active_version else "无"
            raise ValueError(
                "仅支持对当前激活版本手动重构社区，请先激活目标版本后再执行。"
                f" 当前激活版本: {active_label}"
            )

        self._rebuild_live_graph_communities()
        snapshot_info = graph_version_service.export_current_graph(version_id)
        metadata_service.update_graph_version(
            version_id,
            status="active",
            snapshot_path=snapshot_info["snapshot_path"],
            snapshot_data=snapshot_info["snapshot_data"],
            entity_count=snapshot_info["entity_count"],
            relation_count=snapshot_info["relation_count"],
        )

        community_count = self._count_community_nodes()
        emit_runtime_log(
            "admin.graph.community_rebuilt",
            version_id=version_id,
            version_name=version.get("version_name"),
            community_count=community_count,
            node_count=snapshot_info["entity_count"],
            relation_count=snapshot_info["relation_count"],
        )
        return {
            "version_id": version_id,
            "version_name": version.get("version_name"),
            "community_count": community_count,
            "node_count": snapshot_info["entity_count"],
            "relation_count": snapshot_info["relation_count"],
            "snapshot_path": snapshot_info["snapshot_path"],
        }

    def delete_version(self, version_id: str) -> Dict[str, Any]:
        """删除指定图谱版本及其快照。"""
        version = metadata_service.get_graph_version(version_id)
        if not version:
            raise ValueError(f"未找到图谱版本: {version_id}")
        if version.get("is_active"):
            raise ValueError("当前激活版本不允许删除，请先切换到其他版本。")

        graph_version_service.delete_snapshot(version.get("snapshot_path"))
        metadata_service.delete_graph_version(version_id)
        emit_runtime_log(
            "admin.graph.version_deleted",
            version_id=version_id,
            snapshot_path=version.get("snapshot_path"),
        )
        return {
            "deleted": True,
            "version_id": version_id,
        }

    def _rebuild_live_graph_communities(self) -> None:
        """对当前在线图谱执行社区清理与重建。"""
        from graphrag_agent.integrations.build.build_index_and_community import (
            IndexCommunityBuilder,
        )
        from server_config.database import get_db_manager

        graph = get_db_manager().get_graph()

        # 先清理旧社区派生结构，避免新旧社区结果叠加。
        graph.query(
            """
            MATCH (e:`__Entity__`)-[r:IN_COMMUNITY]->(:`__Community__`)
            DELETE r
            """
        )
        graph.query(
            """
            MATCH (c:`__Community__`)
            DETACH DELETE c
            """
        )
        graph.query(
            """
            MATCH (e:`__Entity__`)
            REMOVE e.communities, e.communityIds
            """
        )

        builder = IndexCommunityBuilder()
        builder.process()

    def _count_community_nodes(self) -> int:
        """统计当前在线图谱中的社区节点数。"""
        from server_config.database import get_db_manager

        graph = get_db_manager().get_graph()
        rows = graph.query(
            """
            MATCH (c:`__Community__`)
            RETURN count(c) AS community_count
            """
        )
        if not rows:
            return 0
        return int(rows[0].get("community_count") or 0)

    def _run_build_job(
        self,
        *,
        job_id: str,
        version_id: str,
        build_type: str,
        revision_ids: List[str],
        log_path: str,
    ) -> None:
        progress_handler = self._create_progress_handler(job_id=job_id, log_path=log_path)
        self._update_job_progress(
            job_id,
            status="running",
            message="构建任务开始执行",
            started_at=datetime.utcnow(),
        )
        metadata_service.update_graph_version(version_id, status="building")
        self._append_log(log_path, f"[{datetime.utcnow().isoformat()}] 开始执行 {build_type} 构建")

        try:
            live_paths: List[Path] = []
            if build_type != "full_rebuild":
                self._update_job_progress(
                    job_id,
                    message="同步文档版本到构建目录",
                )
                live_paths = self._sync_revisions_to_files(revision_ids)
            with self._apply_correction_rules(log_path):
                if build_type == "full_rebuild":
                    from graphrag_agent.integrations.build.main import KnowledgeGraphProcessor

                    self._update_job_progress(
                        job_id,
                        message="执行全量重建流程",
                    )
                    self._append_log(log_path, "执行全量重建流程")
                    KnowledgeGraphProcessor(progress_callback=progress_handler).process_all()
                else:
                    from graphrag_agent.integrations.build.incremental_graph_builder import (
                        IncrementalGraphUpdater,
                    )

                    self._update_job_progress(
                        job_id,
                        message="执行指定文件补充构建流程",
                    )
                    self._append_log(log_path, "执行指定文件补充构建流程")
                    updater = IncrementalGraphUpdater(
                        str(FILES_DIR),
                        progress_callback=progress_handler,
                    )
                    if revision_ids:
                        updater.process_selected_files([str(path) for path in live_paths])
                    else:
                        # 未显式选择 revision 时，退回原有目录差量检测逻辑。
                        updater.process_incremental_update()

            self._update_job_progress(
                job_id,
                message="导出图谱快照并更新版本信息",
            )
            snapshot_info = graph_version_service.export_current_graph(version_id)
            metadata_service.update_graph_version(
                version_id,
                status="ready",
                snapshot_path=snapshot_info["snapshot_path"],
                snapshot_data=snapshot_info["snapshot_data"],
                entity_count=snapshot_info["entity_count"],
                relation_count=snapshot_info["relation_count"],
            )
            metadata_service.activate_graph_version(version_id)
            metadata_service.update_graph_version(version_id, status="active")
            self._update_job_progress(
                job_id,
                status="succeeded",
                finished_at=datetime.utcnow(),
                message="构建完成",
            )
            self._append_log(log_path, "构建成功，已生成图谱版本快照")
        except Exception as exc:  # noqa: BLE001
            error_message = f"构建失败: {exc}"
            self._update_job_progress(
                job_id,
                status="failed",
                finished_at=datetime.utcnow(),
                message=error_message,
            )
            metadata_service.update_graph_version(version_id, status="failed")
            self._append_log(log_path, error_message)
            self._append_log(log_path, traceback.format_exc())
            emit_runtime_log(
                "admin.build.failed",
                job_id=job_id,
                version_id=version_id,
                error=str(exc),
            )
        finally:
            with self._lock:
                self._job_threads.pop(job_id, None)
                self._job_runtime_state.pop(job_id, None)

    def _sync_revisions_to_files(self, revision_ids: List[str]) -> List[Path]:
        """将选定 revision 同步到当前文件目录。

        说明：
            为了避免重写现有构图流程，这里只做“将指定 revision 文件同步到 FILES_DIR”
            的最小接入。后台增量构建会优先对这些指定文件做定向补建，而不是扫描整个目录。
        """
        if not revision_ids:
            return []

        synced_paths: List[Path] = []
        revisions = metadata_service.get_document_revisions_by_ids(revision_ids)
        for revision in revisions:
            source_path = Path(revision["file_path"])
            if not source_path.exists():
                continue
            live_path = self._sync_content_to_live_path(
                target_path=source_path,
                preferred_path=FILES_DIR / revision["file_name"],
                content_hash=revision["file_hash"],
            )
            synced_paths.append(live_path)
        return synced_paths

    @contextmanager
    def _apply_correction_rules(self, log_path: str):
        """在构建期间临时将人工修正规则追加到图谱抽取 prompt。"""
        from graphrag_agent.config.prompts import graph_prompts
        from graphrag_agent.integrations.build import build_graph, incremental_graph_builder

        rules = [rule for rule in metadata_service.list_correction_rules() if rule.get("enabled")]
        if not rules:
            yield
            return

        appendix = "\n\n# 人工修正规则\n" + "\n".join(
            [f"- {rule['title']}：{rule['content']}" for rule in rules]
        )
        self._append_log(log_path, f"应用 {len(rules)} 条人工修正规则")

        original_prompt = graph_prompts.system_template_build_graph
        original_build_graph_prompt = build_graph.system_template_build_graph
        original_incremental_prompt = incremental_graph_builder.system_template_build_graph

        patched_prompt = original_prompt + appendix
        graph_prompts.system_template_build_graph = patched_prompt
        build_graph.system_template_build_graph = patched_prompt
        incremental_graph_builder.system_template_build_graph = patched_prompt
        try:
            yield
        finally:
            graph_prompts.system_template_build_graph = original_prompt
            build_graph.system_template_build_graph = original_build_graph_prompt
            incremental_graph_builder.system_template_build_graph = original_incremental_prompt

    def _append_log(self, log_path: str, message: str) -> None:
        Path(log_path).parent.mkdir(parents=True, exist_ok=True)
        with open(log_path, "a", encoding="utf-8") as handle:
            handle.write(message.rstrip() + "\n")

    def _update_job_progress(self, job_id: str, **fields: Any) -> None:
        """统一更新构建任务进度信息。"""
        db_fields = {
            key: value
            for key, value in fields.items()
            if key in {"status", "message", "started_at", "finished_at"}
        }
        extra_fields = {
            key: value
            for key, value in fields.items()
            if key not in {"status", "message", "started_at", "finished_at"}
        }
        if db_fields:
            metadata_service.update_build_job(job_id, **db_fields)
        if extra_fields:
            with self._lock:
                state = self._job_runtime_state.setdefault(job_id, {})
                state.update(extra_fields)
        job = metadata_service.get_build_job(job_id)
        if job:
            self._write_job_status_file(job)

    def _create_progress_handler(self, *, job_id: str, log_path: str):
        """创建构建流程进度回调。

        说明：
            该回调会把结构化进度同步到状态文件，并在阶段消息变化时追加日志。
        """
        def _handler(event: Dict[str, Any]) -> None:
            if not isinstance(event, dict):
                return
            message = str(event.get("message") or "").strip()
            fields: Dict[str, Any] = {
                "message": message or "构建执行中",
            }
            if "progress" in event:
                fields["progress"] = event.get("progress")
            if "stage" in event:
                fields["stage"] = event.get("stage")
            self._update_job_progress(job_id, **fields)

            if message:
                with self._lock:
                    state = self._job_runtime_state.setdefault(job_id, {})
                    if state.get("last_logged_message") == message:
                        return
                    state["last_logged_message"] = message
                self._append_log(log_path, f"[{datetime.utcnow().isoformat()}] {message}")

        return _handler

    def _sync_content_to_live_path(
        self,
        *,
        target_path: Path,
        preferred_path: Path,
        content_hash: str,
    ) -> Path:
        """将文件同步到运行目录，遇到只读同名文件时自动降级处理。"""
        preferred_path.parent.mkdir(parents=True, exist_ok=True)

        # 目标文件不存在时直接写入。
        if not preferred_path.exists():
            shutil.copyfile(target_path, preferred_path)
            return preferred_path

        # 目标文件已存在且内容一致时直接复用，避免重复覆盖。
        existing_hash = hashlib.sha256(preferred_path.read_bytes()).hexdigest()
        if existing_hash == content_hash:
            return preferred_path

        # 同名旧文件不可覆盖时，退化为带 hash 前缀的新文件名。
        fallback_path = preferred_path.with_name(
            f"{content_hash[:12]}_{preferred_path.name}"
        )
        shutil.copyfile(target_path, fallback_path)
        return fallback_path

    def _count_files_in_runtime_dir(self) -> int:
        """统计运行目录中的文件数，用于记录全量构建规模。"""
        return len([path for path in FILES_DIR.rglob("*") if path.is_file()])

    def _write_job_status_file(self, job: Dict[str, Any]) -> None:
        """将任务状态写入本地文件，供后台页面低频轮询、高频本地读取。"""
        log_path = str(job.get("log_path") or "").strip()
        if not log_path:
            return
        with self._lock:
            runtime_state = dict(self._job_runtime_state.get(str(job.get("job_id")), {}))
        status_path = Path(log_path).with_suffix(".status.json")
        payload = {
            "job_id": job.get("job_id"),
            "version_id": job.get("version_id"),
            "job_type": job.get("job_type"),
            "status": job.get("status"),
            "message": job.get("message"),
            "created_at": self._serialize_datetime(job.get("created_at")),
            "started_at": self._serialize_datetime(job.get("started_at")),
            "finished_at": self._serialize_datetime(job.get("finished_at")),
            "log_path": log_path,
            "updated_at": datetime.utcnow().isoformat(),
        }
        for key in ("progress", "stage"):
            if key in runtime_state:
                payload[key] = runtime_state[key]
        status_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _serialize_datetime(self, value: Any) -> Optional[str]:
        """序列化时间字段。"""
        if value is None:
            return None
        if hasattr(value, "isoformat"):
            return value.isoformat()
        return str(value)


admin_build_service = AdminBuildService()
