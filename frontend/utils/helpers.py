import html
import json
import re
from typing import Any, Dict, List, Tuple
import streamlit as st


_INLINE_POINTS_PATTERN = re.compile(
    r"\{\{?\s*['\"]points['\"]\s*:\s*\[[\s\S]*?\]\s*\}\}?",
    re.IGNORECASE,
)
_INLINE_DATA_PATTERN = re.compile(
    r"\{\{?\s*['\"]data['\"]\s*:\s*\{[\s\S]*?\}\s*\}\}?",
    re.IGNORECASE,
)
_TRAILING_REFERENCE_BLOCK_PATTERN = re.compile(
    r"\n*#{1,4}\s*引用数据\s*\n+\s*(?:\{\{?[\s\S]*?\}\}?)*\s*$",
    re.IGNORECASE,
)
_MATHISH_LINE_PATTERN = re.compile(
    r"^[A-Za-z0-9_+\-*/=<>^%.,:;(){}\[\]（）\\|`~'\"△Δδ∂∫∑Σ∞≤≥±×÷·⋅\s]+$"
)


def _strip_legacy_inline_citations(content: str) -> str:
    """移除正文中旧版 `points/data` 内联引用残留。"""
    sanitized = _INLINE_POINTS_PATTERN.sub("", content)
    sanitized = _INLINE_DATA_PATTERN.sub("", sanitized)
    sanitized = _TRAILING_REFERENCE_BLOCK_PATTERN.sub("", sanitized)
    # 收尾清理多余空白，避免删除引用后留下断裂空格。
    sanitized = re.sub(r"[ \t]{2,}", " ", sanitized)
    sanitized = re.sub(r"\n*#{1,4}\s*引用数据\s*$", "", sanitized, flags=re.IGNORECASE)
    sanitized = re.sub(r"\n{3,}", "\n\n", sanitized)
    return sanitized.strip()


def _is_fragmented_math_line(line: str) -> bool:
    """判断一行是否更像被拆散的公式片段而不是自然语言。"""
    stripped = line.strip()
    if not stripped:
        return False
    if len(stripped) > 24:
        return False
    if re.search(r"[\u4e00-\u9fff]{2,}", stripped):
        return False
    if stripped.startswith(("-", "*", "1.", "2.", "3.", "#")):
        return False
    return bool(_MATHISH_LINE_PATTERN.fullmatch(stripped))


def _compact_math_block(lines: List[str]) -> str:
    """将多行碎裂公式压缩为单个 Markdown 数学块。"""
    merged = " ".join(line.strip() for line in lines if line.strip())
    merged = re.sub(r"\s+([,.;:)\]}}])", r"\1", merged)
    merged = re.sub(r"([({\[])\s+", r"\1", merged)
    merged = re.sub(r"\s{2,}", " ", merged).strip()
    if not merged:
        return ""
    return f"$$ {merged} $$"


def _normalize_fragmented_math(content: str) -> str:
    """修复一行一个符号的碎裂公式展示问题。"""
    lines = content.splitlines()
    normalized_lines: List[str] = []
    block: List[str] = []

    def _flush_block() -> None:
        """将缓存中的碎裂公式块写回结果。"""
        nonlocal block
        if len(block) >= 3 and any(
            any(token in line for token in ("=", "Δ", "δ", "∫", "∑", "≤", "≥", "±"))
            for line in block
        ):
            normalized_lines.append(_compact_math_block(block))
        else:
            normalized_lines.extend(block)
        block = []

    for line in lines:
        if _is_fragmented_math_line(line):
            block.append(line)
            continue

        _flush_block()
        normalized_lines.append(line)

    _flush_block()
    normalized = "\n".join(normalized_lines)
    return re.sub(r"\n{3,}", "\n\n", normalized).strip()


def normalize_answer_for_display(content: str) -> str:
    """统一清理回答展示层的引用残留与公式碎裂问题。"""
    if not isinstance(content, str) or not content:
        return content
    normalized = _strip_legacy_inline_citations(content)
    normalized = _normalize_fragmented_math(normalized)
    return normalized

def extract_source_ids(answer: str) -> List[str]:
    """从回答中提取引用的源ID"""
    source_ids = []
    
    # 提取Chunks IDs
    chunks_pattern = r"Chunks':\s*\[([^\]]*)\]"
    matches = re.findall(chunks_pattern, answer)
    
    if matches:
        for match in matches:
            # 处理带引号的ID
            quoted_ids = re.findall(r"'([^']*)'", match)
            if quoted_ids:
                source_ids.extend(quoted_ids)
            else:
                # 处理不带引号的ID
                ids = [id.strip() for id in match.split(',') if id.strip()]
                source_ids.extend(ids)
    
    # 去重
    return list(set(source_ids))

def display_source_content(content: Any):
    """以结构化方式显示源内容。"""
    st.markdown("""
    <style>
    .source-content {
        white-space: pre-wrap;
        overflow-x: auto;
        font-family: monospace;
        line-height: 1.6;
        background-color: #f5f5f5;
        border-radius: 5px;
        padding: 15px;
        max-height: 600px;
        overflow-y: auto;
        border: 1px solid #e1e4e8;
        color: #24292e;
    }
    </style>
    """, unsafe_allow_html=True)

    if isinstance(content, dict):
        title = content.get("title") or "源内容"
        st.subheader(str(title))
        if content.get("source_id"):
            st.caption(f"Source ID: {content.get('source_id')}")

        meta_rows = [
            {"字段": "来源类型", "值": content.get("source_type") or "-"},
            {"字段": "文件名", "值": content.get("file_name") or "-"},
            {"字段": "Chunk ID", "值": content.get("chunk_id") or "-"},
            {"字段": "Community ID", "值": content.get("community_id") or "-"},
            {"字段": "块序号", "值": content.get("position") if content.get("position") is not None else "-"},
            {"字段": "长度", "值": content.get("length") if content.get("length") is not None else "-"},
            {"字段": "偏移量", "值": content.get("content_offset") if content.get("content_offset") is not None else "-"},
        ]
        metric_col1, metric_col2, metric_col3 = st.columns(3)
        with metric_col1:
            st.metric("来源类型", str(content.get("source_type") or "-"))
        with metric_col2:
            st.metric("块序号", str(content.get("position") if content.get("position") is not None else "-"))
        with metric_col3:
            st.metric("文本长度", str(content.get("length") if content.get("length") is not None else "-"))

        with st.expander("查看元信息", expanded=False):
            st.dataframe(_to_safe_dataframe(meta_rows), use_container_width=True, hide_index=True)

        body_text = content.get("text") or content.get("full_content") or content.get("content") or ""
        tab_labels = ["正文"]
        if content.get("summary"):
            tab_labels.insert(0, "摘要")
        tab_labels.append("原始响应")
        tabs = st.tabs(tab_labels)

        tab_offset = 0
        if content.get("summary"):
            with tabs[0]:
                st.markdown(
                    f"<div class='source-content'>{html.escape(str(content.get('summary'))).replace(chr(10), '<br>')}</div>",
                    unsafe_allow_html=True,
                )
            tab_offset = 1

        with tabs[tab_offset]:
            if body_text:
                st.markdown(
                    f"<div class='source-content'>{html.escape(str(body_text)).replace(chr(10), '<br>')}</div>",
                    unsafe_allow_html=True,
                )
                st.download_button(
                    "导出当前原文",
                    data=str(body_text),
                    file_name=_build_source_export_name(content),
                    mime="text/plain",
                    use_container_width=False,
                )
            else:
                st.info("当前来源没有可展示的正文内容。")

        with tabs[tab_offset + 1]:
            st.code(
                json.dumps(_normalize_json_payload(content), ensure_ascii=False, indent=2),
                language="json",
            )

        if content.get("error"):
            st.warning(str(content.get("error")))
        return

    raw_text = str(content or "")
    formatted_content = html.escape(raw_text).replace("\n", "<br>")
    st.markdown(f'<div class="source-content">{formatted_content}</div>', unsafe_allow_html=True)


def _to_safe_dataframe(rows: List[Dict[str, Any]]):
    """构建适合 Streamlit 展示的 DataFrame。"""
    import pandas as pd

    normalized_rows: List[Dict[str, Any]] = []
    for row in rows:
        normalized_row: Dict[str, Any] = {}
        for key, value in row.items():
            if value is None or isinstance(value, (str, int, float, bool)):
                normalized_row[key] = value
            else:
                normalized_row[key] = str(value)
        normalized_rows.append(normalized_row)
    return pd.DataFrame(normalized_rows)


def _normalize_json_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    """将复杂值转换为可稳定序列化的展示结果。"""
    normalized: Dict[str, Any] = {}
    for key, value in payload.items():
        if value is None or isinstance(value, (str, int, float, bool)):
            normalized[key] = value
        else:
            normalized[key] = str(value)
    return normalized


def _build_source_export_name(content: Dict[str, Any]) -> str:
    """构造导出文件名，便于定位来源。"""
    if content.get("chunk_id"):
        return f"source_{content.get('chunk_id')}.txt"
    if content.get("community_id"):
        return f"community_{content.get('community_id')}.txt"
    if content.get("source_id"):
        return f"source_{content.get('source_id')}.txt"
    return "source_content.txt"


def process_thinking_content(content: str, show_thinking: bool = False):
    """
    处理带有思考过程的内容
    
    Args:
        content: 原始内容
        show_thinking: 是否显示思考过程
        
    Returns:
        dict: 包含处理后的内容信息
    """
    if not isinstance(content, str):
        return {"processed": content, "has_thinking": False}
        
    # 检查是否有思考过程
    if "<think>" in content and "</think>" in content:
        # 使用正则表达式提取思考过程
        think_match = re.search(r'<think>(.*?)</think>', content, re.DOTALL)
        if think_match:
            thinking_process = think_match.group(1).strip()
            # 移除思考过程部分，只保留答案
            answer_only = content.replace(f"<think>{thinking_process}</think>", "").strip()
            
            # 将思考过程格式化为Markdown引用格式
            thinking_lines = thinking_process.split('\n')
            quoted_thinking = '\n'.join([f"> {line}" for line in thinking_lines])
            
            return {
                "processed": answer_only,
                "has_thinking": True,
                "thinking": quoted_thinking,
                "original": content
            }
    
    # 如果没有思考过程或提取失败，返回原内容
    return {"processed": content, "has_thinking": False}


def render_answer_with_hover_citations(
    content: str,
) -> str:
    """
    为回答中的证据 ID 添加高亮徽标和悬停提示。

    说明：
        仅转换常见的证据引用格式，尽量不破坏原始 Markdown 结构。

    Args:
        content: 原始回答文本

    Returns:
        str: 带有 HTML 徽标的 Markdown 文本
    """
    if not isinstance(content, str) or not content:
        return content

    rendered = normalize_answer_for_display(content)
    placeholder_map: Dict[str, str] = {}
    evidence_order: List[str] = []
    evidence_index: Dict[str, int] = {}

    def _store_placeholder(html_fragment: str) -> str:
        """暂存已生成的 HTML 片段，避免后续正则再次污染。"""
        placeholder = f"__EVIDENCE_PLACEHOLDER_{len(placeholder_map)}__"
        placeholder_map[placeholder] = html_fragment
        return placeholder

    def _get_footnote_number(evidence_id: str) -> int:
        """为证据 ID 分配稳定的脚注编号。"""
        if evidence_id not in evidence_index:
            evidence_index[evidence_id] = len(evidence_order) + 1
            evidence_order.append(evidence_id)
        return evidence_index[evidence_id]

    def _build_highlight_span(keyword: str, evidence_id: str) -> str:
        """构造纯脚注上标，正文中不再显示证据标签文字。"""
        escaped_id = html.escape(evidence_id, quote=True)
        footnote_number = _get_footnote_number(evidence_id)

        html_fragment = (
            f"<sup class='evidence-footnote-ref' "
            f"data-evidence-target='{escaped_id}' "
            f"title='证据 ID: {escaped_id}'>{footnote_number}</sup>"
        )
        return _store_placeholder(html_fragment)

    # 优先处理新协议：[[ref:关键词|证据ID]]。
    rendered = re.sub(
        r"\[\[ref:([^|\]]+)\|([^\]]+)\]\]",
        lambda match: _build_highlight_span(match.group(1), match.group(2)),
        rendered,
    )

    # 优先处理“关键词[证据ID: xxx]”场景，隐藏证据ID，仅保留关键词高亮。
    rendered = re.sub(
        r"([A-Za-z\u4e00-\u9fff0-9_（）()《》“”‘’·\-]{1,24})\s*\[证据ID[:：]\s*([A-Za-z0-9][A-Za-z0-9_-]{5,})\]",
        lambda match: _build_highlight_span(match.group(1), match.group(2)),
        rendered,
    )

    # 处理“关键词[result_xxx] / 关键词[uuid-like-id]”场景。
    rendered = re.sub(
        r"([A-Za-z\u4e00-\u9fff0-9_（）()《》“”‘’·\-]{1,24})\s*\[([A-Za-z0-9][A-Za-z0-9_-]{7,})\]",
        lambda match: _build_highlight_span(match.group(1), match.group(2))
        if not match.group(2).isdigit() else match.group(0),
        rendered,
    )

    # 如果文本里只有孤立引用标记，没有可绑定的关键词，则降级为一个轻量“引用”占位。
    rendered = re.sub(
        r"\[证据ID[:：]\s*([A-Za-z0-9][A-Za-z0-9_-]{5,})\]",
        lambda match: _build_highlight_span("引用", match.group(1)),
        rendered,
    )
    rendered = re.sub(
        r"\[([A-Za-z0-9][A-Za-z0-9_-]{7,})\]",
        lambda match: _build_highlight_span("引用", match.group(1))
        if not match.group(1).isdigit() else match.group(0),
        rendered,
    )

    for placeholder, html_fragment in placeholder_map.items():
        rendered = rendered.replace(placeholder, html_fragment)

    return rendered


def extract_ordered_evidence_entries(answer: str) -> List[Tuple[str, str]]:
    """按正文出现顺序提取证据条目，用于脚注列表渲染。"""
    if not isinstance(answer, str) or not answer:
        return []

    ordered_entries: List[Tuple[str, str]] = []

    def _append_if_missing(label: str, evidence_id: str):
        """保持顺序去重，避免底部脚注重复。"""
        clean_id = str(evidence_id).strip()
        clean_label = str(label).strip() if label else "引用"
        entry = (clean_label, clean_id)
        if clean_id and entry not in ordered_entries:
            ordered_entries.append(entry)

    for match in re.finditer(r"\[\[ref:([^|\]]+)\|([^\]]+)\]\]", answer):
        _append_if_missing(match.group(1), match.group(2))

    for match in re.finditer(
        r"([A-Za-z\u4e00-\u9fff0-9_（）()《》“”‘’·\-]{1,24})\s*\[证据ID[:：]\s*([A-Za-z0-9][A-Za-z0-9_-]{5,})\]",
        answer,
    ):
        _append_if_missing(match.group(1), match.group(2))

    for match in re.finditer(
        r"([A-Za-z\u4e00-\u9fff0-9_（）()《》“”‘’·\-]{1,24})\s*\[([A-Za-z0-9][A-Za-z0-9_-]{7,})\]",
        answer,
    ):
        evidence_id = match.group(1)
        if not match.group(2).isdigit():
            _append_if_missing(match.group(1), match.group(2))

    for match in re.finditer(r"\[证据ID[:：]\s*([A-Za-z0-9][A-Za-z0-9_-]{5,})\]", answer):
        _append_if_missing("引用", match.group(1))

    for match in re.finditer(r"\[([A-Za-z0-9][A-Za-z0-9_-]{7,})\]", answer):
        evidence_id = match.group(1)
        if not evidence_id.isdigit():
            _append_if_missing("引用", evidence_id)

    # 兼容旧格式中尾部的 Chunks 引用列表。
    for source_id in extract_source_ids(answer):
        _append_if_missing("Chunks", source_id)

    return ordered_entries


def build_footnote_entries(answer: str) -> List[Tuple[int, str, str]]:
    """构造脚注编号、标签文字与证据 ID 的对应关系。"""
    return [
        (index, label, evidence_id)
        for index, (label, evidence_id) in enumerate(
            extract_ordered_evidence_entries(answer),
            start=1,
        )
    ]
