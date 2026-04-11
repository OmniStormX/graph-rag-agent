from typing import Any, Callable, Dict, Optional

from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from graphrag_agent.graph.core import connection_manager
from graphrag_agent.integrations.build.build_graph import KnowledgeGraphBuilder
from graphrag_agent.integrations.build.build_index_and_community import IndexCommunityBuilder
from graphrag_agent.integrations.build.build_chunk_index import ChunkIndexBuilder

ProgressCallback = Optional[Callable[[Dict[str, Any]], None]]


class KnowledgeGraphProcessor:
    """
    知识图谱处理器，整合了图谱构建和索引处理的完整流程。
    可以选择完整流程或单独执行其中一个步骤。
    """

    def __init__(self, progress_callback: ProgressCallback = None):
        """初始化知识图谱处理器。

        Args:
            progress_callback: 外部进度回调，用于向后台管理系统同步阶段状态。
        """
        self.console = Console()
        self.progress_callback = progress_callback

    def _emit_progress(self, message: str, progress: float, stage: str) -> None:
        """向外部发出结构化进度事件。"""
        if not self.progress_callback:
            return
        self.progress_callback(
            {
                "stage": stage,
                "message": message,
                "progress": progress,
            }
        )

    def process_all(self):
        """执行完整的处理流程。"""
        try:
            # 显示开始面板
            start_text = Text("开始知识图谱处理流程", style="bold cyan")
            self.console.print(Panel(start_text, border_style="cyan"))
            self._emit_progress("开始知识图谱处理流程", 0.02, "bootstrap")

            # 0. 清除所有旧索引（防止索引冲突）
            self.console.print("\n[bold yellow]步骤 0: 清除所有旧索引[/bold yellow]")
            self._emit_progress("清除旧索引", 0.08, "drop_indexes")
            connection_manager.drop_all_indexes()

            # 1. 构建基础图谱
            self.console.print("\n[bold cyan]步骤 1: 构建基础图谱[/bold cyan]")
            self._emit_progress("开始构建基础图谱", 0.12, "build_graph")
            graph_builder = KnowledgeGraphBuilder(progress_callback=self.progress_callback)
            graph_builder.process()

            # 2. 构建实体索引和社区
            self.console.print("\n[bold cyan]步骤 2: 构建实体索引和社区[/bold cyan]")
            self._emit_progress("开始构建索引与社区", 0.62, "build_index")
            index_builder = IndexCommunityBuilder(progress_callback=self.progress_callback)
            index_builder.process()

            # 3. 构建Chunk索引
            self.console.print("\n[bold cyan]步骤 3: 构建Chunk索引[/bold cyan]")
            self._emit_progress("开始构建 Chunk 索引", 0.90, "build_chunk_index")
            chunk_index_builder = ChunkIndexBuilder()
            chunk_index_builder.process()

            # 显示完成面板
            success_text = Text("知识图谱处理流程完成", style="bold green")
            self.console.print(Panel(success_text, border_style="green"))
            self._emit_progress("知识图谱处理流程完成", 1.0, "completed")

        except Exception as e:
            error_text = Text(f"处理过程中出现错误: {str(e)}", style="bold red")
            self.console.print(Panel(error_text, border_style="red"))
            self._emit_progress(f"处理过程中出现错误: {str(e)}", 1.0, "failed")
            raise

if __name__ == "__main__":
    try:
        processor = KnowledgeGraphProcessor()
        processor.process_all()
    except Exception as e:
        console = Console()
        console.print(f"[red]执行过程中出现错误: {str(e)}[/red]")
