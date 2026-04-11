"""图谱版本快照中的社区结构测试。"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest


def _make_package(name: str) -> types.ModuleType:
    """创建最小化包模块，避免导入真实服务依赖。"""
    module = types.ModuleType(name)
    module.__path__ = []
    return module


class _FakeQueryGraph:
    """用于导出快照的图查询替身。"""

    def query(self, statement: str):
        """根据查询语句返回预设节点或关系。"""
        if "MATCH (n)" in statement:
            return [
                {
                    "neo4j_id": "node-1",
                    "labels": ["__Entity__"],
                    "properties": {"id": "entity-1", "name": "泵站"},
                },
                {
                    "neo4j_id": "node-2",
                    "labels": ["__Community__"],
                    "properties": {"id": "community-1", "summary": "泵站与回路"},
                },
            ]
        return [
            {
                "source_id": "node-1",
                "target_id": "node-2",
                "rel_type": "IN_COMMUNITY",
                "properties": {"weight": 1.0},
            }
        ]


class _FakeResult:
    """Neo4j 查询结果替身。"""

    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def single(self) -> dict:
        """返回单条结果。"""
        return self._payload


class _FakeSession:
    """记录恢复阶段执行语句的 Session 替身。"""

    def __init__(self) -> None:
        self.commands = []
        self._created_nodes = 0

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def run(self, statement: str, **params):
        """记录语句，并为创建节点返回新的 elementId。"""
        self.commands.append((statement, params))
        if "RETURN elementId(n) AS node_id" in statement:
            self._created_nodes += 1
            return _FakeResult({"node_id": f"restored-{self._created_nodes}"})
        return _FakeResult({})


class _FakeDriver:
    """返回固定 Session 的 Driver 替身。"""

    def __init__(self, session: _FakeSession) -> None:
        self._session = session

    def session(self) -> _FakeSession:
        return self._session


class _FakeDbManager:
    """组合图查询与驱动接口的数据库管理器替身。"""

    def __init__(self) -> None:
        self.session = _FakeSession()
        self.graph = _FakeQueryGraph()

    def get_graph(self) -> _FakeQueryGraph:
        """返回图查询替身。"""
        return self.graph

    def get_driver(self) -> _FakeDriver:
        """返回驱动替身。"""
        return _FakeDriver(self.session)


def _load_graph_version_module(snapshot_dir: Path):
    """按文件路径加载图谱快照服务，并注入最小依赖。"""
    module_path = (
        Path(__file__).resolve().parent.parent
        / "server"
        / "services"
        / "graph_version_service.py"
    )
    fake_db_manager = _FakeDbManager()

    stub_modules = {
        "graphrag_agent": _make_package("graphrag_agent"),
        "graphrag_agent.config": _make_package("graphrag_agent.config"),
        "graphrag_agent.config.settings": types.ModuleType("graphrag_agent.config.settings"),
        "graphrag_agent.runtime_logging": types.ModuleType("graphrag_agent.runtime_logging"),
        "server_config": _make_package("server_config"),
        "server_config.database": types.ModuleType("server_config.database"),
    }
    stub_modules["graphrag_agent.config.settings"].GRAPH_ADMIN_SNAPSHOT_DIR = snapshot_dir
    stub_modules["graphrag_agent.runtime_logging"].emit_runtime_log = lambda *_args, **_kwargs: None
    stub_modules["server_config.database"].get_db_manager = lambda: fake_db_manager

    original_modules = {name: sys.modules.get(name) for name in stub_modules}
    try:
        sys.modules.update(stub_modules)
        spec = importlib.util.spec_from_file_location(
            "test_graph_version_service_module",
            module_path,
        )
        assert spec is not None
        assert spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module, fake_db_manager
    finally:
        for name, original in original_modules.items():
            if original is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = original


class GraphVersionCommunitySnapshotTest(unittest.TestCase):
    """验证社区节点与关系会进入快照并参与回滚恢复。"""

    def test_export_snapshot_keeps_community_nodes_and_relations(self) -> None:
        """导出当前图谱时不应丢失社区结构。"""
        with tempfile.TemporaryDirectory() as temp_dir:
            module, _db_manager = _load_graph_version_module(Path(temp_dir))
            service = module.GraphVersionService()

            snapshot_info = service.export_current_graph("version_demo")
            snapshot_data = json.loads(snapshot_info["snapshot_data"])

            self.assertEqual(snapshot_info["entity_count"], 2)
            self.assertEqual(snapshot_info["relation_count"], 1)
            self.assertEqual(snapshot_data["nodes"][1]["labels"], ["__Community__"])
            self.assertEqual(snapshot_data["relationships"][0]["type"], "IN_COMMUNITY")
            self.assertTrue(Path(snapshot_info["snapshot_path"]).exists())

    def test_restore_snapshot_recreates_community_structure(self) -> None:
        """回滚快照时应同步恢复社区节点与社区关系。"""
        with tempfile.TemporaryDirectory() as temp_dir:
            module, db_manager = _load_graph_version_module(Path(temp_dir))
            service = module.GraphVersionService()

            snapshot = {
                "version_id": "version_demo",
                "nodes": [
                    {
                        "neo4j_id": "node-1",
                        "labels": ["__Entity__"],
                        "properties": {"id": "entity-1", "name": "泵站"},
                    },
                    {
                        "neo4j_id": "node-2",
                        "labels": ["__Community__"],
                        "properties": {"id": "community-1", "summary": "泵站与回路"},
                    },
                ],
                "relationships": [
                    {
                        "source_id": "node-1",
                        "target_id": "node-2",
                        "type": "IN_COMMUNITY",
                        "properties": {"weight": 1.0},
                    }
                ],
            }

            result = service.restore_snapshot(
                snapshot_path=None,
                snapshot_data=json.dumps(snapshot, ensure_ascii=False),
            )

            executed_statements = [statement for statement, _params in db_manager.session.commands]
            self.assertEqual(result["node_count"], 2)
            self.assertEqual(result["relation_count"], 1)
            self.assertTrue(any("MATCH (n) DETACH DELETE n" in statement for statement in executed_statements))
            self.assertTrue(any("`__Community__`" in statement for statement in executed_statements))
            self.assertTrue(any("`IN_COMMUNITY`" in statement for statement in executed_statements))


if __name__ == "__main__":
    unittest.main()
