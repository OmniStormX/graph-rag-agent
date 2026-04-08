import re
import html
from typing import List
import streamlit as st

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

def display_source_content(content: str):
    """更好地显示源内容"""
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
    
    # 将换行符转换为HTML换行，确保格式正确
    formatted_content = content.replace("\n", "<br>")
    st.markdown(f'<div class="source-content">{formatted_content}</div>', unsafe_allow_html=True)


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

    rendered = content
    placeholder_map = {}

    def _store_placeholder(html_fragment: str) -> str:
        """暂存已生成的 HTML 片段，避免后续正则再次污染。"""
        placeholder = f"__EVIDENCE_PLACEHOLDER_{len(placeholder_map)}__"
        placeholder_map[placeholder] = html_fragment
        return placeholder

    def _build_highlight_span(keyword: str, evidence_id: str) -> str:
        """构造仅支持悬停提示的证据关键词高亮。"""
        escaped_id = html.escape(evidence_id, quote=True)
        escaped_keyword = html.escape(keyword)

        html_fragment = (
            f"<span class='evidence-keyword-highlight' "
            f"data-evidence-id='证据 ID: {escaped_id}' "
            f"data-evidence-target='{escaped_id}'>{escaped_keyword}</span>"
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
