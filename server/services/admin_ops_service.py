"""图谱后台运维操作服务。"""

from __future__ import annotations

import os
import shutil
import signal
import subprocess
from pathlib import Path
from typing import Any, Dict, List

from graphrag_agent.config.settings import (
    CACHE_DIR,
    GRAPH_ADMIN_BACKEND_LOG_PATH,
    GRAPH_ADMIN_BUILD_LOG_DIR,
    GRAPH_ADMIN_FRONTEND_LOG_PATH,
    GRAPH_ADMIN_RUNTIME_DIR,
    GRAPH_ADMIN_SNAPSHOT_DIR,
    GRAPH_ADMIN_UPLOAD_DIR,
    PROJECT_ROOT,
)
from server_config.database import get_db_manager
from services.admin_metadata_service import metadata_service


class AdminOpsService:
    """负责后台中的运维操作。"""

    def __init__(self) -> None:
        self._project_root = PROJECT_ROOT
        self._runtime_root_dir = GRAPH_ADMIN_RUNTIME_DIR
        self._runtime_log_dir = self._runtime_root_dir / "logs"
        self._runtime_log_dir.mkdir(parents=True, exist_ok=True)
        self._service_specs = {
            "backend": {
                "label": "主后端",
                "make_target": "start-backend",
                "match_patterns": [
                    "uvicorn main:app --reload --port 8000",
                    "python -m uvicorn main:app --reload --port 8000",
                ],
                "log_path": self._resolve_backend_log_path(),
                "stoppable": True,
            },
            "frontend": {
                "label": "主前端",
                "make_target": "start-frontend",
                "match_patterns": [
                    "streamlit run app.py",
                    "streamlit run frontend/app.py",
                ],
                "log_path": self._resolve_frontend_log_path(),
                "stoppable": True,
            },
        }

    def list_processes(self) -> List[Dict[str, Any]]:
        """返回各服务运行状态。"""
        process_table = self._collect_process_table()
        results: List[Dict[str, Any]] = []
        for target, spec in self._service_specs.items():
            matched = self._match_processes(process_table, spec["match_patterns"])
            results.append(
                {
                    "target": target,
                    "label": spec["label"],
                    "status": "running" if matched else "stopped",
                    "running": bool(matched),
                    "pids": [item["pid"] for item in matched],
                    "command_lines": [item["command"] for item in matched],
                    "stoppable": bool(spec.get("stoppable", True)),
                    "note": spec.get("note", ""),
                    "log_path": str(spec["log_path"]),
                }
            )
        return results

    def control_process(self, *, target: str, action: str) -> Dict[str, Any]:
        """控制指定服务进程。"""
        if target not in self._service_specs:
            raise ValueError(f"不支持的服务目标: {target}")
        if action not in {"start", "stop"}:
            raise ValueError(f"不支持的动作: {action}")

        if action == "start":
            return self._start_process(target)
        return self._stop_process(target)

    def reset_all_state(self) -> Dict[str, Any]:
        """清空图数据库、元数据库与缓存目录。"""
        cleared_indexes = self._clear_neo4j()
        metadata_cleared = self._clear_metadata_db()
        removed_paths = self._clear_cache_and_artifacts()
        return {
            "status": "ok",
            "neo4j_indexes_removed": cleared_indexes,
            "metadata_cleared": metadata_cleared,
            "removed_paths": removed_paths,
        }

    def _start_process(self, target: str) -> Dict[str, Any]:
        """启动指定服务。"""
        spec = self._service_specs[target]
        if self._match_processes(self._collect_process_table(), spec["match_patterns"]):
            return {
                "status": "already_running",
                "target": target,
                "message": f"{spec['label']} 已经在运行。",
            }

        return self._spawn_make_target(
            target=spec["make_target"],
            log_path=spec["log_path"],
        ) | {"target": target}

    def _stop_process(self, target: str) -> Dict[str, Any]:
        """停止指定服务。"""
        spec = self._service_specs[target]
        if not spec.get("stoppable", True):
            raise ValueError(spec.get("note") or "该服务不支持关闭")

        matched = self._match_processes(self._collect_process_table(), spec["match_patterns"])
        if not matched:
            return {
                "status": "already_stopped",
                "target": target,
                "message": f"{spec['label']} 当前未运行。",
            }

        stopped_pids: List[int] = []
        for item in matched:
            pid = item["pid"]
            try:
                os.kill(pid, signal.SIGTERM)
                stopped_pids.append(pid)
            except ProcessLookupError:
                continue

        return {
            "status": "stopping",
            "target": target,
            "stopped_pids": stopped_pids,
        }

    def _spawn_make_target(self, *, target: str, log_path: Path) -> Dict[str, Any]:
        """以后台进程方式启动 make 目标。"""
        log_path.parent.mkdir(parents=True, exist_ok=True)
        handle = open(log_path, "a", encoding="utf-8")
        process = subprocess.Popen(  # noqa: S603
            ["make", target],
            cwd=str(self._project_root),
            stdout=handle,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
            env=os.environ.copy(),
        )
        handle.close()
        return {
            "status": "started",
            "make_target": target,
            "pid": process.pid,
            "log_path": str(log_path),
        }

    def _collect_process_table(self) -> List[Dict[str, Any]]:
        """采集当前系统进程列表。"""
        completed = subprocess.run(  # noqa: S603
            ["ps", "-eo", "pid=,args="],
            cwd=str(self._project_root),
            capture_output=True,
            text=True,
            check=True,
        )
        process_rows: List[Dict[str, Any]] = []
        for line in completed.stdout.splitlines():
            row = line.strip()
            if not row:
                continue
            parts = row.split(maxsplit=1)
            if len(parts) != 2:
                continue
            pid_str, command = parts
            if not pid_str.isdigit():
                continue
            process_rows.append({"pid": int(pid_str), "command": command})
        return process_rows

    def _match_processes(
        self,
        process_table: List[Dict[str, Any]],
        patterns: List[str],
    ) -> List[Dict[str, Any]]:
        """按命令关键字匹配目标进程。"""
        matched: List[Dict[str, Any]] = []
        for row in process_table:
            command = row["command"]
            if "codex-linux-sandbox" in command:
                continue
            if any(pattern in command for pattern in patterns):
                matched.append(row)
        return matched

    def _clear_neo4j(self) -> List[str]:
        """清空 Neo4j 数据与常用索引。"""
        driver = get_db_manager().get_driver()
        dropped_indexes: List[str] = []
        index_names = ["entity_embedding", "chunk_embedding", "vector"]

        with driver.session() as session:
            session.run("MATCH (n) DETACH DELETE n")
            for index_name in index_names:
                session.run(f"DROP INDEX {index_name} IF EXISTS")
                dropped_indexes.append(index_name)
        return dropped_indexes

    def _clear_metadata_db(self) -> bool:
        """清空后台元数据库表内容。"""
        if not metadata_service.available:
            return False

        table_names = [
            "admin_build_job_revisions",
            "admin_build_jobs",
            "admin_graph_versions",
            "admin_document_revisions",
            "admin_documents",
            "admin_correction_rules",
        ]
        with metadata_service._get_conn() as conn:  # noqa: SLF001
            with conn.cursor() as cur:
                for table_name in table_names:
                    cur.execute(f"TRUNCATE TABLE {table_name} CASCADE")
        return True

    def _clear_cache_and_artifacts(self) -> List[str]:
        """清空缓存与后台生成产物目录。"""
        paths = [
            CACHE_DIR,
            GRAPH_ADMIN_BUILD_LOG_DIR,
            GRAPH_ADMIN_SNAPSHOT_DIR,
            GRAPH_ADMIN_UPLOAD_DIR,
            self._runtime_log_dir,
        ]
        removed: List[str] = []
        for path in paths:
            path_obj = Path(path)
            if path_obj.exists():
                shutil.rmtree(path_obj, ignore_errors=True)
                removed.append(str(path_obj))

        self._runtime_root_dir.mkdir(parents=True, exist_ok=True)
        GRAPH_ADMIN_BUILD_LOG_DIR.mkdir(parents=True, exist_ok=True)
        self._runtime_log_dir.mkdir(parents=True, exist_ok=True)
        GRAPH_ADMIN_SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
        GRAPH_ADMIN_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        return removed

    def _resolve_backend_log_path(self) -> Path:
        """解析主后端日志路径。"""
        configured = GRAPH_ADMIN_BACKEND_LOG_PATH.strip()
        if configured:
            return Path(configured).expanduser()
        return self._runtime_log_dir / "backend.log"

    def _resolve_frontend_log_path(self) -> Path:
        """解析主前端日志路径。"""
        configured = GRAPH_ADMIN_FRONTEND_LOG_PATH.strip()
        if configured:
            return Path(configured).expanduser()
        return self._runtime_log_dir / "frontend.log"


admin_ops_service = AdminOpsService()
