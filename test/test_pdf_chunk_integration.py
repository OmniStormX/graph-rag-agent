"""验证正式 PDF 切片流程的集成测试。"""

from __future__ import annotations

import statistics
import unittest
from pathlib import Path


class TestPdfChunkIntegration(unittest.TestCase):
    """覆盖 PDF 读取与分块的正式集成链路。"""

    PDF_NAME = "Ch 1_2.pdf"
    OUTPUT_DIR_NAME = "txt文件"

    def test_document_processor_chunks_target_pdf(self) -> None:
        """验证目标 PDF 会通过正式流程产生稳定的分块结果。"""
        try:
            from graphrag_agent.config.settings import CHUNK_SIZE, FILES_DIR, OVERLAP
            from graphrag_agent.pipelines.ingestion.document_processor import (
                DocumentProcessor,
            )
            from graphrag_agent.pipelines.ingestion.file_reader import PyPDF2
        except ImportError as exc:
            self.skipTest(f"当前环境缺少 PDF 集成测试依赖: {exc}")
            return

        if PyPDF2 is None:
            self.skipTest("当前环境未安装 PyPDF2，无法执行 PDF 集成测试。")
            return

        pdf_path = Path(FILES_DIR) / self.PDF_NAME
        if not pdf_path.exists():
            self.skipTest(f"未找到目标测试文件: {pdf_path}")
            return

        processor = DocumentProcessor(
            directory_path=str(FILES_DIR),
            chunk_size=CHUNK_SIZE,
            overlap=OVERLAP,
        )
        results = processor.process_directory(file_extensions=[".pdf"], recursive=False)

        target_doc = next(
            (item for item in results if item.get("filename") == self.PDF_NAME),
            None,
        )
        self.assertIsNotNone(target_doc, f"未在处理结果中找到 {self.PDF_NAME}")

        chunks = target_doc.get("chunks") or []
        chunk_lengths = target_doc.get("chunk_lengths") or []

        self.assertGreater(len(chunks), 0, "PDF 经过正式流程后未生成任何 chunk")
        self.assertEqual(
            target_doc.get("chunk_count"),
            len(chunks),
            "chunk_count 与实际 chunk 数量不一致",
        )
        self.assertEqual(
            len(chunk_lengths),
            len(chunks),
            "chunk_lengths 与实际 chunk 数量不一致",
        )
        self.assertGreater(
            target_doc.get("content_length", 0),
            0,
            "PDF 抽取后的正文长度必须大于 0",
        )

        non_empty_chunks = ["".join(chunk).strip() for chunk in chunks if "".join(chunk).strip()]
        self.assertEqual(
            len(non_empty_chunks),
            len(chunks),
            "正式切片流程不应产出空 chunk",
        )

        export_dir = self._export_chunks_to_txt(
            files_dir=Path(FILES_DIR),
            pdf_path=pdf_path,
            target_doc=target_doc,
            chunk_texts=non_empty_chunks,
            chunk_lengths=chunk_lengths,
            chunk_size=CHUNK_SIZE,
            overlap=OVERLAP,
        )

        # 这里不对具体 chunk 数做硬编码，避免后续优化清洗逻辑时测试变脆。
        # 但至少要求 chunk 长度分布有波动，便于发现退化成固定窗口硬切的情况。
        unique_lengths = len(set(chunk_lengths))
        self.assertGreater(
            unique_lengths,
            3,
            "chunk 长度分布过于单一，疑似退化成固定窗口硬切",
        )

        first_chunk_preview = non_empty_chunks[0][:160]
        middle_chunk_preview = non_empty_chunks[len(non_empty_chunks) // 2][:160]
        last_chunk_preview = non_empty_chunks[-1][:160]
        stats_line = (
            f"PDF={self.PDF_NAME} | strategy={target_doc.get('chunk_strategy')} "
            f"| chunks={len(chunks)} | min={min(chunk_lengths)} | "
            f"median={statistics.median(chunk_lengths):.1f} | "
            f"max={max(chunk_lengths)}"
        )
        print(stats_line)
        print(f"FIRST: {first_chunk_preview}")
        print(f"MIDDLE: {middle_chunk_preview}")
        print(f"LAST: {last_chunk_preview}")
        print(f"EXPORTED_TO: {export_dir}")

    def _export_chunks_to_txt(
        self,
        files_dir: Path,
        pdf_path: Path,
        target_doc: dict,
        chunk_texts: list[str],
        chunk_lengths: list[int],
        chunk_size: int,
        overlap: int,
    ) -> Path:
        """将正式流程产出的 chunk 导出为可人工检查的 txt 文件。"""
        output_dir = files_dir / self.OUTPUT_DIR_NAME
        output_dir.mkdir(parents=True, exist_ok=True)

        safe_prefix = pdf_path.stem.replace(" ", "_")
        for index, chunk_text in enumerate(chunk_texts, start=1):
            chunk_file = output_dir / f"{safe_prefix}_chunk_{index:04d}.txt"
            chunk_file.write_text(chunk_text, encoding="utf-8")

        summary_lines = [
            f"源文件: {pdf_path}",
            f"输出目录: {output_dir}",
            f"分块策略: {target_doc.get('chunk_strategy')}",
            f"文本总长度: {target_doc.get('content_length', 0)}",
            f"分块总数: {len(chunk_texts)}",
            f"chunk_size: {chunk_size}",
            f"overlap: {overlap}",
            f"最短块长度: {min(chunk_lengths)}",
            f"中位块长度: {statistics.median(chunk_lengths):.1f}",
            f"最长块长度: {max(chunk_lengths)}",
            "",
            "分块文件列表:",
        ]
        summary_lines.extend(
            f"{safe_prefix}_chunk_{index:04d}.txt"
            for index in range(1, len(chunk_texts) + 1)
        )

        summary_file = output_dir / f"{safe_prefix}_chunk_summary.txt"
        summary_file.write_text("\n".join(summary_lines), encoding="utf-8")
        return output_dir


if __name__ == "__main__":
    unittest.main()
