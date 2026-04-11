"""图谱后台管理系统入口。"""

from __future__ import annotations

import html
import json
import re
import time
from pathlib import Path
from typing import Any, Dict, List

import pandas as pd
import requests
import streamlit as st

from components.knowledge_graph.visualization import visualize_knowledge_graph
from utils.community_graph import (
    build_community_drilldown_visualization,
    build_community_overview_visualization,
)
from utils.admin_api import (
    activate_graph_version,
    create_correction,
    create_full_rebuild,
    create_incremental_build,
    delete_graph_version,
    get_admin_health,
    get_admin_processes,
    get_admin_status,
    get_backend_logs,
    get_builds,
    get_corrections,
    get_documents,
    get_frontend_logs,
    get_graph_diff,
    get_graph_version,
    get_graph_versions,
    get_graph_visualization,
    rebuild_graph_version_communities,
    reset_admin_state,
    rollback_graph_version,
    trigger_admin_action,
    upload_document,
)


def main() -> None:
    """渲染后台管理页面。"""
    st.set_page_config(
        page_title="GraphRAG Admin Console",
        page_icon="🧭",
        layout="wide",
    )
    _inject_admin_styles()
    _init_admin_state()

    try:
        health = get_admin_health()
        status = get_admin_status()
    except requests.RequestException as exc:
        st.error(f"无法连接后台管理接口：{exc}")
        return

    _render_admin_hero(health, status)
    _render_status_header(health, status)

    tabs = st.tabs(
        [
            "概览总览",
            "文档入库",
            "构建调度",
            "版本治理",
            "版本洞察",
            "规则治理",
            "日志运维",
        ]
    )

    with tabs[0]:
        _render_overview(status)
    with tabs[1]:
        _render_upload_tab()
    with tabs[2]:
        _render_build_tab()
    with tabs[3]:
        _render_versions_tab()
    with tabs[4]:
        _render_version_view_tab()
    with tabs[5]:
        _render_corrections_tab()
    with tabs[6]:
        _render_logs_tab()


def _init_admin_state() -> None:
    """初始化后台页面所需会话状态。"""
    st.session_state.setdefault(
        "kg_display_settings",
        {
            "physics_enabled": True,
            "node_size": 22,
            "edge_width": 2,
            "spring_length": 140,
            "gravity": -5000,
        },
    )
    st.session_state.setdefault("admin_flash_message", None)
    st.session_state.setdefault("admin_flash_level", "success")
    st.session_state.setdefault("admin_build_rows", [])
    st.session_state.setdefault("admin_build_total", 0)
    st.session_state.setdefault("admin_build_total_pages", 1)
    st.session_state.setdefault("admin_build_page", 1)
    st.session_state.setdefault("admin_build_page_size", 20)
    st.session_state.setdefault("admin_build_keyword", "")
    st.session_state.setdefault("admin_build_status_filter", "全部")
    st.session_state.setdefault("admin_build_last_query_signature", None)
    st.session_state.setdefault("admin_build_heartbeat_ts", 0.0)
    st.session_state.setdefault("admin_selected_relation_edge_id", None)
    st.session_state.setdefault("admin_selected_community_version_id", None)
    st.session_state.setdefault("admin_selected_community_path", [])


def _render_admin_hero(health: Dict[str, Any], status: Dict[str, Any]) -> None:
    """渲染管理台首页 Hero。"""
    latest_job = status.get("latest_job") or {}
    health_text = "治理链路在线" if health.get("enabled") else "治理链路关闭"
    active_version = status.get("active_version_name") or "未激活"
    hero_html = f"""
    <section class="admin-hero">
      <div class="admin-hero-copy">
        <div class="admin-hero-kicker">GraphRAG Admin Console</div>
        <h1>面向图谱运维与版本治理的统一后台。</h1>
        <p>
          将文档入库、构建调度、版本切换、人工规则和运行日志收敛到一个操作面板，
          让后台更像治理工作台，而不是零散接口的拼接页。
        </p>
        <div class="admin-hero-tags">
          <span>{html.escape(health_text)}</span>
          <span>当前版本：{html.escape(str(active_version))}</span>
          <span>最近任务：{html.escape(_format_status_label(latest_job.get("status", "无")))}</span>
        </div>
      </div>
      <div class="admin-hero-panel">
        <div class="admin-hero-panel-label">当前关注点</div>
        <div class="admin-hero-panel-value">{html.escape(_build_overview_recommendation(status))}</div>
        <div class="admin-hero-panel-meta">建议先完成版本洞察，再执行激活或回滚操作。</div>
      </div>
    </section>
    """
    st.markdown(hero_html, unsafe_allow_html=True)


def _render_section_intro(title: str, description: str, *, compact: bool = False) -> None:
    """渲染分区标题。"""
    class_name = "admin-section-intro compact" if compact else "admin-section-intro"
    st.markdown(
        f"""
        <div class="{class_name}">
          <h2>{html.escape(title)}</h2>
          <p>{html.escape(description)}</p>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _render_summary_metrics(items: List[Dict[str, Any]]) -> None:
    """渲染统一风格的摘要卡片。"""
    if not items:
        return
    cols = st.columns(len(items), gap="medium")
    for col, item in zip(cols, items):
        tone = html.escape(str(item.get("tone") or "light"))
        label = html.escape(str(item.get("label") or "-"))
        value = html.escape(str(item.get("value") or "-"))
        meta = html.escape(str(item.get("meta") or ""))
        col.markdown(
            f"""
            <div class="admin-metric-card {tone}">
              <div class="admin-metric-label">{label}</div>
              <div class="admin-metric-value">{value}</div>
              <div class="admin-metric-meta">{meta}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )


def _render_callout(title: str, description: str, *, tone: str = "info") -> None:
    """渲染统一风格的信息提示卡。"""
    st.markdown(
        f"""
        <div class="admin-callout {html.escape(tone)}">
          <strong>{html.escape(title)}</strong>
          <span>{html.escape(description)}</span>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _render_empty_state(title: str, description: str) -> None:
    """渲染统一空态。"""
    st.markdown(
        f"""
        <div class="admin-empty-state">
          <strong>{html.escape(title)}</strong>
          <span>{html.escape(description)}</span>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _build_overview_recommendation(status: Dict[str, Any]) -> str:
    """根据当前状态生成运维建议。"""
    latest_job = status.get("latest_job") or {}
    latest_status = str(latest_job.get("status") or "")
    if latest_status == "failed":
        return "最近构建失败，建议先进入构建调度定位日志并确认失败阶段。"
    if not status.get("active_version_id"):
        return "当前没有激活版本，建议先完成一次全量构建并确认快照可视化是否正常。"
    if int(status.get("document_count") or 0) == 0:
        return "当前没有登记文档，建议先执行文档入库，再进行补充构建。"
    return "系统处于可治理状态，可优先查看版本洞察并评估是否需要激活新版本。"


def _render_status_header(health: Dict[str, Any], status: Dict[str, Any]) -> None:
    """渲染顶部状态摘要。"""
    latest_job = status.get("latest_job") or {}
    _render_summary_metrics(
        [
            {
                "label": "后台开关",
                "value": "启用" if health.get("enabled") else "关闭",
                "meta": "控制治理接口是否对外提供能力",
                "tone": "dark" if health.get("enabled") else "warning",
            },
            {
                "label": "元数据库",
                "value": "已连接" if status.get("metadata_db_connected") else "未连接",
                "meta": "版本、文档、任务与规则元数据",
                "tone": "info" if status.get("metadata_db_connected") else "warning",
            },
            {
                "label": "Neo4j",
                "value": "已连接" if status.get("neo4j_connected") else "未连接",
                "meta": "当前激活图谱的在线读写存储",
                "tone": "info" if status.get("neo4j_connected") else "warning",
            },
            {
                "label": "当前激活版本",
                "value": status.get("active_version_name") or "无",
                "meta": f"最近任务：{_format_status_label(latest_job.get('status'))}",
                "tone": "accent",
            },
        ]
    )

    if not health.get("enabled"):
        _render_callout(
            "后台管理未启用",
            "请检查 `GRAPH_ADMIN_ENABLED` 与后端启动参数，否则页面只能停留在连接失败或只读状态。",
            tone="warning",
        )
    elif not status.get("metadata_db_connected") or not status.get("neo4j_connected"):
        _render_callout(
            "核心依赖存在未就绪项",
            "建议先恢复 PostgreSQL 或 Neo4j，再执行入库、构建和版本切换，避免产生半完成任务。",
            tone="warning",
        )
    else:
        _render_callout(
            "治理链路已就绪",
            "建议按照“文档入库 -> 构建调度 -> 版本洞察 -> 版本治理”的顺序操作，降低误删或误回滚风险。",
            tone="info",
        )


def _render_overview(status: Dict[str, Any]) -> None:
    """渲染概览页。"""
    latest_job = status.get("latest_job") or {}
    _render_section_intro(
        "治理总览",
        "集中查看后台健康度、当前激活版本、最近一次构建结果以及建议操作路径。",
    )
    _render_summary_metrics(
        [
            {
                "label": "登记文档",
                "value": status.get("document_count", 0),
                "meta": "已进入治理链路的 PDF 文档数量",
                "tone": "light",
            },
            {
                "label": "图谱版本",
                "value": status.get("version_count", 0),
                "meta": "支持激活、回滚与差异对比",
                "tone": "light",
            },
            {
                "label": "最近任务状态",
                "value": _format_status_label(latest_job.get("status", "无")),
                "meta": latest_job.get("job_type") or "暂无任务记录",
                "tone": "accent" if latest_job.get("status") == "succeeded" else "dark",
            },
            {
                "label": "当前生效版本",
                "value": status.get("active_version_name") or "未激活",
                "meta": status.get("active_version_id") or "请先完成一次构建",
                "tone": "dark",
            },
        ]
    )

    col1, col2 = st.columns([1.6, 1.0], gap="large")
    with col1:
        _render_section_intro("系统快照", "保留关键字段，减少在元数据表中来回查找。", compact=True)
        _render_callout(
            "当前建议",
            _build_overview_recommendation(status),
            tone="info",
        )
        overview_rows = [
            {"字段": "active_version_id", "值": status.get("active_version_id")},
            {"字段": "active_version_name", "值": status.get("active_version_name")},
            {"字段": "latest_job_id", "值": latest_job.get("job_id")},
            {"字段": "latest_job_type", "值": latest_job.get("job_type")},
            {"字段": "latest_job_message", "值": latest_job.get("message")},
        ]
        _render_safe_dataframe(overview_rows)

    with col2:
        _render_section_intro("标准操作流", "后台治理建议按照稳定运维顺序推进。", compact=True)
        st.markdown(
            """
            <div class="admin-step-list">
              <div class="admin-step-item"><span>01</span><div><strong>文档入库</strong><br>先登记 PDF，保证 revision 来源可追溯。</div></div>
              <div class="admin-step-item"><span>02</span><div><strong>构建调度</strong><br>新增文档优先补充构建，避免无差别全量重扫。</div></div>
              <div class="admin-step-item"><span>03</span><div><strong>版本洞察</strong><br>先看社区图谱、关系筛选和差异结果，再决定是否激活。</div></div>
              <div class="admin-step-item"><span>04</span><div><strong>版本治理</strong><br>仅对经过确认的版本执行激活、回滚或清理。</div></div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        _render_callout(
            "Kubernetes 建议",
            "后台前端、FastAPI 与构建 Worker 应拆成独立 Deployment；构建任务不要跑在 Web 进程内，并为上传目录、快照目录、Neo4j 与 PostgreSQL 都配置持久化卷。",
            tone="dark",
        )


def _render_upload_tab() -> None:
    """渲染文档上传页。"""
    _render_section_intro(
        "文档入库",
        "上传 PDF 并登记 revision，为增量补图和版本追踪提供可回溯输入。",
    )
    docs = get_documents()
    document_rows = docs.get("documents", [])
    revision_rows = docs.get("revisions", [])
    _render_summary_metrics(
        [
            {
                "label": "已登记文档",
                "value": len(document_rows),
                "meta": "文档主记录",
                "tone": "light",
            },
            {
                "label": "Revision 数",
                "value": len(revision_rows),
                "meta": "支持增量构建追踪",
                "tone": "light",
            },
            {
                "label": "推荐方式",
                "value": "批量上传",
                "meta": "一次性维护一批待补图文档",
                "tone": "accent",
            },
        ]
    )
    intro_col1, intro_col2 = st.columns([1.7, 1.0], gap="large")
    with intro_col1:
        _render_callout(
            "入库策略",
            "后台会先登记文档和 revision，之后再在构建调度中决定执行全量构建还是补充构建。",
            tone="info",
        )
    with intro_col2:
        _render_callout(
            "操作建议",
            "生产环境建议限制单次上传批次大小，并在对象存储或持久化卷中保存原始 PDF，避免仅依赖容器本地磁盘。",
            tone="dark",
        )
    uploaded_files = st.file_uploader(
        "选择一个或多个 PDF 文件",
        type=["pdf"],
        accept_multiple_files=True,
    )

    if st.button("上传并登记文档", type="primary", use_container_width=True):
        if not uploaded_files:
            st.warning("请先选择至少一个 PDF 文件。")
            return

        results: List[Dict[str, Any]] = []
        for item in uploaded_files:
            try:
                result = upload_document(item.name, item.getvalue())
                results.append(result)
            except requests.RequestException as exc:
                st.error(f"上传 {item.name} 失败：{exc}")
                return

        st.success(f"成功上传 {len(results)} 个文档。")
        _render_safe_dataframe(results)

    st.divider()
    _render_section_intro("文档台账", "将文档主记录与 revision 记录分开展示，便于快速定位补图来源。", compact=True)
    docs_tab, revs_tab = st.tabs(["文档记录", "Revision 记录"])
    with docs_tab:
        _render_dataframe_or_empty(document_rows, "当前还没有已登记文档。")
    with revs_tab:
        _render_dataframe_or_empty(revision_rows, "当前还没有 revision 记录。")


def _render_build_tab() -> None:
    """渲染构建页。"""
    _render_flash_message()
    _render_section_intro(
        "构建调度",
        "把全量重建和补充构建收敛到同一工作区，并配合任务时间线与日志做过程追踪。",
    )
    build_mode = st.radio(
        "构建方式",
        ["full_rebuild", "incremental"],
        horizontal=True,
        format_func=lambda value: (
            "扫描 files 全量构建"
            if value == "full_rebuild"
            else "上传新文件并补充构建"
        ),
    )
    version_name = st.text_input("版本名称", placeholder="可选，不填则自动生成")
    _render_callout(
        "构建行为说明",
        "当前实现会在构建完成后生成新版本并立即激活。若后续要上生产，建议改成“构建完成 -> 人工验收 -> 手动激活”的两阶段流程。",
        tone="warning",
    )

    if build_mode == "full_rebuild":
        _render_callout(
            "全量重建",
            "适合底层规则调整、索引结构变化或大规模回灌场景。该操作会重新扫描 `files/` 下全部文件，成本较高。",
            tone="dark",
        )
        if st.button("开始全量构建", type="primary", use_container_width=True):
            try:
                result = create_full_rebuild(
                    version_name=version_name or None,
                    revision_ids=[],
                )
            except requests.RequestException as exc:
                st.error(f"创建全量构建任务失败：{exc}")
                return
            _handle_build_created(result, "全量构建任务已创建。")
    else:
        _render_callout(
            "补充构建",
            "适合新增少量文档时快速补图。该模式会先保存新文件，再仅针对这批 revision 执行构建。",
            tone="info",
        )
        uploaded_files = st.file_uploader(
            "选择要补充构建的新 PDF 文件",
            type=["pdf"],
            accept_multiple_files=True,
            key="admin_incremental_build_uploads",
        )
        if st.button("上传并开始补充构建", type="primary", use_container_width=True):
            if not uploaded_files:
                st.warning("请先选择至少一个 PDF 文件。")
                return

            revision_ids: List[str] = []
            try:
                for item in uploaded_files:
                    upload_result = upload_document(item.name, item.getvalue())
                    revision_ids.append(upload_result["revision_id"])
                result = create_incremental_build(
                    version_name=version_name or None,
                    revision_ids=revision_ids,
                )
            except requests.RequestException as exc:
                st.error(f"创建补充构建任务失败：{exc}")
                return
            _handle_build_created(result, "补充构建任务已创建。")

    st.divider()
    _render_build_monitor_section()


def _render_versions_tab() -> None:
    """渲染图谱版本页。"""
    versions = get_graph_versions().get("items", [])
    _render_section_intro(
        "版本治理",
        "统一执行版本激活、回滚和清理，避免在多个页面之间切换造成误操作。",
    )
    active_versions = [item for item in versions if item.get("is_active")]
    _render_summary_metrics(
        [
            {
                "label": "版本总数",
                "value": len(versions),
                "meta": "可用于历史追溯与回滚",
                "tone": "light",
            },
            {
                "label": "当前激活",
                "value": active_versions[0].get("version_name") if active_versions else "无",
                "meta": active_versions[0].get("version_id") if active_versions else "请先激活稳定版本",
                "tone": "dark",
            },
            {
                "label": "治理原则",
                "value": "先洞察后切换",
                "meta": "建议先在版本洞察确认图谱内容",
                "tone": "accent",
            },
        ]
    )
    version_table_rows = [
        {
            "版本名称": item.get("version_name"),
            "版本 ID": item.get("version_id"),
            "状态": _format_status_label(item.get("status")),
            "构建类型": item.get("build_type") or "-",
            "节点数": item.get("entity_count") or 0,
            "关系数": item.get("relation_count") or 0,
            "是否激活": "是" if item.get("is_active") else "否",
            "创建时间": _format_datetime_text(item.get("created_at")),
        }
        for item in versions
    ]
    _render_dataframe_or_empty(version_table_rows, "当前还没有图谱版本。")

    version_options = {
        f"{item['version_name']} | {item['version_id']} | {_format_status_label(item['status'])}": item["version_id"]
        for item in versions
    }
    if not version_options:
        return

    _render_callout(
        "操作提示",
        "激活会立即切换在线图谱；回滚适用于恢复历史稳定状态；手动重构社区仅支持当前激活版本；删除前请确认该版本不是唯一可回溯快照。",
        tone="warning",
    )
    selected_label = st.selectbox("选择要操作的图谱版本", options=list(version_options.keys()))
    selected_version_id = version_options[selected_label]
    selected_version = next(
        (item for item in versions if item.get("version_id") == selected_version_id),
        {},
    )
    is_selected_active = bool(selected_version.get("is_active"))

    if is_selected_active:
        _render_callout(
            "社区重构已就绪",
            "该版本当前已经激活。你可以在不改节点与关系主数据的前提下，手动重建社区与社区摘要，并刷新当前版本快照。",
            tone="info",
        )
    else:
        _render_callout(
            "社区重构受限",
            "为避免后台误写非激活图谱，手动社区重构仅对当前激活版本开放。若确需重构，请先激活该版本。",
            tone="dark",
        )

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        if st.button("激活为当前线上版本", use_container_width=True, type="primary"):
            try:
                result = activate_graph_version(selected_version_id)
            except requests.RequestException as exc:
                st.error(f"激活版本失败：{exc}")
            else:
                st.success("版本已激活。")
                st.json(result)
    with col2:
        if st.button("回滚到该版本", use_container_width=True):
            try:
                result = rollback_graph_version(selected_version_id)
            except requests.RequestException as exc:
                st.error(f"回滚版本失败：{exc}")
            else:
                st.success("图谱已回滚。")
                st.json(result)
    with col3:
        if st.button(
            "手动重构社区",
            use_container_width=True,
            disabled=not is_selected_active,
        ):
            try:
                result = rebuild_graph_version_communities(selected_version_id)
            except requests.RequestException as exc:
                st.error(f"手动重构社区失败：{exc}")
            else:
                st.success("社区结构已按当前激活图谱重建，并同步刷新版本快照。")
                st.json(result)
    with col4:
        if st.button("删除该版本", use_container_width=True):
            try:
                result = delete_graph_version(selected_version_id)
            except requests.RequestException as exc:
                st.error(f"删除版本失败：{exc}")
            else:
                st.success("版本已删除。")
                st.json(result)


def _render_version_view_tab() -> None:
    """渲染版本查看页。"""
    versions = get_graph_versions().get("items", [])
    _render_section_intro(
        "版本洞察",
        "在激活前从元数据、节点关系、社区结构与版本差异多个视角确认版本质量。",
    )
    version_options = {
        f"{item['version_name']} | {item['version_id']}": item["version_id"]
        for item in versions
    }
    if not version_options:
        _render_empty_state("暂无可查看版本", "请先在构建调度中完成一次构建，再进入版本洞察。")
        return

    selected_version_label = st.selectbox(
        "选择查看版本",
        options=list(version_options.keys()),
        key="admin_selected_version",
    )
    selected_version_id = version_options[selected_version_label]

    detail = get_graph_version(selected_version_id)
    if st.session_state.get("admin_selected_community_version_id") != selected_version_id:
        st.session_state.admin_selected_community_version_id = selected_version_id
        st.session_state.admin_selected_community_path = []
    version = detail.get("version", {})
    build_jobs = detail.get("build_jobs", [])
    document_rows = detail.get("documents", [])
    revision_rows = detail.get("document_revisions", [])

    _render_summary_metrics(
        [
            {
                "label": "版本状态",
                "value": _format_status_label(version.get("status") or "-"),
                "meta": version.get("build_type") or "未知构建类型",
                "tone": "dark",
            },
            {
                "label": "节点数",
                "value": int(version.get("entity_count") or 0),
                "meta": "来自版本快照统计",
                "tone": "light",
            },
            {
                "label": "关系数",
                "value": int(version.get("relation_count") or 0),
                "meta": "可在关系工作台进一步筛选",
                "tone": "light",
            },
            {
                "label": "关联文档数",
                "value": len({row.get("document_id") for row in document_rows if row.get("document_id")}),
                "meta": "关联 revision 与文档来源",
                "tone": "accent",
            },
        ]
    )

    meta_tab, jobs_tab, docs_tab, revs_tab = st.tabs(
        ["版本记录", "构建任务", "关联文档", "关联 Revision"]
    )
    with meta_tab:
        _render_version_metadata(version)
    with jobs_tab:
        _render_dataframe_or_empty(build_jobs, "当前版本还没有关联构建任务。")
    with docs_tab:
        _render_dataframe_or_empty(document_rows, "当前版本还没有关联文档。")
    with revs_tab:
        _render_dataframe_or_empty(revision_rows, "当前版本还没有关联 revision。")

    try:
        visualization = get_graph_visualization(selected_version_id)
    except requests.RequestException as exc:
        if version.get("status") in {"pending", "building"}:
            st.info("当前版本仍在构建中，快照生成后才可查看可视化。")
        else:
            st.error(f"加载图谱可视化失败：{exc}")
        visualization = {}

    if visualization:
        raw_snapshot = visualization.get("raw", {})
        node_rows = raw_snapshot.get("nodes", [])
        relation_rows = raw_snapshot.get("relationships", [])
        relation_view_rows = _build_relation_view_rows(node_rows, relation_rows)
        community_visualization = build_community_overview_visualization(raw_snapshot)
        _render_section_intro(
            "图谱快照工作台",
            "把节点浏览、关系筛选和差异对比放在同一页，减少治理时的上下文切换。",
            compact=True,
        )
        node_tab, rel_tab, diff_tab = st.tabs(["节点浏览", "关系工作台", "版本差异"])
        with node_tab:
            _render_paginated_node_table(
                node_rows,
                export_prefix=f"graph_nodes_{selected_version_id}",
                raw_snapshot=raw_snapshot,
            )
        with rel_tab:
            _render_relationship_workspace(
                visualization,
                community_visualization,
                relation_view_rows,
                raw_snapshot,
            )
        with diff_tab:
            compare_options = {
                f"{item['version_name']} | {item['version_id']}": item["version_id"]
                for item in versions
                if item["version_id"] != selected_version_id
            }
            if not compare_options:
                _render_empty_state("差异对比未就绪", "至少需要两个版本，才能查看新增节点与版本摘要差异。")
            else:
                diff_label = st.selectbox("选择对比版本", options=list(compare_options.keys()))
                if st.button("比较版本差异", use_container_width=True):
                    diff_result = get_graph_diff(selected_version_id, compare_options[diff_label])
                    summary = diff_result.get("summary", {})
                    _render_summary_metrics(
                        [
                            {
                                "label": "新增节点",
                                "value": summary.get("added_node_count", 0),
                                "meta": "对比结果",
                                "tone": "accent",
                            },
                            {
                                "label": "新增关系",
                                "value": summary.get("added_relationship_count", 0),
                                "meta": "对比结果",
                                "tone": "light",
                            },
                            {
                                "label": "移除节点",
                                "value": summary.get("removed_node_count", 0),
                                "meta": "对比结果",
                                "tone": "warning",
                            },
                            {
                                "label": "移除关系",
                                "value": summary.get("removed_relationship_count", 0),
                                "meta": "对比结果",
                                "tone": "warning",
                            },
                        ]
                    )
                    _render_dataframe_or_empty(
                        diff_result.get("added_nodes", []),
                        "当前没有新增节点。",
                    )
    else:
        _render_empty_state("当前版本暂无可视化快照", "如果版本仍在构建中，请等待快照生成；如果已完成，请检查后端快照导出链路。")


def _render_dataframe_or_empty(rows: List[Dict[str, Any]], empty_message: str) -> None:
    """渲染表格或空态提示。"""
    if not rows:
        _render_empty_state("暂无数据", empty_message)
        return
    _render_safe_dataframe(rows)


def _render_version_metadata(version: Dict[str, Any]) -> None:
    """以适合后台查看的格式渲染版本元数据。"""
    if not version:
        st.info("当前版本没有可展示的元数据。")
        return

    summary_rows = [
        {"字段": "版本 ID", "值": str(version.get("version_id") or "-")},
        {"字段": "版本名称", "值": str(version.get("version_name") or "-")},
        {"字段": "构建类型", "值": str(version.get("build_type") or "-")},
        {"字段": "状态", "值": str(version.get("status") or "-")},
        {"字段": "基线版本", "值": str(version.get("base_version_id") or "-")},
        {"字段": "创建时间", "值": str(_format_datetime_text(version.get("created_at")))},
        {"字段": "激活时间", "值": str(_format_datetime_text(version.get("activated_at")))},
        {"字段": "节点数", "值": str(int(version.get("entity_count") or 0))},
        {"字段": "关系数", "值": str(int(version.get("relation_count") or 0))},
        {"字段": "文档数", "值": str(int(version.get("document_count") or 0))},
        {"字段": "是否激活", "值": "是" if version.get("is_active") else "否"},
        {"字段": "快照文件", "值": str(version.get("snapshot_path") or "-")},
    ]
    _render_safe_dataframe(summary_rows)

    snapshot_data = version.get("snapshot_data")
    if snapshot_data:
        st.caption(f"快照内容已隐藏，元数据库中已保存约 {len(str(snapshot_data)):,} 个字符。")


def _handle_build_created(result: Dict[str, Any], message: str) -> None:
    """处理构建任务创建后的前端状态更新。"""
    st.session_state.admin_flash_message = message
    st.session_state.admin_flash_level = "success"
    st.session_state.admin_selected_job_id = result["job"]["job_id"]
    st.session_state.admin_build_heartbeat_ts = 0.0
    st.session_state.admin_build_last_query_signature = None


def _render_paginated_node_table(
    node_rows: List[Dict[str, Any]],
    *,
    export_prefix: str = "graph_nodes",
    raw_snapshot: Dict[str, Any] | None = None,
) -> None:
    """分页渲染节点表，避免一次性加载过多节点。"""
    if not node_rows:
        st.info("当前版本没有节点数据。")
        return

    export_rows = _exportable_node_rows(node_rows)
    export_df = pd.DataFrame(export_rows)
    export_col1, export_col2, export_col3 = st.columns(3)
    export_col1.download_button(
        "导出节点 CSV",
        data=export_df.to_csv(index=False).encode("utf-8-sig"),
        file_name=f"{export_prefix}.csv",
        mime="text/csv",
        use_container_width=True,
    )
    export_col2.download_button(
        "导出节点 Excel",
        data=_build_excel_html_bytes(export_df),
        file_name=f"{export_prefix}.xls",
        mime="application/vnd.ms-excel",
        use_container_width=True,
    )
    snapshot_payload = _build_node_export_payload(
        node_rows,
        version_id=export_prefix.replace("graph_nodes_", "", 1),
    )
    export_col3.download_button(
        "导出节点 JSON",
        data=json.dumps(snapshot_payload, ensure_ascii=False, indent=2).encode("utf-8"),
        file_name=f"{export_prefix}.json",
        mime="application/json",
        use_container_width=True,
    )

    pager_col1, pager_col2, pager_col3 = st.columns([1.4, 1.4, 3.2])
    page_size = pager_col1.selectbox(
        "每页条数",
        options=[20, 50, 100, 200],
        index=1,
        key="admin_node_page_size",
    )
    total_pages = max(1, (len(node_rows) + page_size - 1) // page_size)
    page_number = pager_col2.number_input(
        "页码",
        min_value=1,
        max_value=total_pages,
        value=min(st.session_state.get("admin_node_page_number", 1), total_pages),
        step=1,
        key="admin_node_page_number",
    )
    pager_col3.caption(f"节点总数 {len(node_rows)}，共 {total_pages} 页。")

    start_index = (int(page_number) - 1) * int(page_size)
    end_index = start_index + int(page_size)
    current_page_rows = node_rows[start_index:end_index]

    st.caption(f"当前第 {int(page_number)} / {total_pages} 页，每页 {int(page_size)} 条。")
    _render_safe_dataframe(current_page_rows)


def _build_relation_view_rows(
    node_rows: List[Dict[str, Any]],
    relation_rows: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """构建适合前端检索的关系表结构。"""
    node_label_map: Dict[str, str] = {}
    node_graph_id_map: Dict[str, str] = {}
    for node in node_rows:
        neo4j_id = str(node.get("neo4j_id"))
        properties = node.get("properties", {}) or {}
        label = properties.get("name") or properties.get("id") or f"neo4j:{neo4j_id}"
        graph_node_id = properties.get("id") or f"neo4j:{neo4j_id}"
        node_label_map[neo4j_id] = str(label)
        node_graph_id_map[neo4j_id] = str(graph_node_id)

    rows: List[Dict[str, Any]] = []
    for index, relation in enumerate(relation_rows):
        source_id = str(relation.get("source_id"))
        target_id = str(relation.get("target_id"))
        properties = relation.get("properties", {}) or {}
        row = {
            "edge_id": f"edge_{index}",
            "source_id": source_id,
            "source_name": node_label_map.get(source_id, source_id),
            "source_graph_node_id": node_graph_id_map.get(source_id, source_id),
            "relationship_type": relation.get("type", ""),
            "target_id": target_id,
            "target_name": node_label_map.get(target_id, target_id),
            "target_graph_node_id": node_graph_id_map.get(target_id, target_id),
            "properties_json": json.dumps(properties, ensure_ascii=False),
            "properties_dict": properties,
        }
        for key, value in properties.items():
            row[f"prop_{key}"] = value
        rows.append(row)
    return rows


def _render_relationship_workspace(
    visualization: Dict[str, Any],
    community_visualization: Dict[str, Any],
    relation_rows: List[Dict[str, Any]],
    raw_snapshot: Dict[str, Any],
) -> None:
    """渲染关系图、检索表和属性详情。"""
    if not relation_rows:
        _render_empty_state("当前版本没有关系数据", "请先确认该版本是否已生成有效快照。")
        return

    _render_callout(
        "关系工作台说明",
        "先用关键词和关系类型过滤，再勾选高亮关系查看局部聚焦图，最后在属性面板确认细节。",
        tone="info",
    )
    filter_col1, filter_col2, filter_col3, filter_col4 = st.columns([2.0, 1.4, 2.0, 1.8])
    keyword = filter_col1.text_input(
        "搜索节点或关系",
        placeholder="输入源节点、目标节点、关系类型或属性关键词",
        key="admin_relation_keyword",
    ).strip().lower()
    source_options = sorted(
        {
            str(row.get("source_name") or "")
            for row in relation_rows
            if row.get("source_name")
        }
    )
    selected_source_name = filter_col2.selectbox(
        "源节点筛选",
        options=["全部"] + source_options,
        key="admin_relation_source_filter",
    )
    relation_types = sorted(
        {
            str(row.get("relationship_type") or "")
            for row in relation_rows
            if row.get("relationship_type")
        }
    )
    selected_relation_type = filter_col3.selectbox(
        "关系类型筛选",
        options=["全部"] + relation_types,
        key="admin_relation_type_filter",
    )
    target_keyword = filter_col4.text_input(
        "按目标节点过滤",
        placeholder="输入目标节点名称",
        key="admin_relation_target_keyword",
    ).strip().lower()

    filtered_rows = relation_rows
    if keyword:
        filtered_rows = [
            row
            for row in filtered_rows
            if keyword in " ".join(
                [
                    str(row.get("source_name", "")).lower(),
                    str(row.get("target_name", "")).lower(),
                    str(row.get("relationship_type", "")).lower(),
                    str(row.get("properties_json", "")).lower(),
                ]
            )
        ]
    if selected_source_name != "全部":
        filtered_rows = [
            row
            for row in filtered_rows
            if str(row.get("source_name") or "") == selected_source_name
        ]
    if selected_relation_type != "全部":
        filtered_rows = [
            row
            for row in filtered_rows
            if str(row.get("relationship_type") or "") == selected_relation_type
        ]
    if target_keyword:
        filtered_rows = [
            row
            for row in filtered_rows
            if target_keyword in str(row.get("target_name", "")).lower()
        ]

    current_selected_relation = _render_relationship_selection(filtered_rows)
    _render_summary_metrics(
        [
            {
                "label": "关系总数",
                "value": len(relation_rows),
                "meta": "版本快照中的全部关系",
                "tone": "light",
            },
            {
                "label": "筛选结果",
                "value": len(filtered_rows),
                "meta": "当前过滤条件命中",
                "tone": "accent",
            },
            {
                "label": "关系类型",
                "value": len(relation_types),
                "meta": "可用于筛选的类型数",
                "tone": "light",
            },
            {
                "label": "当前高亮",
                "value": current_selected_relation.get("relationship_type") if current_selected_relation else "未选择",
                "meta": current_selected_relation.get("source_name") if current_selected_relation else "请在表格中勾选关系",
                "tone": "dark",
            },
        ]
    )
    export_df = pd.DataFrame(_exportable_relation_rows(filtered_rows))
    export_col1, export_col2 = st.columns(2)
    export_col1.download_button(
        "导出 CSV",
        data=export_df.to_csv(index=False).encode("utf-8-sig"),
        file_name="graph_relationships.csv",
        mime="text/csv",
        use_container_width=True,
    )
    export_col2.download_button(
        "导出 Excel",
        data=_build_excel_html_bytes(export_df),
        file_name="graph_relationships.xls",
        mime="application/vnd.ms-excel",
        use_container_width=True,
    )

    page_rows, page_state = _paginate_relation_rows(filtered_rows)
    display_rows = _build_relation_display_rows(page_rows, current_selected_relation)
    edited_df = st.data_editor(
        pd.DataFrame(display_rows),
        use_container_width=True,
        hide_index=True,
        key=f"admin_relation_editor_{page_state['page_number']}",
        disabled=["源节点", "关系类型", "目标节点", "关系属性"],
        column_config={
            "高亮": st.column_config.CheckboxColumn(
                "高亮",
                help="点击后高亮图中的对应边和节点",
            ),
        },
    )
    _sync_selected_relation_from_editor(page_rows, edited_df)
    selected_relation = _render_relationship_selection(filtered_rows)

    highlighted_visualization = _build_highlighted_visualization(
        visualization,
        selected_relation,
    )
    workspace_tab1, workspace_tab2, workspace_tab3 = st.tabs(
        ["社区全局图谱", "局部聚焦图谱", "关系属性"]
    )
    with workspace_tab1:
        _render_section_intro(
            "社区全局图谱",
            "仅展示压缩后的社区层，并按跨社区关系聚合为超边，适合快速判断全局结构是否异常。",
            compact=True,
        )
        _render_recursive_community_workspace(raw_snapshot, community_visualization)

    with workspace_tab2:
        _render_section_intro(
            "局部聚焦图谱",
            "基于当前高亮关系自动聚焦一跳邻域，适合检查错误连接或命名漂移。",
            compact=True,
        )
        focused_node_id = _render_focus_node_selector(visualization, selected_relation)
        focused_visualization = _build_focused_visualization(
            highlighted_visualization,
            focused_node_id,
        )
        if selected_relation:
            st.caption(
                f"当前高亮：{selected_relation['source_name']} -[{selected_relation['relationship_type']}]-> {selected_relation['target_name']}"
            )
        visualize_knowledge_graph(
            focused_visualization,
            focus_node_id=focused_node_id,
        )

    with workspace_tab3:
        _render_section_intro(
            "关系属性详情",
            f"当前第 {page_state['page_number']} / {page_state['total_pages']} 页，每页 {page_state['page_size']} 条。",
            compact=True,
        )
        if selected_relation:
            prop_rows = [
                {"字段": key, "值": value}
                for key, value in (selected_relation.get("properties_dict") or {}).items()
            ]
            detail_col1, detail_col2 = st.columns([1.6, 2.4])
            with detail_col1:
                st.json(
                    {
                        "edge_id": selected_relation.get("edge_id"),
                        "source_name": selected_relation.get("source_name"),
                        "relationship_type": selected_relation.get("relationship_type"),
                        "target_name": selected_relation.get("target_name"),
                    }
                )
            with detail_col2:
                if prop_rows:
                    _render_safe_dataframe(_stringify_record_values(prop_rows))
                else:
                    _render_empty_state("没有额外属性", "该关系当前仅包含基础连接信息。")
        else:
            _render_empty_state("尚未选择关系", "请先在关系表中勾选一条关系，再查看属性详情。")


def _render_recursive_community_workspace(
    raw_snapshot: Dict[str, Any],
    root_visualization: Dict[str, Any],
) -> None:
    """渲染支持递归下钻的社区图谱工作区。"""
    community_path = list(st.session_state.get("admin_selected_community_path", []))
    current_visualization = build_community_drilldown_visualization(
        raw_snapshot,
        community_path=community_path,
    )
    community_meta = current_visualization.get("meta", {}) or {}

    if community_meta.get("community_count"):
        breadcrumb = " / ".join(community_meta.get("path_labels") or [])
        if breadcrumb:
            st.caption(f"当前下钻路径：{breadcrumb}")
        else:
            root_meta = root_visualization.get("meta", {}) or {}
            st.caption(
                "当前展示社区压缩图："
                f" level={root_meta.get('display_level', 0)}，"
                f" 社区数={root_meta.get('community_count', 0)}，"
                f" 聚合边数={root_meta.get('aggregated_edge_count', 0)}。"
            )

        control_col1, control_col2, control_col3 = st.columns([1.0, 1.0, 2.2])
        with control_col1:
            if st.button("回到根社区图", use_container_width=True, key="admin_reset_community_path"):
                st.session_state.admin_selected_community_path = []
                st.rerun()
        with control_col2:
            can_go_back = bool(community_path)
            if st.button(
                "返回上一层",
                use_container_width=True,
                disabled=not can_go_back,
                key="admin_pop_community_path",
            ):
                st.session_state.admin_selected_community_path = community_path[:-1]
                st.rerun()
        with control_col3:
            expandable_nodes = [
                node for node in current_visualization.get("nodes", [])
                if int(node.get("properties", {}).get("child_count") or 0) > 0
            ]
            if expandable_nodes:
                selected_label = st.selectbox(
                    "选择当前社区并下钻到子社区",
                    options=[
                        f"{node.get('label', node['id']).splitlines()[0]} | {node['id']} | 子社区 {int(node.get('properties', {}).get('child_count') or 0)}"
                        for node in expandable_nodes
                    ],
                    key="admin_expandable_community_selector",
                )
                selected_community_id = selected_label.split(" | ")[1]
                if st.button(
                    "展开子社区",
                    use_container_width=True,
                    key="admin_expand_community_path",
                ):
                    st.session_state.admin_selected_community_path = community_path + [selected_community_id]
                    st.rerun()
            else:
                st.caption("当前社区层已经不可再分，可通过“返回上一层”继续查看上级结构。")
    else:
        _render_empty_state(
            "当前没有可展示的社区压缩图",
            "请先确认社区检测已经生成 `__Community__` 节点，或重新执行社区重构。",
        )

    visualize_knowledge_graph(current_visualization)


def _render_safe_dataframe(rows: List[Dict[str, Any]]) -> None:
    """渲染对 Arrow 兼容更友好的 DataFrame。"""
    dataframe = pd.DataFrame(_stringify_record_values(rows))
    st.dataframe(dataframe, use_container_width=True, hide_index=True)


def _stringify_record_values(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """将记录中的复杂值统一转为字符串，避免 Streamlit Arrow 推断失败。"""
    normalized_rows: List[Dict[str, Any]] = []
    for row in rows:
        normalized_row: Dict[str, Any] = {}
        for key, value in row.items():
            if value is None:
                normalized_row[key] = "-"
            elif isinstance(value, bool):
                normalized_row[key] = "true" if value else "false"
            elif isinstance(value, (int, float)):
                normalized_row[key] = str(value)
            elif isinstance(value, str):
                normalized_row[key] = value
            elif isinstance(value, (list, tuple, set, dict)):
                normalized_row[key] = json.dumps(value, ensure_ascii=False)
            else:
                normalized_row[key] = str(value)
        normalized_rows.append(normalized_row)
    return normalized_rows


def _render_relationship_selection(
    relation_rows: List[Dict[str, Any]],
) -> Dict[str, Any] | None:
    """根据会话状态返回当前选中的关系。"""
    selected_edge_id = st.session_state.get("admin_selected_relation_edge_id")
    for row in relation_rows:
        if row.get("edge_id") == selected_edge_id:
            return row
    if relation_rows:
        return relation_rows[0]
    return None


def _build_relation_display_rows(
    relation_rows: List[Dict[str, Any]],
    selected_relation: Dict[str, Any] | None,
) -> List[Dict[str, Any]]:
    """构建关系表展示结构。"""
    selected_edge_id = selected_relation.get("edge_id") if selected_relation else None
    rows: List[Dict[str, Any]] = []
    for row in relation_rows:
        rows.append(
            {
                "高亮": row.get("edge_id") == selected_edge_id,
                "源节点": row.get("source_name"),
                "关系类型": row.get("relationship_type"),
                "目标节点": row.get("target_name"),
                "关系属性": row.get("properties_json"),
            }
        )
    return rows


def _paginate_relation_rows(relation_rows: List[Dict[str, Any]]) -> tuple[List[Dict[str, Any]], Dict[str, int]]:
    """对关系表进行分页，避免单次渲染过多数据。"""
    if not relation_rows:
        return [], {"page_number": 1, "total_pages": 1, "page_size": 20}

    pager_col1, pager_col2, pager_col3 = st.columns([1.4, 1.4, 3.2])
    page_size = pager_col1.selectbox(
        "每页条数",
        options=[20, 50, 100, 200],
        index=1,
        key="admin_relation_page_size",
    )
    total_pages = max(1, (len(relation_rows) + page_size - 1) // page_size)
    page_number = pager_col2.number_input(
        "页码",
        min_value=1,
        max_value=total_pages,
        value=min(st.session_state.get("admin_relation_page_number", 1), total_pages),
        step=1,
        key="admin_relation_page_number",
    )
    pager_col3.caption(f"筛选结果共 {len(relation_rows)} 条关系，分页后共 {total_pages} 页。")

    start_index = (int(page_number) - 1) * int(page_size)
    end_index = start_index + int(page_size)
    return relation_rows[start_index:end_index], {
        "page_number": int(page_number),
        "total_pages": total_pages,
        "page_size": int(page_size),
    }


def _sync_selected_relation_from_editor(
    relation_rows: List[Dict[str, Any]],
    edited_df: pd.DataFrame,
) -> None:
    """从可编辑表格同步当前选中的关系。"""
    if edited_df.empty or "高亮" not in edited_df.columns:
        return
    checked_indexes = [index for index, value in enumerate(edited_df["高亮"].tolist()) if bool(value)]
    if not checked_indexes:
        return
    selected_index = checked_indexes[-1]
    if selected_index >= len(relation_rows):
        return
    st.session_state.admin_selected_relation_edge_id = relation_rows[selected_index]["edge_id"]


def _build_highlighted_visualization(
    visualization: Dict[str, Any],
    selected_relation: Dict[str, Any] | None,
) -> Dict[str, Any]:
    """生成带高亮状态的图谱数据。"""
    nodes = [dict(node) for node in visualization.get("nodes", [])]
    links = [dict(link) for link in visualization.get("links", [])]

    highlighted_node_ids = set()
    selected_edge_id = None
    if selected_relation:
        highlighted_node_ids.add(str(selected_relation.get("source_graph_node_id")))
        highlighted_node_ids.add(str(selected_relation.get("target_graph_node_id")))
        selected_edge_id = selected_relation.get("edge_id")

    for index, link in enumerate(links):
        edge_id = f"edge_{index}"
        link["edge_id"] = edge_id
        link["highlighted"] = edge_id == selected_edge_id
    for node in nodes:
        node["highlighted"] = str(node.get("id")) in highlighted_node_ids

    payload = dict(visualization)
    payload["nodes"] = nodes
    payload["links"] = links
    return payload


def _render_focus_node_selector(
    visualization: Dict[str, Any],
    selected_relation: Dict[str, Any] | None,
) -> str | None:
    """渲染局部图谱的聚焦节点选择器。"""
    node_options = {
        str(node.get("label") or node.get("id")): str(node.get("id"))
        for node in visualization.get("nodes", [])
    }
    if not node_options:
        return None

    default_node_id = None
    if selected_relation:
        default_node_id = selected_relation.get("source_graph_node_id")

    option_labels = list(node_options.keys())
    default_index = 0
    if default_node_id:
        for idx, label in enumerate(option_labels):
            if node_options[label] == default_node_id:
                default_index = idx
                break

    selected_label = st.selectbox(
        "选择聚焦节点",
        options=option_labels,
        index=default_index,
        key="admin_focus_node_selector",
    )
    return node_options[selected_label]


def _build_focused_visualization(
    visualization: Dict[str, Any],
    focus_node_id: str | None,
) -> Dict[str, Any]:
    """构建单节点局部子图，仅保留目标节点及其一跳邻居。"""
    if not focus_node_id:
        return visualization

    connected_node_ids = {str(focus_node_id)}
    focused_links: List[Dict[str, Any]] = []
    for link in visualization.get("links", []):
        source_id = str(link.get("source"))
        target_id = str(link.get("target"))
        if source_id == str(focus_node_id) or target_id == str(focus_node_id):
            focused_links.append(dict(link))
            connected_node_ids.add(source_id)
            connected_node_ids.add(target_id)

    focused_nodes = [
        dict(node)
        for node in visualization.get("nodes", [])
        if str(node.get("id")) in connected_node_ids
    ]
    return {
        **visualization,
        "nodes": focused_nodes,
        "links": focused_links,
    }


def _is_human_reviewable_property(key: str, value: Any) -> bool:
    """判断属性是否适合导出给人工审查。"""
    normalized_key = str(key).strip().lower()
    if not normalized_key:
        return False

    # 向量、嵌入和索引类字段对人工审查价值很低，默认不导出。
    blocked_keywords = ("embedding", "vector", "index_embedding")
    if any(keyword in normalized_key for keyword in blocked_keywords):
        return False

    if isinstance(value, (bytes, bytearray)):
        return False

    # 超长纯数字列表通常为向量数据，即使字段名异常也不导出。
    if isinstance(value, list) and value:
        if len(value) > 16 and all(isinstance(item, (int, float)) for item in value):
            return False

    return True


def _sanitize_node_for_export(node: Dict[str, Any]) -> Dict[str, Any]:
    """构造适合人工审查的节点导出结构。"""
    properties = node.get("properties", {}) or {}
    sanitized_properties: Dict[str, Any] = {}
    for key, value in properties.items():
        if _is_human_reviewable_property(str(key), value):
            sanitized_properties[str(key)] = value

    return {
        "neo4j_id": node.get("neo4j_id"),
        "labels": node.get("labels", []) or [],
        "properties": sanitized_properties,
    }


def _build_node_export_payload(
    node_rows: List[Dict[str, Any]],
    *,
    version_id: str | None = None,
) -> Dict[str, Any]:
    """构建节点 JSON 导出载荷，仅保留人工可审查字段。"""
    sanitized_nodes = [_sanitize_node_for_export(node) for node in node_rows]
    return {
        "version_id": version_id,
        "node_count": len(sanitized_nodes),
        "nodes": sanitized_nodes,
    }


def _exportable_node_rows(node_rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """构建导出用节点行，保留核心字段并展开属性。"""
    rows: List[Dict[str, Any]] = []
    for node in node_rows:
        sanitized_node = _sanitize_node_for_export(node)
        properties = sanitized_node.get("properties", {}) or {}
        labels = sanitized_node.get("labels", []) or []
        export_row = {
            "neo4j_id": sanitized_node.get("neo4j_id"),
            "labels": json.dumps(labels, ensure_ascii=False),
            "entity_id": properties.get("id"),
            "name": properties.get("name"),
            "description": properties.get("description"),
        }
        # 将属性展开为独立列，便于 Excel 过滤和业务侧复核。
        for key, value in properties.items():
            export_row[f"prop_{key}"] = value
        rows.append(export_row)
    return rows


def _exportable_relation_rows(relation_rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """构建导出用关系行。"""
    rows: List[Dict[str, Any]] = []
    for row in relation_rows:
        export_row = {
            "edge_id": row.get("edge_id"),
            "source_id": row.get("source_id"),
            "source_name": row.get("source_name"),
            "relationship_type": row.get("relationship_type"),
            "target_id": row.get("target_id"),
            "target_name": row.get("target_name"),
            "properties_json": row.get("properties_json"),
        }
        for key, value in row.items():
            if str(key).startswith("prop_"):
                export_row[key] = value
        rows.append(export_row)
    return rows


def _build_excel_html_bytes(dataframe: pd.DataFrame) -> bytes:
    """生成可被 Excel 打开的 HTML 表格字节流。"""
    html_table = dataframe.to_html(index=False, escape=False)
    document = (
        "<html><head><meta charset='utf-8'></head><body>"
        f"{html_table}"
        "</body></html>"
    )
    return document.encode("utf-8")


def _render_corrections_tab() -> None:
    """渲染修正规则页。"""
    _render_section_intro(
        "规则治理",
        "把人工修正规则集中沉淀为可复用治理资产，避免在 Prompt 中临时追加不可追踪逻辑。",
    )
    _render_callout(
        "行业建议",
        "生产环境建议将规则继续细分为抽取、归一化、合并与黑白名单四类，并补充审批流、启停审计与版本化管理。",
        tone="dark",
    )
    with st.form("create_correction_rule"):
        rule_type = st.selectbox("规则类型", ["prompt_append", "extraction_hint", "merge_hint"])
        title = st.text_input("规则标题")
        content = st.text_area("规则内容", height=160)
        scope_type = st.selectbox("作用域", ["global", "document", "revision"])
        scope_id = st.text_input("作用对象 ID", placeholder="可选，document_id 或 revision_id")
        enabled = st.checkbox("启用规则", value=True)
        submitted = st.form_submit_button("新增规则", use_container_width=True)

    if submitted:
        if not title.strip() or not content.strip():
            st.warning("规则标题和内容不能为空。")
        else:
            try:
                result = create_correction(
                    rule_type=rule_type,
                    title=title.strip(),
                    content=content.strip(),
                    scope_type=scope_type,
                    scope_id=scope_id.strip() or None,
                    enabled=enabled,
                )
            except requests.RequestException as exc:
                st.error(f"创建修正规则失败：{exc}")
            else:
                st.success("修正规则已创建。")
                st.json(result)

    rules = get_corrections().get("items", [])
    _render_summary_metrics(
        [
            {
                "label": "规则总数",
                "value": len(rules),
                "meta": "建议控制高频变更并保留审计记录",
                "tone": "light",
            },
            {
                "label": "治理目标",
                "value": "可追溯",
                "meta": "避免规则散落在代码与环境变量中",
                "tone": "accent",
            },
        ]
    )
    _render_dataframe_or_empty(rules, "当前还没有修正规则。")


def _render_logs_tab() -> None:
    """渲染日志页。"""
    _render_flash_message()
    _render_section_intro(
        "日志运维",
        "统一查看前后端运行日志、服务进程状态与高风险维护动作。",
    )
    col1, col2 = st.columns(2)

    try:
        backend_logs = get_backend_logs()
    except requests.RequestException as exc:
        backend_logs = {"path": None, "lines": [f"读取失败：{exc}"]}
    try:
        frontend_logs = get_frontend_logs()
    except requests.RequestException as exc:
        frontend_logs = {"path": None, "lines": [f"读取失败：{exc}"]}

    with col1:
        st.caption(f"后端日志: {backend_logs.get('path') or '未配置'}")
        st.code("\n".join(backend_logs.get("lines", [])), language="log")
    with col2:
        st.caption(f"前端日志: {frontend_logs.get('path') or '未配置'}")
        st.code("\n".join(frontend_logs.get("lines", [])), language="log")

    st.divider()
    _render_section_intro(
        "系统运维操作",
        "这里用于启动主系统服务，以及执行清空数据库和缓存的高风险操作。",
        compact=True,
    )

    try:
        process_rows = get_admin_processes().get("items", [])
    except requests.RequestException as exc:
        st.error(f"读取服务运行状态失败：{exc}")
        process_rows = []

    if process_rows:
        _render_summary_metrics(
            [
                {
                    "label": "服务数",
                    "value": len(process_rows),
                    "meta": "已纳入后台托管",
                    "tone": "light",
                },
                {
                    "label": "运行中",
                    "value": len([item for item in process_rows if item.get("running")]),
                    "meta": "当前在线服务",
                    "tone": "accent",
                },
            ]
        )
        for item in process_rows:
            _render_process_row(item)
    else:
        _render_empty_state("暂无服务状态", "请检查后台进程状态接口是否可用。")

    _render_callout(
        "高风险操作",
        "清空会删除 Neo4j 图数据、后台元数据库记录、图谱快照、上传产物和本地缓存。生产环境建议改为二次确认加审批单。",
        tone="warning",
    )
    confirm_reset = st.checkbox("我确认要清空数据库与缓存", value=False)
    if st.button("执行清空", type="primary", use_container_width=True):
        if not confirm_reset:
            st.error("请先勾选确认后再执行。")
        else:
            try:
                result = reset_admin_state(confirm=True)
            except requests.RequestException as exc:
                st.error(f"执行清空失败：{exc}")
            else:
                st.success("清空操作已完成。")
                st.json(result)


def _render_process_row(item: Dict[str, Any]) -> None:
    """渲染单个服务进程状态行。"""
    status_text = "运行中" if item.get("running") else "未运行"
    pid_text = ", ".join([str(pid) for pid in item.get("pids", [])]) or "-"
    st.markdown(
        f"""
        <div class="admin-process-card">
          <div>
            <div class="admin-process-title">{html.escape(str(item.get('label', item.get('target'))))}</div>
            <div class="admin-process-meta">PID: {html.escape(pid_text)}</div>
            <div class="admin-process-note">{html.escape(str(item.get('note', '') or f"日志: {item.get('log_path', '-')}"))}</div>
          </div>
          <div class="admin-process-state">{html.escape(status_text)}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    cols = st.columns([5.6, 1.4])
    cols[0].markdown("")

    target = item.get("target", "")
    is_running = bool(item.get("running"))
    stoppable = bool(item.get("stoppable", True))
    button_label = "关闭" if is_running else "启动"
    button_type = "secondary" if is_running else "primary"
    disabled = is_running and not stoppable
    if cols[1].button(
        button_label,
        key=f"ops_btn_{target}_{button_label}",
        use_container_width=True,
        type=button_type,
        disabled=disabled,
    ):
        _run_admin_action(
            target=target,
            action="stop" if is_running else "start",
        )


def _run_admin_action(target: str, action: str) -> None:
    """执行后台运维动作并反馈结果。"""
    try:
        result = trigger_admin_action(target=target, action=action)
    except requests.RequestException as exc:
        st.error(f"执行动作失败：{exc}")
        return
    st.session_state.admin_flash_message = f"{target} 已执行 {action}。"
    st.session_state.admin_flash_level = "success"
    st.session_state.admin_last_action_result = result
    st.session_state.admin_build_heartbeat_ts = 0.0


def _render_build_monitor_section() -> None:
    """渲染构建任务监控区。"""
    _refresh_build_rows(force=False)
    build_rows = st.session_state.get("admin_build_rows", [])
    total = st.session_state.get("admin_build_total", 0)
    total_pages = st.session_state.get("admin_build_total_pages", 1)
    st.session_state.admin_build_page = min(
        int(st.session_state.get("admin_build_page", 1)),
        max(1, int(total_pages)),
    )

    _render_section_intro("任务列表", "按任务状态、关键字和分页条件快速筛选构建执行记录。", compact=True)
    filter_col1, filter_col2, filter_col3, filter_col4 = st.columns([2.2, 1.2, 1.0, 2.0])
    keyword_value = filter_col1.text_input(
        "任务筛选",
        value=st.session_state.get("admin_build_keyword", ""),
        placeholder="按任务 ID、版本 ID、类型、状态或消息过滤",
        key="admin_build_keyword",
    )
    status_value = filter_col2.selectbox(
        "状态筛选",
        options=["全部", "pending", "running", "succeeded", "failed"],
        index=["全部", "pending", "running", "succeeded", "failed"].index(
            st.session_state.get("admin_build_status_filter", "全部")
        ),
        key="admin_build_status_filter",
    )
    page_size_value = int(filter_col3.selectbox(
        "每页条数",
        options=[10, 20, 50, 100],
        index=[10, 20, 50, 100].index(st.session_state.get("admin_build_page_size", 20)),
        key="admin_build_page_size",
    ))
    current_page = int(st.session_state.get("admin_build_page", 1))
    page_value = int(filter_col4.number_input(
        "页码",
        min_value=1,
        max_value=max(1, int(total_pages)),
        value=min(current_page, max(1, int(total_pages))),
        step=1,
        key="admin_build_page",
    ))
    _render_build_monitor_summary_bar(
        total=total,
        total_pages=total_pages,
        current_page=page_value,
        page_size=page_size_value,
        build_rows=build_rows,
    )

    current_signature = _build_monitor_query_signature(
        page=page_value,
        page_size=page_size_value,
        keyword=keyword_value,
        status=status_value,
    )
    if current_signature != st.session_state.get("admin_build_last_query_signature"):
        _refresh_build_rows(force=True)
        build_rows = st.session_state.get("admin_build_rows", [])
        total = st.session_state.get("admin_build_total", total)
        total_pages = st.session_state.get("admin_build_total_pages", total_pages)

    _render_build_rows_table(build_rows)
    _render_build_monitor(build_rows)


def _render_build_monitor(build_rows: List[Dict[str, Any]]) -> None:
    """渲染构建任务监控区。"""
    st.divider()
    _render_section_intro("构建监控", "查看单个任务的阶段、进度时间线与实时日志。", compact=True)
    control_cols = st.columns([1.2, 1.4, 3.4])
    if control_cols[0].button("刷新任务状态", use_container_width=True, key="admin_build_refresh"):
        _refresh_build_rows(force=True)
    auto_refresh = control_cols[1].checkbox("后台轮询提示", value=False, key="admin_build_auto_refresh")
    if build_rows:
        running_count = len([row for row in build_rows if row.get("status") == "running"])
        control_cols[2].caption(f"当前运行任务数: {running_count}")
    else:
        control_cols[2].caption("当前没有构建任务。")

    if not build_rows:
        _render_empty_state("暂无构建任务", "请先创建一次全量构建或补充构建。")
        return

    selected_job = _render_build_job_selector(build_rows)
    job_detail = _load_local_job_status(selected_job)
    job_logs = _load_local_job_logs(job_detail, lines=200)
    selector_col, detail_col = st.columns([1.3, 2.7], gap="large")

    with selector_col:
        st.markdown("##### 当前页任务")
        _render_job_compact_list(build_rows, selected_job.get("job_id"))

    with detail_col:
        _render_build_job_detail(job_detail, job_logs)

    if auto_refresh and job_detail.get("status") in {"pending", "running"}:
        st.caption("任务正在运行。当前页面已关闭 fragment 定时刷新，请使用“刷新任务状态”获取最新进度。")
    elif job_detail.get("status") in {"pending", "running"}:
        st.caption("任务正在运行。点击“刷新任务状态”可拉取最新进度。")


def _render_flash_message() -> None:
    """渲染一次性提示信息。"""
    message = st.session_state.pop("admin_flash_message", None)
    if not message:
        return
    level = st.session_state.pop("admin_flash_level", "success")
    if level == "error":
        st.error(message)
    elif level == "warning":
        st.warning(message)
    else:
        st.success(message)


def _refresh_build_rows(force: bool = False) -> None:
    """低频同步构建任务列表，避免高频 HTTP 轮询。"""
    now = time.time()
    last_ts = st.session_state.get("admin_build_heartbeat_ts", 0.0)
    query_signature = _build_monitor_query_signature(
        page=st.session_state.get("admin_build_page", 1),
        page_size=st.session_state.get("admin_build_page_size", 20),
        keyword=st.session_state.get("admin_build_keyword", ""),
        status=st.session_state.get("admin_build_status_filter", "全部"),
    )
    if (
        not force
        and query_signature == st.session_state.get("admin_build_last_query_signature")
        and now - last_ts < 15
    ):
        return
    try:
        build_response = get_builds(
            page=int(st.session_state.get("admin_build_page", 1)),
            page_size=int(st.session_state.get("admin_build_page_size", 20)),
            keyword=(st.session_state.get("admin_build_keyword", "") or "").strip() or None,
            status=_normalize_monitor_status_filter(
                st.session_state.get("admin_build_status_filter", "全部")
            ),
        )
    except requests.RequestException:
        return
    st.session_state.admin_build_rows = build_response.get("items", [])
    st.session_state.admin_build_total = int(build_response.get("total", 0))
    st.session_state.admin_build_total_pages = int(build_response.get("total_pages", 1))
    st.session_state.admin_build_last_query_signature = _build_monitor_query_signature(
        page=int(build_response.get("page", st.session_state.get("admin_build_page", 1))),
        page_size=int(build_response.get("page_size", st.session_state.get("admin_build_page_size", 20))),
        keyword=st.session_state.get("admin_build_keyword", ""),
        status=st.session_state.get("admin_build_status_filter", "全部"),
    )
    st.session_state.admin_build_heartbeat_ts = now


def _build_monitor_query_signature(
    *,
    page: int,
    page_size: int,
    keyword: str,
    status: str,
) -> str:
    """构建监控查询签名，用于判断筛选条件是否变化。"""
    return json.dumps(
        {
            "page": int(page),
            "page_size": int(page_size),
            "keyword": (keyword or "").strip(),
            "status": _normalize_monitor_status_filter(status),
        },
        ensure_ascii=False,
        sort_keys=True,
    )


def _normalize_monitor_status_filter(status: str | None) -> str | None:
    """规范化构建监控状态筛选值。"""
    if not status or status == "全部":
        return None
    return status


def _render_build_monitor_summary_bar(
    *,
    total: int,
    total_pages: int,
    current_page: int,
    page_size: int,
    build_rows: List[Dict[str, Any]],
) -> None:
    """渲染任务列表摘要栏。"""
    running_count = len([row for row in build_rows if row.get("status") == "running"])
    _render_summary_metrics(
        [
            {
                "label": "筛选结果",
                "value": total,
                "meta": "符合当前过滤条件",
                "tone": "light",
            },
            {
                "label": "当前页",
                "value": f"{current_page}/{max(1, total_pages)}",
                "meta": "分页浏览",
                "tone": "light",
            },
            {
                "label": "每页条数",
                "value": page_size,
                "meta": "可按任务量调整",
                "tone": "light",
            },
            {
                "label": "本页运行中",
                "value": running_count,
                "meta": "用于判断是否需要继续刷新",
                "tone": "accent" if running_count else "dark",
            },
        ]
    )


def _render_build_rows_table(build_rows: List[Dict[str, Any]]) -> None:
    """渲染适合后台查看的紧凑任务表。"""
    if not build_rows:
        _render_empty_state("当前筛选下没有任务", "请调整筛选条件，或先创建新的构建任务。")
        return

    display_rows = []
    for row in build_rows:
        display_rows.append(
            {
                "任务 ID": row.get("job_id"),
                "状态": _format_status_label(row.get("status")),
                "类型": row.get("job_type"),
                "版本": row.get("version_id"),
                "创建时间": _format_datetime_text(row.get("created_at")),
                "结束时间": _format_datetime_text(row.get("finished_at")),
                "最近消息": str(row.get("message") or "-")[:48],
            }
        )
    dataframe = pd.DataFrame(_stringify_record_values(display_rows))
    st.dataframe(
        dataframe,
        use_container_width=True,
        hide_index=True,
        height=320,
    )


def _render_build_job_selector(build_rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """渲染任务选择器，并返回选中的任务。"""
    job_options = {
        _format_build_job_option(item): item["job_id"]
        for item in build_rows
    }
    default_job_id = st.session_state.get("admin_selected_job_id")
    option_labels = list(job_options.keys())
    selected_index = 0
    if default_job_id:
        for idx, label in enumerate(option_labels):
            if job_options[label] == default_job_id:
                selected_index = idx
                break
    selected_label = st.selectbox(
        "选择任务",
        options=option_labels,
        index=selected_index,
        key="admin_build_monitor_job",
    )
    selected_job_id = job_options[selected_label]
    st.session_state.admin_selected_job_id = selected_job_id
    return next(
        (row for row in build_rows if row.get("job_id") == selected_job_id),
        {},
    )


def _render_job_compact_list(build_rows: List[Dict[str, Any]], selected_job_id: str | None) -> None:
    """渲染左侧紧凑任务列表。"""
    for row in build_rows:
        is_selected = row.get("job_id") == selected_job_id
        st.markdown(
            _render_job_card(row, is_selected=is_selected),
            unsafe_allow_html=True,
        )


def _render_build_job_detail(job_detail: Dict[str, Any], job_logs: Dict[str, Any]) -> None:
    """渲染任务详情区域。"""
    status_cols = st.columns([1.1, 1.0, 1.2, 1.5])
    with status_cols[0]:
        st.markdown(
            _render_status_badge(job_detail.get("status", "-")),
            unsafe_allow_html=True,
        )
    status_cols[1].metric("任务类型", job_detail.get("job_type", "-"))
    status_cols[2].metric("关联版本", job_detail.get("version_id", "-"))
    status_cols[3].metric("当前阶段", job_detail.get("stage") or "-")

    message_text = job_detail.get("message") or "暂无状态消息"
    st.markdown(
        f"<div class='admin-detail-card'><strong>最近消息</strong><br>{html.escape(str(message_text))}</div>",
        unsafe_allow_html=True,
    )
    progress_value = _normalize_progress_value(job_detail.get("progress"))
    st.progress(progress_value, text=_format_progress_text(job_detail))

    meta_cols = st.columns(3)
    meta_cols[0].caption(f"创建时间：{_format_datetime_text(job_detail.get('created_at'))}")
    meta_cols[1].caption(f"开始时间：{_format_datetime_text(job_detail.get('started_at'))}")
    meta_cols[2].caption(f"结束时间：{_format_datetime_text(job_detail.get('finished_at'))}")

    timeline_tab, live_log_tab = st.tabs(["进度时间线", "实时日志"])
    log_lines = job_logs.get("lines", [])

    with timeline_tab:
        st.caption(f"日志文件: {job_logs.get('path') or '未生成'}")
        timeline_items = _build_timeline_items(job_detail, log_lines)
        if timeline_items:
            for item in timeline_items:
                st.markdown(_render_timeline_item(item), unsafe_allow_html=True)
        else:
            st.info("当前还没有可展示的进度事件。")

    with live_log_tab:
        if job_detail.get("status") in {"pending", "running"}:
            st.caption("当前任务运行中，日志和状态优先从本地文件读取，仅低频同步任务列表。")
        st.code("\n".join(log_lines), language="log")


def _format_build_job_option(row: Dict[str, Any]) -> str:
    """格式化下拉框中的任务标签。"""
    return (
        f"{_format_status_label(row.get('status'))} | "
        f"{row.get('job_type') or '-'} | "
        f"{row.get('job_id') or '-'}"
    )


def _render_job_card(row: Dict[str, Any], *, is_selected: bool) -> str:
    """渲染任务卡片。"""
    selected_class = "admin-job-card selected" if is_selected else "admin-job-card"
    message = html.escape(str(row.get("message") or "暂无状态消息"))
    return f"""
    <div class="{selected_class}">
      <div class="admin-job-card-header">
        <span class="admin-job-card-status">{html.escape(_format_status_label(row.get("status")))}</span>
        <span class="admin-job-card-type">{html.escape(str(row.get("job_type") or '-'))}</span>
      </div>
      <div class="admin-job-card-id">{html.escape(str(row.get("job_id") or '-'))}</div>
      <div class="admin-job-card-version">版本：{html.escape(str(row.get("version_id") or '-'))}</div>
      <div class="admin-job-card-time">创建于：{html.escape(_format_datetime_text(row.get("created_at")))}</div>
      <div class="admin-job-card-message">{message}</div>
    </div>
    """


def _format_status_label(status: Any) -> str:
    """将状态值转换为中文标签。"""
    mapping = {
        "pending": "待执行",
        "running": "运行中",
        "succeeded": "已完成",
        "failed": "失败",
        "building": "构建中",
    }
    return mapping.get(str(status), str(status or "-"))


def _format_datetime_text(value: Any) -> str:
    """格式化时间文本，便于后台列表查看。"""
    if not value:
        return "-"
    text = str(value).replace("T", " ")
    return text.split(".")[0]


def _load_local_job_status(job_row: Dict[str, Any]) -> Dict[str, Any]:
    """从本地状态文件读取任务最新状态。"""
    merged = dict(job_row)
    log_path = str(merged.get("log_path") or "").strip()
    if not log_path:
        return merged
    status_path = Path(log_path).with_suffix(".status.json")
    if not status_path.exists():
        return merged
    try:
        payload = json.loads(status_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return merged
    merged.update(payload)
    return merged


def _load_local_job_logs(job_detail: Dict[str, Any], lines: int = 200) -> Dict[str, Any]:
    """从本地日志文件读取构建日志。"""
    log_path = str(job_detail.get("log_path") or "").strip()
    if not log_path:
        return {"path": None, "lines": ["日志路径未生成"]}
    path_obj = Path(log_path)
    if not path_obj.exists():
        return {"path": str(path_obj), "lines": ["日志文件不存在或尚未创建"]}
    try:
        content = path_obj.read_text(encoding="utf-8", errors="ignore").splitlines()
    except OSError as exc:
        return {"path": str(path_obj), "lines": [f"读取日志失败：{exc}"]}
    return {"path": str(path_obj), "lines": content[-lines:]}


def _render_status_badge(status: str) -> str:
    """渲染任务状态彩色条。"""
    palette = {
        "pending": ("待执行", "#8c6d1f", "#f7e3a1"),
        "running": ("运行中", "#0b6e4f", "#b8ecd7"),
        "succeeded": ("已完成", "#0b5394", "#cfe6ff"),
        "failed": ("失败", "#8a1c1c", "#ffc9c9"),
        "building": ("构建中", "#6b3fa0", "#e2d4ff"),
    }
    label, text_color, bg_color = palette.get(
        str(status),
        (str(status), "#333333", "#e7e7e7"),
    )
    return (
        f"<div class='admin-status-pill' style='color:{text_color};"
        f"background:{bg_color};'>{html.escape(label)}</div>"
    )


def _build_timeline_items(job_detail: Dict[str, Any], log_lines: List[str]) -> List[Dict[str, str]]:
    """根据任务详情和日志构建进度时间线。"""
    items: List[Dict[str, str]] = []
    created_at = job_detail.get("created_at")
    started_at = job_detail.get("started_at")
    finished_at = job_detail.get("finished_at")
    message = job_detail.get("message") or ""
    stage = job_detail.get("stage") or ""

    if created_at:
        items.append({"time": str(created_at), "title": "任务已创建", "detail": "任务记录已写入元数据库。"})
    if started_at:
        items.append({"time": str(started_at), "title": "任务开始执行", "detail": "后台工作线程已启动。"})

    seen_keys = set()
    for line in log_lines:
        raw_line = str(line).strip()
        if not raw_line:
            continue
        timestamp = ""
        detail = raw_line
        matched = re.match(r"^\[(.*?)\]\s*(.*)$", raw_line)
        if matched:
            timestamp = matched.group(1)
            detail = matched.group(2)
        title = _summarize_log_line(detail)
        cache_key = f"{timestamp}|{title}|{detail}"
        if cache_key in seen_keys:
            continue
        seen_keys.add(cache_key)
        items.append({"time": timestamp or "-", "title": title, "detail": detail})

    if finished_at:
        title = "任务执行完成" if job_detail.get("status") == "succeeded" else "任务执行结束"
        detail = message or "任务结束。"
        items.append({"time": str(finished_at), "title": title, "detail": detail})
    elif message:
        detail = message
        if stage:
            detail = f"{message}\n阶段: {stage}"
        items.append({"time": "-", "title": "当前进度", "detail": detail})

    return items


def _summarize_log_line(detail: str) -> str:
    """将日志消息收敛为简短阶段名称。"""
    mappings = [
        ("开始执行", "开始构建"),
        ("执行增量构建流程", "增量构建"),
        ("执行全量重建流程", "全量重建"),
        ("构建成功", "构建成功"),
        ("构建失败", "构建失败"),
        ("应用", "应用修正规则"),
    ]
    for keyword, title in mappings:
        if keyword in detail:
            return title
    return detail[:24] + ("..." if len(detail) > 24 else "")


def _normalize_progress_value(raw_value: Any) -> float:
    """将任意进度值归一化到 Streamlit 进度条需要的 0-1 区间。"""
    try:
        value = float(raw_value)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, value))


def _format_progress_text(job_detail: Dict[str, Any]) -> str:
    """格式化进度条说明文本。"""
    progress_value = _normalize_progress_value(job_detail.get("progress"))
    percent_text = f"{progress_value * 100:.0f}%"
    message = str(job_detail.get("message") or "等待状态更新")
    stage = str(job_detail.get("stage") or "").strip()
    if stage:
        return f"{percent_text} | {stage} | {message}"
    return f"{percent_text} | {message}"


def _render_timeline_item(item: Dict[str, str]) -> str:
    """渲染单条时间线项。"""
    return f"""
    <div class="admin-timeline-item">
      <div class="admin-timeline-dot"></div>
      <div class="admin-timeline-content">
        <div class="admin-timeline-time">{html.escape(item.get("time", "-"))}</div>
        <div class="admin-timeline-title">{html.escape(item.get("title", ""))}</div>
        <div class="admin-timeline-detail">{html.escape(item.get("detail", ""))}</div>
      </div>
    </div>
    """


def _inject_admin_styles() -> None:
    """注入后台管理页样式。"""
    st.markdown(
        """
        <style>
        :root {
            --admin-bg: #f5f5f7;
            --admin-surface: #ffffff;
            --admin-surface-soft: #fbfbfd;
            --admin-dark: #000000;
            --admin-dark-card: #1d1d1f;
            --admin-text: #1d1d1f;
            --admin-muted: rgba(29, 29, 31, 0.72);
            --admin-subtle: rgba(29, 29, 31, 0.48);
            --admin-border: rgba(29, 29, 31, 0.08);
            --admin-accent: #0071e3;
            --admin-accent-strong: #0066cc;
            --admin-shadow: rgba(0, 0, 0, 0.12) 0px 12px 32px;
        }
        .stApp {
            background: var(--admin-bg);
            color: var(--admin-text);
            font-family: "SF Pro Text", "Helvetica Neue", Helvetica, Arial, sans-serif;
        }
        .main .block-container {
            max-width: 1440px;
            padding-top: 2rem;
            padding-bottom: 4rem;
        }
        h1, h2, h3, h4, h5 {
            font-family: "SF Pro Display", "Helvetica Neue", Helvetica, Arial, sans-serif;
            color: var(--admin-text);
            letter-spacing: -0.02em;
        }
        .admin-hero {
            background: var(--admin-dark);
            border-radius: 28px;
            padding: 2.6rem 2.4rem;
            display: grid;
            grid-template-columns: minmax(0, 2fr) minmax(280px, 1fr);
            gap: 1.6rem;
            color: #ffffff;
            margin-bottom: 1.4rem;
            box-shadow: rgba(0, 0, 0, 0.22) 3px 5px 30px 0px;
        }
        .admin-hero-kicker {
            font-size: 0.82rem;
            line-height: 1.3;
            letter-spacing: 0.08em;
            text-transform: uppercase;
            color: rgba(255, 255, 255, 0.68);
            margin-bottom: 0.9rem;
        }
        .admin-hero h1 {
            color: #ffffff;
            font-size: clamp(2.2rem, 5vw, 3.6rem);
            line-height: 1.08;
            margin: 0 0 0.8rem 0;
        }
        .admin-hero p {
            font-size: 1rem;
            line-height: 1.6;
            color: rgba(255, 255, 255, 0.82);
            max-width: 56rem;
            margin: 0;
        }
        .admin-hero-tags {
            display: flex;
            flex-wrap: wrap;
            gap: 0.7rem;
            margin-top: 1.3rem;
        }
        .admin-hero-tags span {
            display: inline-flex;
            align-items: center;
            min-height: 2.1rem;
            padding: 0 0.95rem;
            border-radius: 999px;
            border: 1px solid rgba(255, 255, 255, 0.16);
            color: #ffffff;
            background: rgba(255, 255, 255, 0.08);
            font-size: 0.92rem;
        }
        .admin-hero-panel {
            background: #101012;
            border: 1px solid rgba(255, 255, 255, 0.08);
            border-radius: 24px;
            padding: 1.4rem 1.3rem;
            display: flex;
            flex-direction: column;
            justify-content: space-between;
        }
        .admin-hero-panel-label {
            color: rgba(255, 255, 255, 0.58);
            font-size: 0.8rem;
            text-transform: uppercase;
            letter-spacing: 0.08em;
        }
        .admin-hero-panel-value {
            color: #ffffff;
            font-size: 1.24rem;
            line-height: 1.45;
            font-weight: 600;
            margin-top: 1rem;
        }
        .admin-hero-panel-meta {
            color: rgba(255, 255, 255, 0.64);
            font-size: 0.88rem;
            line-height: 1.5;
            margin-top: 1rem;
        }
        .admin-section-intro {
            margin: 1.35rem 0 0.9rem 0;
        }
        .admin-section-intro.compact {
            margin-top: 0.4rem;
        }
        .admin-section-intro h2 {
            font-size: 2rem;
            line-height: 1.12;
            margin: 0;
        }
        .admin-section-intro p {
            margin: 0.35rem 0 0 0;
            color: var(--admin-muted);
            font-size: 0.98rem;
            line-height: 1.55;
            max-width: 52rem;
        }
        .admin-metric-card {
            border-radius: 22px;
            padding: 1.2rem 1.15rem;
            min-height: 8.7rem;
            display: flex;
            flex-direction: column;
            justify-content: space-between;
            border: 1px solid var(--admin-border);
            background: var(--admin-surface);
            box-shadow: var(--admin-shadow);
        }
        .admin-metric-card.dark {
            background: var(--admin-dark-card);
            color: #ffffff;
            border-color: rgba(255, 255, 255, 0.06);
        }
        .admin-metric-card.accent {
            background: #eef5ff;
            border-color: rgba(0, 113, 227, 0.18);
        }
        .admin-metric-card.warning {
            background: #fff8e8;
            border-color: rgba(138, 90, 0, 0.14);
        }
        .admin-metric-card.info {
            background: #f7fbff;
            border-color: rgba(0, 102, 204, 0.12);
        }
        .admin-metric-label {
            font-size: 0.84rem;
            color: var(--admin-subtle);
        }
        .admin-metric-card.dark .admin-metric-label,
        .admin-metric-card.dark .admin-metric-meta {
            color: rgba(255, 255, 255, 0.64);
        }
        .admin-metric-value {
            font-size: 2rem;
            line-height: 1.08;
            font-weight: 600;
            letter-spacing: -0.03em;
            margin: 0.45rem 0;
        }
        .admin-metric-card.accent .admin-metric-value {
            color: var(--admin-accent-strong);
        }
        .admin-metric-meta {
            font-size: 0.88rem;
            line-height: 1.45;
            color: var(--admin-muted);
        }
        .admin-callout {
            display: flex;
            flex-direction: column;
            gap: 0.3rem;
            border-radius: 18px;
            padding: 1rem 1.15rem;
            margin: 0.9rem 0;
            border: 1px solid var(--admin-border);
            background: var(--admin-surface);
        }
        .admin-callout strong {
            font-size: 0.96rem;
        }
        .admin-callout span {
            color: var(--admin-muted);
            font-size: 0.92rem;
            line-height: 1.55;
        }
        .admin-callout.info {
            background: #f7fbff;
            border-color: rgba(0, 102, 204, 0.12);
        }
        .admin-callout.warning {
            background: #fff8e8;
            border-color: rgba(138, 90, 0, 0.14);
        }
        .admin-callout.dark {
            background: var(--admin-dark-card);
            border-color: rgba(255, 255, 255, 0.06);
        }
        .admin-callout.dark strong,
        .admin-callout.dark span {
            color: rgba(255, 255, 255, 0.88);
        }
        .admin-empty-state {
            display: flex;
            flex-direction: column;
            gap: 0.35rem;
            align-items: flex-start;
            padding: 1.1rem 1.2rem;
            border-radius: 18px;
            background: var(--admin-surface-soft);
            border: 1px dashed rgba(29, 29, 31, 0.12);
            color: var(--admin-text);
        }
        .admin-empty-state span {
            color: var(--admin-muted);
            line-height: 1.5;
        }
        .admin-step-list {
            display: grid;
            gap: 0.8rem;
        }
        .admin-step-item {
            display: grid;
            grid-template-columns: 44px minmax(0, 1fr);
            gap: 0.85rem;
            align-items: start;
            background: var(--admin-surface);
            border: 1px solid var(--admin-border);
            border-radius: 18px;
            padding: 0.95rem 1rem;
            box-shadow: rgba(0, 0, 0, 0.06) 0px 10px 24px;
        }
        .admin-step-item span {
            width: 44px;
            height: 44px;
            border-radius: 999px;
            background: var(--admin-dark-card);
            color: #ffffff;
            display: inline-flex;
            align-items: center;
            justify-content: center;
            font-size: 0.86rem;
            font-weight: 600;
        }
        .admin-step-item div {
            color: var(--admin-muted);
            line-height: 1.5;
            font-size: 0.94rem;
        }
        .admin-step-item strong {
            color: var(--admin-text);
        }
        [data-testid="stTabs"] [data-baseweb="tab-list"] {
            gap: 0.45rem;
            background: rgba(29, 29, 31, 0.92);
            padding: 0.38rem;
            border-radius: 999px;
            backdrop-filter: saturate(180%) blur(20px);
            margin-top: 1rem;
        }
        [data-testid="stTabs"] [data-baseweb="tab"] {
            color: rgba(255, 255, 255, 0.72);
            border-radius: 999px;
            padding: 0.45rem 1rem;
            font-weight: 500;
        }
        [data-testid="stTabs"] [aria-selected="true"] {
            background: rgba(255, 255, 255, 0.96);
            color: var(--admin-text);
        }
        [data-testid="stTextInputRootElement"],
        [data-testid="stNumberInputContainer"],
        [data-testid="stFileUploaderDropzone"],
        .stTextArea textarea,
        .stSelectbox [data-baseweb="select"] > div,
        .stMultiSelect [data-baseweb="select"] > div {
            border-radius: 14px !important;
            border-color: rgba(29, 29, 31, 0.12) !important;
            background: rgba(255, 255, 255, 0.96) !important;
        }
        .stButton > button,
        .stDownloadButton > button,
        .stFormSubmitButton > button {
            min-height: 2.75rem;
            border-radius: 999px;
            border: 1px solid transparent;
            font-weight: 500;
            transition: all 0.18s ease;
        }
        .stButton > button[kind="primary"],
        .stDownloadButton > button[kind="primary"],
        .stFormSubmitButton > button[kind="primary"] {
            background: var(--admin-accent);
            color: #ffffff;
        }
        .stButton > button[kind="secondary"],
        .stDownloadButton > button[kind="secondary"],
        .stFormSubmitButton > button[kind="secondary"] {
            background: rgba(255, 255, 255, 0.92);
            color: var(--admin-text);
            border-color: rgba(29, 29, 31, 0.12);
        }
        .stButton > button:hover,
        .stDownloadButton > button:hover,
        .stFormSubmitButton > button:hover {
            transform: translateY(-1px);
        }
        [data-testid="stDataFrame"],
        [data-testid="stTable"] {
            border-radius: 18px;
            overflow: hidden;
            border: 1px solid rgba(29, 29, 31, 0.08);
            box-shadow: rgba(0, 0, 0, 0.06) 0px 10px 24px;
            background: var(--admin-surface);
        }
        .admin-status-pill {
            display: inline-flex;
            align-items: center;
            justify-content: center;
            width: 100%;
            min-height: 70px;
            border-radius: 18px;
            font-size: 22px;
            font-weight: 600;
            letter-spacing: -0.02em;
        }
        .admin-detail-card {
            background: var(--admin-surface);
            border: 1px solid var(--admin-border);
            border-radius: 18px;
            padding: 14px 16px;
            margin: 8px 0 14px 0;
            color: var(--admin-text);
            line-height: 1.5;
            box-shadow: rgba(0, 0, 0, 0.06) 0px 10px 24px;
        }
        .admin-job-card {
            background: var(--admin-surface);
            border: 1px solid var(--admin-border);
            border-radius: 18px;
            padding: 12px 14px;
            margin-bottom: 10px;
            box-shadow: rgba(0, 0, 0, 0.05) 0px 8px 18px;
        }
        .admin-job-card.selected {
            border-color: rgba(0, 113, 227, 0.22);
            box-shadow: rgba(0, 113, 227, 0.08) 0px 10px 24px;
            background: #f7fbff;
        }
        .admin-job-card-header {
            display: flex;
            justify-content: space-between;
            gap: 12px;
            margin-bottom: 6px;
            font-size: 12px;
            font-weight: 700;
        }
        .admin-job-card-status {
            color: var(--admin-accent-strong);
        }
        .admin-job-card-type {
            color: var(--admin-muted);
        }
        .admin-job-card-id {
            font-size: 14px;
            font-weight: 700;
            color: var(--admin-text);
            word-break: break-all;
            margin-bottom: 6px;
        }
        .admin-job-card-version,
        .admin-job-card-time {
            font-size: 12px;
            color: var(--admin-muted);
            margin-bottom: 4px;
            word-break: break-all;
        }
        .admin-job-card-message {
            font-size: 13px;
            color: var(--admin-muted);
            margin-top: 6px;
            line-height: 1.45;
            word-break: break-word;
        }
        .admin-process-card {
            display: flex;
            justify-content: space-between;
            align-items: flex-start;
            gap: 1rem;
            background: var(--admin-surface);
            border: 1px solid var(--admin-border);
            border-radius: 18px;
            padding: 1rem 1.1rem;
            margin: 0.85rem 0 0.35rem 0;
            box-shadow: rgba(0, 0, 0, 0.05) 0px 8px 18px;
        }
        .admin-process-title {
            font-size: 1rem;
            font-weight: 600;
            color: var(--admin-text);
        }
        .admin-process-meta,
        .admin-process-note {
            color: var(--admin-muted);
            font-size: 0.88rem;
            line-height: 1.5;
            margin-top: 0.22rem;
        }
        .admin-process-state {
            min-width: 5.5rem;
            text-align: center;
            border-radius: 999px;
            padding: 0.42rem 0.78rem;
            background: #eef5ff;
            color: var(--admin-accent-strong);
            font-size: 0.88rem;
            font-weight: 600;
        }
        .admin-timeline-item {
            display: flex;
            gap: 14px;
            padding: 12px 0 12px 6px;
            border-left: 2px solid rgba(0, 113, 227, 0.14);
            margin-left: 10px;
        }
        .admin-timeline-dot {
            width: 12px;
            height: 12px;
            margin-left: -21px;
            margin-top: 6px;
            border-radius: 999px;
            background: var(--admin-accent);
            border: 2px solid var(--admin-bg);
            flex: 0 0 12px;
        }
        .admin-timeline-content {
            background: var(--admin-surface);
            border-radius: 16px;
            padding: 10px 14px;
            width: 100%;
            box-shadow: rgba(0, 0, 0, 0.05) 0px 8px 18px;
        }
        .admin-timeline-time {
            font-size: 12px;
            color: var(--admin-subtle);
            margin-bottom: 4px;
        }
        .admin-timeline-title {
            font-size: 15px;
            font-weight: 600;
            color: var(--admin-text);
            margin-bottom: 4px;
        }
        .admin-timeline-detail {
            font-size: 13px;
            color: var(--admin-muted);
            white-space: pre-wrap;
            word-break: break-word;
        }
        @media (max-width: 980px) {
            .admin-hero {
                grid-template-columns: 1fr;
                padding: 1.8rem 1.4rem;
            }
            .admin-metric-card {
                min-height: 7.6rem;
            }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


if __name__ == "__main__":
    main()
