"""图谱后台元数据服务。

使用 PostgreSQL 保存图谱后台的文档、版本、构建任务和修正规则信息。
"""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from datetime import datetime
from typing import Any, Dict, Generator, Iterable, List, Optional

from graphrag_agent.config.settings import GRAPH_ADMIN_METADATA_DSN
from graphrag_agent.runtime_logging import emit_runtime_log

try:
    import psycopg
    from psycopg.rows import dict_row
except ModuleNotFoundError:  # pragma: no cover
    psycopg = None
    dict_row = None


class AdminMetadataService:
    """图谱后台元数据库访问层。"""

    def __init__(self) -> None:
        self._dsn = GRAPH_ADMIN_METADATA_DSN
        self._available = bool(self._dsn and psycopg is not None)

    @property
    def available(self) -> bool:
        """当前元数据库是否可用。"""
        return self._available

    @contextmanager
    def _get_conn(self) -> Generator[Any, None, None]:
        """获取 PostgreSQL 连接。"""
        if not self.available:
            raise RuntimeError(
                "图谱后台元数据库未启用，请配置 GRAPH_ADMIN_METADATA_DSN 并安装 psycopg。"
            )

        conn = psycopg.connect(self._dsn, row_factory=dict_row)
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def initialize_schema(self) -> None:
        """初始化后台相关表结构。"""
        if not self.available:
            return

        ddl_statements = [
            """
            CREATE TABLE IF NOT EXISTS admin_documents (
                document_id TEXT PRIMARY KEY,
                file_name TEXT NOT NULL,
                status TEXT NOT NULL,
                latest_revision_id TEXT,
                latest_file_hash TEXT,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS admin_document_revisions (
                revision_id TEXT PRIMARY KEY,
                document_id TEXT NOT NULL REFERENCES admin_documents(document_id) ON DELETE CASCADE,
                file_name TEXT NOT NULL,
                file_path TEXT NOT NULL,
                file_hash TEXT NOT NULL,
                file_size BIGINT NOT NULL DEFAULT 0,
                uploaded_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS admin_graph_versions (
                version_id TEXT PRIMARY KEY,
                version_name TEXT NOT NULL,
                build_type TEXT NOT NULL,
                status TEXT NOT NULL,
                snapshot_path TEXT,
                snapshot_data TEXT,
                base_version_id TEXT,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                activated_at TIMESTAMPTZ,
                entity_count INTEGER NOT NULL DEFAULT 0,
                relation_count INTEGER NOT NULL DEFAULT 0,
                document_count INTEGER NOT NULL DEFAULT 0,
                is_active BOOLEAN NOT NULL DEFAULT FALSE
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS admin_build_jobs (
                job_id TEXT PRIMARY KEY,
                version_id TEXT NOT NULL REFERENCES admin_graph_versions(version_id) ON DELETE CASCADE,
                job_type TEXT NOT NULL,
                status TEXT NOT NULL,
                message TEXT,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                started_at TIMESTAMPTZ,
                finished_at TIMESTAMPTZ,
                log_path TEXT
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS admin_build_job_revisions (
                job_id TEXT NOT NULL REFERENCES admin_build_jobs(job_id) ON DELETE CASCADE,
                revision_id TEXT NOT NULL REFERENCES admin_document_revisions(revision_id) ON DELETE CASCADE,
                PRIMARY KEY (job_id, revision_id)
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS admin_correction_rules (
                rule_id TEXT PRIMARY KEY,
                rule_type TEXT NOT NULL,
                title TEXT NOT NULL,
                content TEXT NOT NULL,
                scope_type TEXT NOT NULL,
                scope_id TEXT,
                enabled BOOLEAN NOT NULL DEFAULT TRUE,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """,
        ]

        with self._get_conn() as conn:
            with conn.cursor() as cur:
                for ddl in ddl_statements:
                    cur.execute(ddl)
                # 兼容已存在的旧表结构，补齐新增快照字段。
                cur.execute(
                    "ALTER TABLE admin_graph_versions ADD COLUMN IF NOT EXISTS snapshot_data TEXT"
                )
        emit_runtime_log("admin.metadata.schema_ready")

    def create_or_update_document(
        self,
        *,
        file_name: str,
        file_path: str,
        file_hash: str,
        file_size: int,
    ) -> Dict[str, Any]:
        """创建文档与对应的 revision。"""
        now = datetime.utcnow()
        document_id = f"doc_{uuid.uuid4().hex[:12]}"
        revision_id = f"rev_{uuid.uuid4().hex[:12]}"

        with self._get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT document_id FROM admin_documents
                    WHERE file_name = %s
                    ORDER BY created_at ASC
                    LIMIT 1
                    """,
                    (file_name,),
                )
                existing = cur.fetchone()
                if existing:
                    document_id = existing["document_id"]
                    cur.execute(
                        """
                        UPDATE admin_documents
                        SET status = %s,
                            latest_revision_id = %s,
                            latest_file_hash = %s,
                            updated_at = %s
                        WHERE document_id = %s
                        """,
                        ("uploaded", revision_id, file_hash, now, document_id),
                    )
                else:
                    cur.execute(
                        """
                        INSERT INTO admin_documents (
                            document_id, file_name, status, latest_revision_id,
                            latest_file_hash, created_at, updated_at
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                        """,
                        (
                            document_id,
                            file_name,
                            "uploaded",
                            revision_id,
                            file_hash,
                            now,
                            now,
                        ),
                    )

                cur.execute(
                    """
                    INSERT INTO admin_document_revisions (
                        revision_id, document_id, file_name, file_path,
                        file_hash, file_size, uploaded_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        revision_id,
                        document_id,
                        file_name,
                        file_path,
                        file_hash,
                        file_size,
                        now,
                    ),
                )

        return {
            "document_id": document_id,
            "revision_id": revision_id,
            "file_name": file_name,
            "file_path": file_path,
            "file_hash": file_hash,
            "file_size": file_size,
        }

    def list_documents(self) -> List[Dict[str, Any]]:
        """查询文档列表。"""
        return self._fetchall(
            """
            SELECT document_id, file_name, status, latest_revision_id,
                   latest_file_hash, created_at, updated_at
            FROM admin_documents
            ORDER BY updated_at DESC
            """
        )

    def list_document_revisions(self, document_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """查询文档 revision 列表。"""
        if document_id:
            return self._fetchall(
                """
                SELECT revision_id, document_id, file_name, file_path, file_hash,
                       file_size, uploaded_at
                FROM admin_document_revisions
                WHERE document_id = %s
                ORDER BY uploaded_at DESC
                """,
                (document_id,),
            )
        return self._fetchall(
            """
            SELECT revision_id, document_id, file_name, file_path, file_hash,
                   file_size, uploaded_at
            FROM admin_document_revisions
            ORDER BY uploaded_at DESC
            """
        )

    def get_document_revisions_by_ids(self, revision_ids: Iterable[str]) -> List[Dict[str, Any]]:
        """按 revision_id 列表查询文档版本。"""
        revision_ids = [revision_id for revision_id in revision_ids if revision_id]
        if not revision_ids:
            return []
        placeholders = ", ".join(["%s"] * len(revision_ids))
        return self._fetchall(
            f"""
            SELECT revision_id, document_id, file_name, file_path, file_hash,
                   file_size, uploaded_at
            FROM admin_document_revisions
            WHERE revision_id IN ({placeholders})
            ORDER BY uploaded_at DESC
            """,
            tuple(revision_ids),
        )

    def create_graph_version(
        self,
        *,
        version_name: str,
        build_type: str,
        base_version_id: Optional[str],
        document_count: int,
    ) -> Dict[str, Any]:
        """创建图谱版本记录。"""
        version_id = f"gv_{uuid.uuid4().hex[:12]}"
        now = datetime.utcnow()
        self._execute(
            """
            INSERT INTO admin_graph_versions (
                version_id, version_name, build_type, status,
                base_version_id, created_at, document_count, is_active
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, FALSE)
            """,
            (
                version_id,
                version_name,
                build_type,
                "pending",
                base_version_id,
                now,
                document_count,
            ),
        )
        return self.get_graph_version(version_id) or {}

    def update_graph_version(self, version_id: str, **fields: Any) -> None:
        """更新图谱版本记录。"""
        self._update_by_id("admin_graph_versions", "version_id", version_id, fields)

    def get_graph_version(self, version_id: str) -> Optional[Dict[str, Any]]:
        """查询单个图谱版本。"""
        return self._fetchone(
            """
            SELECT version_id, version_name, build_type, status, snapshot_path, snapshot_data,
                   base_version_id, created_at, activated_at, entity_count,
                   relation_count, document_count, is_active
            FROM admin_graph_versions
            WHERE version_id = %s
            """,
            (version_id,),
        )

    def list_graph_versions(self) -> List[Dict[str, Any]]:
        """查询图谱版本列表。"""
        return self._fetchall(
            """
            SELECT version_id, version_name, build_type, status, snapshot_path,
                   base_version_id, created_at, activated_at, entity_count,
                   relation_count, document_count, is_active
            FROM admin_graph_versions
            ORDER BY created_at DESC
            """
        )

    def get_active_graph_version(self) -> Optional[Dict[str, Any]]:
        """查询当前激活图谱版本。"""
        return self._fetchone(
            """
            SELECT version_id, version_name, build_type, status, snapshot_path,
                   base_version_id, created_at, activated_at, entity_count,
                   relation_count, document_count, is_active
            FROM admin_graph_versions
            WHERE is_active = TRUE
            ORDER BY activated_at DESC NULLS LAST, created_at DESC
            LIMIT 1
            """
        )

    def delete_graph_version(self, version_id: str) -> Optional[Dict[str, Any]]:
        """删除指定图谱版本元数据并返回被删除记录。"""
        version = self.get_graph_version(version_id)
        if not version:
            return None
        self._execute(
            """
            DELETE FROM admin_graph_versions
            WHERE version_id = %s
            """,
            (version_id,),
        )
        return version

    def activate_graph_version(self, version_id: str) -> None:
        """将指定图谱版本切换为激活状态。"""
        now = datetime.utcnow()
        with self._get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("UPDATE admin_graph_versions SET is_active = FALSE")
                cur.execute(
                    """
                    UPDATE admin_graph_versions
                    SET is_active = TRUE, status = %s, activated_at = %s
                    WHERE version_id = %s
                    """,
                    ("active", now, version_id),
                )

    def create_build_job(
        self,
        *,
        version_id: str,
        job_type: str,
        log_path: Optional[str],
        revision_ids: Optional[Iterable[str]] = None,
    ) -> Dict[str, Any]:
        """创建构建任务。"""
        job_id = f"job_{uuid.uuid4().hex[:12]}"
        now = datetime.utcnow()
        with self._get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO admin_build_jobs (
                        job_id, version_id, job_type, status,
                        created_at, log_path
                    ) VALUES (%s, %s, %s, %s, %s, %s)
                    """,
                    (
                        job_id,
                        version_id,
                        job_type,
                        "pending",
                        now,
                        log_path,
                    ),
                )
                for revision_id in revision_ids or []:
                    cur.execute(
                        """
                        INSERT INTO admin_build_job_revisions (job_id, revision_id)
                        VALUES (%s, %s)
                        ON CONFLICT DO NOTHING
                        """,
                        (job_id, revision_id),
                    )
        return self.get_build_job(job_id) or {}

    def update_build_job(self, job_id: str, **fields: Any) -> None:
        """更新构建任务。"""
        self._update_by_id("admin_build_jobs", "job_id", job_id, fields)

    def get_build_job(self, job_id: str) -> Optional[Dict[str, Any]]:
        """查询单个构建任务。"""
        return self._fetchone(
            """
            SELECT job_id, version_id, job_type, status, message,
                   created_at, started_at, finished_at, log_path
            FROM admin_build_jobs
            WHERE job_id = %s
            """,
            (job_id,),
        )

    def list_build_jobs(self) -> List[Dict[str, Any]]:
        """查询构建任务列表。"""
        return self._fetchall(
            """
            SELECT job_id, version_id, job_type, status, message,
                   created_at, started_at, finished_at, log_path
            FROM admin_build_jobs
            ORDER BY created_at DESC
            """
        )

    def list_build_jobs_paginated(
        self,
        *,
        page: int,
        page_size: int,
        keyword: Optional[str] = None,
        status: Optional[str] = None,
    ) -> Dict[str, Any]:
        """分页查询构建任务列表。

        Args:
            page: 当前页码，从 1 开始。
            page_size: 每页条数。
            keyword: 可选关键字，匹配任务 ID、版本 ID、类型、状态或消息。
            status: 可选状态过滤条件。

        Returns:
            包含分页结果和统计信息的字典。
        """
        normalized_page = max(1, int(page))
        normalized_page_size = max(1, min(int(page_size), 200))
        where_sql, params = self._build_build_job_filters(
            keyword=keyword,
            status=status,
        )

        # 使用数据库分页，避免后台监控一次性加载全部任务记录。
        total_row = self._fetchone(
            f"""
            SELECT COUNT(*) AS total
            FROM admin_build_jobs
            {where_sql}
            """,
            params,
        ) or {"total": 0}
        total = int(total_row.get("total") or 0)
        total_pages = max(1, (total + normalized_page_size - 1) // normalized_page_size)
        current_page = min(normalized_page, total_pages)
        offset = (current_page - 1) * normalized_page_size

        items = self._fetchall(
            f"""
            SELECT job_id, version_id, job_type, status, message,
                   created_at, started_at, finished_at, log_path
            FROM admin_build_jobs
            {where_sql}
            ORDER BY created_at DESC
            LIMIT %s OFFSET %s
            """,
            (*params, normalized_page_size, offset),
        )
        return {
            "items": items,
            "total": total,
            "page": current_page,
            "page_size": normalized_page_size,
            "total_pages": total_pages,
            "keyword": keyword,
            "status": status,
        }

    def list_build_jobs_by_version(self, version_id: str) -> List[Dict[str, Any]]:
        """查询指定图谱版本关联的构建任务。"""
        return self._fetchall(
            """
            SELECT job_id, version_id, job_type, status, message,
                   created_at, started_at, finished_at, log_path
            FROM admin_build_jobs
            WHERE version_id = %s
            ORDER BY created_at DESC
            """,
            (version_id,),
        )

    def list_job_revisions(self, job_id: str) -> List[Dict[str, Any]]:
        """查询指定构建任务关联的文档 revision。"""
        return self._fetchall(
            """
            SELECT
                r.revision_id,
                r.document_id,
                r.file_name,
                r.file_path,
                r.file_hash,
                r.file_size,
                r.uploaded_at
            FROM admin_build_job_revisions AS jr
            JOIN admin_document_revisions AS r
              ON jr.revision_id = r.revision_id
            WHERE jr.job_id = %s
            ORDER BY r.uploaded_at DESC
            """,
            (job_id,),
        )

    def _build_build_job_filters(
        self,
        *,
        keyword: Optional[str],
        status: Optional[str],
    ) -> tuple[str, tuple[Any, ...]]:
        """构造构建任务筛选条件。"""
        conditions: List[str] = []
        params: List[Any] = []

        if keyword:
            fuzzy_keyword = f"%{keyword.strip()}%"
            if fuzzy_keyword != "%%":
                conditions.append(
                    """
                    (
                        job_id ILIKE %s
                        OR version_id ILIKE %s
                        OR job_type ILIKE %s
                        OR status ILIKE %s
                        OR COALESCE(message, '') ILIKE %s
                    )
                    """
                )
                params.extend([fuzzy_keyword] * 5)

        if status:
            conditions.append("status = %s")
            params.append(status)

        if not conditions:
            return "", tuple()
        return "WHERE " + " AND ".join(conditions), tuple(params)

    def list_version_documents(self, version_id: str) -> List[Dict[str, Any]]:
        """查询指定图谱版本关联的文档与 revision 信息。"""
        return self._fetchall(
            """
            SELECT DISTINCT
                d.document_id,
                d.file_name AS document_name,
                d.status AS document_status,
                d.latest_revision_id,
                r.revision_id,
                r.file_name,
                r.file_hash,
                r.file_size,
                r.uploaded_at
            FROM admin_build_jobs AS j
            JOIN admin_build_job_revisions AS jr
              ON j.job_id = jr.job_id
            JOIN admin_document_revisions AS r
              ON jr.revision_id = r.revision_id
            JOIN admin_documents AS d
              ON r.document_id = d.document_id
            WHERE j.version_id = %s
            ORDER BY r.uploaded_at DESC
            """,
            (version_id,),
        )

    def create_correction_rule(
        self,
        *,
        rule_type: str,
        title: str,
        content: str,
        scope_type: str,
        scope_id: Optional[str],
        enabled: bool,
    ) -> Dict[str, Any]:
        """创建人工修正规则。"""
        rule_id = f"rule_{uuid.uuid4().hex[:12]}"
        now = datetime.utcnow()
        self._execute(
            """
            INSERT INTO admin_correction_rules (
                rule_id, rule_type, title, content, scope_type,
                scope_id, enabled, created_at, updated_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                rule_id,
                rule_type,
                title,
                content,
                scope_type,
                scope_id,
                enabled,
                now,
                now,
            ),
        )
        return self._fetchone(
            """
            SELECT rule_id, rule_type, title, content, scope_type,
                   scope_id, enabled, created_at, updated_at
            FROM admin_correction_rules
            WHERE rule_id = %s
            """,
            (rule_id,),
        ) or {}

    def list_correction_rules(self) -> List[Dict[str, Any]]:
        """查询修正规则列表。"""
        return self._fetchall(
            """
            SELECT rule_id, rule_type, title, content, scope_type,
                   scope_id, enabled, created_at, updated_at
            FROM admin_correction_rules
            ORDER BY updated_at DESC
            """
        )

    def _fetchall(
        self,
        sql: str,
        params: tuple[Any, ...] = (),
    ) -> List[Dict[str, Any]]:
        if not self.available:
            return []
        with self._get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                return list(cur.fetchall())

    def _fetchone(
        self,
        sql: str,
        params: tuple[Any, ...] = (),
    ) -> Optional[Dict[str, Any]]:
        if not self.available:
            return None
        with self._get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                return cur.fetchone()

    def _execute(self, sql: str, params: tuple[Any, ...] = ()) -> None:
        if not self.available:
            raise RuntimeError("图谱后台元数据库不可用")
        with self._get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, params)

    def _update_by_id(
        self,
        table_name: str,
        id_column: str,
        item_id: str,
        fields: Dict[str, Any],
    ) -> None:
        if not fields:
            return
        assignments = []
        values: List[Any] = []
        for key, value in fields.items():
            assignments.append(f"{key} = %s")
            values.append(value)
        values.append(item_id)
        self._execute(
            f"UPDATE {table_name} SET {', '.join(assignments)} WHERE {id_column} = %s",
            tuple(values),
        )


metadata_service = AdminMetadataService()
