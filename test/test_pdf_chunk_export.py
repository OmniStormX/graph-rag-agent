"""导出指定 PDF 的分块结果，便于人工检查。"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import List

from graphrag_agent.config.settings import CHUNK_SIZE, FILES_DIR, OVERLAP
from graphrag_agent.pipelines.ingestion.file_reader import FileReader
from graphrag_agent.pipelines.ingestion.text_chunker import ChineseTextChunker


PDF_FILE_NAME = "Ch 1_2.pdf"
OUTPUT_DIR_NAME = "txt文件"


def export_pdf_chunks(
    pdf_file_name: str = PDF_FILE_NAME,
    output_dir_name: str = OUTPUT_DIR_NAME,
) -> Path:
    """导出 PDF 分块结果到指定目录。

    处理步骤：
        1. 读取 PDF 文本。
        2. 使用项目当前 HanLP 分词配置做预处理。
        3. 按 chunk_size / overlap 执行文本分块。
        4. 将每个分块结果导出为独立 txt 文件。

    Returns:
        导出目录路径。
    """
    pdf_path = FILES_DIR / pdf_file_name
    if not pdf_path.exists():
        raise FileNotFoundError(f"未找到测试文件: {pdf_path}")

    output_dir = FILES_DIR / output_dir_name
    output_dir.mkdir(parents=True, exist_ok=True)

    reader = FileReader(str(FILES_DIR))
    chunker = ChineseTextChunker(chunk_size=CHUNK_SIZE, overlap=OVERLAP)

    raw_text = reader._read_pdf(str(pdf_path))
    chunks = chunker.chunk_text(raw_text)

    exported_files: List[Path] = []
    for index, chunk_tokens in enumerate(chunks, start=1):
        chunk_text = "".join(chunk_tokens)
        chunk_prefix = pdf_path.stem.replace(" ", "_")
        chunk_file = output_dir / f"{chunk_prefix}_chunk_{index:04d}.txt"
        chunk_file.write_text(chunk_text, encoding="utf-8")
        exported_files.append(chunk_file)

    summary_lines = [
        f"源文件: {pdf_path}",
        f"输出目录: {output_dir}",
        f"文本总长度: {len(raw_text)}",
        f"分块总数: {len(chunks)}",
        f"chunk_size: {CHUNK_SIZE}",
        f"overlap: {OVERLAP}",
        "",
        "导出文件列表:",
    ]
    summary_lines.extend(str(path.name) for path in exported_files)
    summary_file = output_dir / f"{pdf_path.stem.replace(' ', '_')}_chunk_summary.txt"
    summary_file.write_text(
        "\n".join(summary_lines),
        encoding="utf-8",
    )
    return output_dir


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="导出指定 PDF 的分块结果")
    parser.add_argument("--pdf", default=PDF_FILE_NAME, help="待处理的 PDF 文件名，默认从 files 目录读取")
    parser.add_argument("--output-dir", default=OUTPUT_DIR_NAME, help="输出目录名，默认位于 files 下")
    args = parser.parse_args()

    exported_dir = export_pdf_chunks(
        pdf_file_name=args.pdf,
        output_dir_name=args.output_dir,
    )
    print(f"分块结果已导出到: {exported_dir}")
