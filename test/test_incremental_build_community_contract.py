"""增量构建后的社区刷新契约测试。"""

from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import types
import unittest


def _make_package(name: str) -> types.ModuleType:
    """创建最小化包模块，避免测试时触发真实工程初始化。"""
    module = types.ModuleType(name)
    module.__path__ = []
    return module


def _load_incremental_module():
    """按文件路径加载增量构建模块，并注入最小依赖替身。"""
    module_path = (
        Path(__file__).resolve().parent.parent
        / "graphrag_agent"
        / "integrations"
        / "build"
        / "incremental_graph_builder.py"
    )

    stub_modules = {
        "rich": _make_package("rich"),
        "rich.console": types.ModuleType("rich.console"),
        "rich.table": types.ModuleType("rich.table"),
        "graphrag_agent": _make_package("graphrag_agent"),
        "graphrag_agent.models": _make_package("graphrag_agent.models"),
        "graphrag_agent.models.get_models": types.ModuleType("graphrag_agent.models.get_models"),
        "graphrag_agent.config": _make_package("graphrag_agent.config"),
        "graphrag_agent.config.prompts": _make_package("graphrag_agent.config.prompts"),
        "graphrag_agent.config.prompts.graph_prompts": types.ModuleType(
            "graphrag_agent.config.prompts.graph_prompts"
        ),
        "graphrag_agent.config.settings": types.ModuleType("graphrag_agent.config.settings"),
        "graphrag_agent.pipelines": _make_package("graphrag_agent.pipelines"),
        "graphrag_agent.pipelines.ingestion": _make_package("graphrag_agent.pipelines.ingestion"),
        "graphrag_agent.pipelines.ingestion.document_processor": types.ModuleType(
            "graphrag_agent.pipelines.ingestion.document_processor"
        ),
        "graphrag_agent.graph": types.ModuleType("graphrag_agent.graph"),
        "graphrag_agent.config.neo4jdb": types.ModuleType("graphrag_agent.config.neo4jdb"),
        "graphrag_agent.integrations": _make_package("graphrag_agent.integrations"),
        "graphrag_agent.integrations.build": _make_package("graphrag_agent.integrations.build"),
        "graphrag_agent.integrations.build.incremental": _make_package(
            "graphrag_agent.integrations.build.incremental"
        ),
        "graphrag_agent.integrations.build.incremental.file_change_manager": types.ModuleType(
            "graphrag_agent.integrations.build.incremental.file_change_manager"
        ),
        "graphrag_agent.graph.indexing": _make_package("graphrag_agent.graph.indexing"),
        "graphrag_agent.graph.indexing.embedding_manager": types.ModuleType(
            "graphrag_agent.graph.indexing.embedding_manager"
        ),
        "graphrag_agent.integrations.build.build_chunk_index": types.ModuleType(
            "graphrag_agent.integrations.build.build_chunk_index"
        ),
    }

    stub_modules["graphrag_agent.models.get_models"].get_llm_model = lambda: None
    stub_modules["rich.console"].Console = lambda: types.SimpleNamespace(
        print=lambda *_args, **_kwargs: None
    )

    class _DummyTable:
        """最小表格替身。"""

        def add_column(self, *_args, **_kwargs) -> None:
            pass

        def add_row(self, *_args, **_kwargs) -> None:
            pass

    stub_modules["rich.table"].Table = _DummyTable

    prompt_module = stub_modules["graphrag_agent.config.prompts.graph_prompts"]
    prompt_module.system_template_build_graph = ""
    prompt_module.human_template_build_graph = ""
    prompt_module.system_template_build_graph_batch = ""
    prompt_module.human_template_build_graph_batch = ""

    settings_module = stub_modules["graphrag_agent.config.settings"]
    settings_module.entity_types = []
    settings_module.relationship_types = []
    settings_module.CHUNK_SIZE = 256
    settings_module.OVERLAP = 32
    settings_module.MAX_WORKERS = 1
    settings_module.BATCH_SIZE = 1
    settings_module.LLM_BATCH_SIZE = 1
    settings_module.FILE_REGISTRY_PATH = Path("file_registry.json")

    class _DummyDocumentProcessor:
        """最小文档处理器替身。"""

        def __init__(self, *_args, **_kwargs) -> None:
            pass

    stub_modules[
        "graphrag_agent.pipelines.ingestion.document_processor"
    ].DocumentProcessor = _DummyDocumentProcessor

    class _DummyEntityExtractor:
        """最小实体抽取器替身。"""

        def __init__(self, *_args, **_kwargs) -> None:
            pass

    class _DummyGraphWriter:
        """最小图写入器替身。"""

        def __init__(self, *_args, **_kwargs) -> None:
            pass

    class _DummyStructBuilder:
        """最小图结构构建器替身。"""

        def __init__(self, *_args, **_kwargs) -> None:
            pass

    graph_module = stub_modules["graphrag_agent.graph"]
    graph_module.EntityRelationExtractor = _DummyEntityExtractor
    graph_module.GraphWriter = _DummyGraphWriter
    graph_module.GraphStructureBuilder = _DummyStructBuilder

    stub_modules["graphrag_agent.config.neo4jdb"].get_db_manager = lambda: types.SimpleNamespace(
        graph=types.SimpleNamespace(query=lambda *_args, **_kwargs: [])
    )

    class _DummyFileChangeManager:
        """最小文件变更管理器替身。"""

        def __init__(self, *_args, **_kwargs) -> None:
            pass

    stub_modules[
        "graphrag_agent.integrations.build.incremental.file_change_manager"
    ].FileChangeManager = _DummyFileChangeManager

    class _DummyEmbeddingManager:
        """最小 Embedding 管理器替身。"""

        def __init__(self, *_args, **_kwargs) -> None:
            pass

    stub_modules[
        "graphrag_agent.graph.indexing.embedding_manager"
    ].EmbeddingManager = _DummyEmbeddingManager

    class _DummyChunkIndexBuilder:
        """最小 Chunk 索引构建器替身。"""

        def process(self) -> None:
            pass

    stub_modules[
        "graphrag_agent.integrations.build.build_chunk_index"
    ].ChunkIndexBuilder = _DummyChunkIndexBuilder

    original_modules = {name: sys.modules.get(name) for name in stub_modules}
    try:
        sys.modules.update(stub_modules)
        spec = importlib.util.spec_from_file_location(
            "test_incremental_graph_builder_module",
            module_path,
        )
        assert spec is not None
        assert spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        for name, original in original_modules.items():
            if original is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = original


class IncrementalBuildCommunityContractTest(unittest.TestCase):
    """验证增量构建完成后一定会刷新社区与全局索引。"""

    @classmethod
    def setUpClass(cls) -> None:
        """预加载待测模块。"""
        cls.module = _load_incremental_module()

    def _build_fake_updater(self):
        """构造只保留流程控制能力的 updater 替身。"""
        updater = self.module.IncrementalGraphUpdater.__new__(self.module.IncrementalGraphUpdater)
        updater.console = types.SimpleNamespace(print=lambda *_args, **_kwargs: None)
        updater.progress_callback = None
        updater.stats = {
            "start_time": None,
            "end_time": None,
            "total_time": 0,
            "files_processed": 0,
            "entities_integrated": 0,
            "relations_integrated": 0,
            "entities_updated": 0,
            "chunks_updated": 0,
        }
        updater._emit_progress = lambda *_args, **_kwargs: None
        return updater

    def test_process_incremental_update_refreshes_community_and_chunk_indexes(self) -> None:
        """目录差量更新后应重算社区并刷新 Chunk 索引。"""
        updater = self._build_fake_updater()
        call_order = []

        updater.detect_changes = lambda: {"added": [], "modified": ["a.md"], "deleted": []}
        updater.process_updated_files = lambda files: (
            call_order.append(("process_updated_files", tuple(files)))
            or {"entities_extracted": 2, "relations_created": 3}
        )
        updater.update_changed_file_embeddings = lambda files: (
            call_order.append(("update_changed_file_embeddings", tuple(files)))
            or {"entities": 1, "chunks": 1}
        )
        updater.rebuild_indexes_and_communities = lambda: call_order.append(
            "rebuild_indexes_and_communities"
        )
        updater.rebuild_chunk_index = lambda: call_order.append("rebuild_chunk_index")
        updater.display_graph_statistics = lambda: call_order.append("display_graph_statistics")
        updater.file_manager = types.SimpleNamespace(
            update_registry=lambda: call_order.append("update_registry")
        )

        result = self.module.IncrementalGraphUpdater.process_incremental_update(updater)

        self.assertEqual(
            call_order,
            [
                ("process_updated_files", ("a.md",)),
                ("update_changed_file_embeddings", ("a.md",)),
                "rebuild_indexes_and_communities",
                "rebuild_chunk_index",
                "update_registry",
                "display_graph_statistics",
            ],
        )
        self.assertEqual(result["entities_integrated"], 2)
        self.assertEqual(result["relations_integrated"], 3)

    def test_process_selected_files_refreshes_community_before_finish(self) -> None:
        """指定文件补建后也应执行同样的社区与索引刷新。"""
        updater = self._build_fake_updater()
        call_order = []

        updater._normalize_file_paths = lambda paths: paths
        updater.process_updated_files = lambda files: (
            call_order.append(("process_updated_files", tuple(files)))
            or {"files_processed": len(files), "entities_extracted": 1, "relations_created": 1}
        )
        updater.update_changed_file_embeddings = lambda files: call_order.append(
            ("update_changed_file_embeddings", tuple(files))
        )
        updater.rebuild_indexes_and_communities = lambda: call_order.append(
            "rebuild_indexes_and_communities"
        )
        updater.rebuild_chunk_index = lambda: call_order.append("rebuild_chunk_index")
        updater.display_graph_statistics = lambda: call_order.append("display_graph_statistics")
        updater.file_manager = types.SimpleNamespace(
            update_registry=lambda: call_order.append("update_registry")
        )

        result = self.module.IncrementalGraphUpdater.process_selected_files(
            updater,
            ["demo.pdf"],
        )

        self.assertEqual(
            call_order,
            [
                ("process_updated_files", ("demo.pdf",)),
                ("update_changed_file_embeddings", ("demo.pdf",)),
                "rebuild_indexes_and_communities",
                "rebuild_chunk_index",
                "update_registry",
                "display_graph_statistics",
            ],
        )
        self.assertEqual(result["files_processed"], 1)
        self.assertEqual(result["entities_integrated"], 1)
        self.assertEqual(result["relations_integrated"], 1)


if __name__ == "__main__":
    unittest.main()
