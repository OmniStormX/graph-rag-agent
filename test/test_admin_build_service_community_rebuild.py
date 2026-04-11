"""后台手动社区重构测试。"""

from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import tempfile
import types
import unittest


def _load_admin_build_service_module():
    """按文件路径加载后台构建服务，并注入最小依赖替身。"""
    module_path = (
        Path(__file__).resolve().parent.parent
        / "server"
        / "services"
        / "admin_build_service.py"
    )
    temp_root = Path(tempfile.mkdtemp(prefix="admin-build-service-test-"))

    metadata_state = {
        "version": {
            "version_id": "gv_active",
            "version_name": "当前激活版本",
            "is_active": True,
        },
        "active_version": {
            "version_id": "gv_active",
            "version_name": "当前激活版本",
            "is_active": True,
        },
        "updates": [],
    }

    metadata_module = types.ModuleType("services.admin_metadata_service")
    metadata_module.metadata_service = types.SimpleNamespace(
        available=True,
        get_graph_version=lambda version_id: metadata_state["version"]
        if version_id == metadata_state["version"]["version_id"]
        else None,
        get_active_graph_version=lambda: metadata_state["active_version"],
        update_graph_version=lambda version_id, **fields: metadata_state["updates"].append(
            {"version_id": version_id, **fields}
        ),
    )

    graph_version_module = types.ModuleType("services.graph_version_service")
    graph_version_module.graph_version_service = types.SimpleNamespace(
        export_current_graph=lambda _version_id: {
            "snapshot_path": str(temp_root / "snapshot.json"),
            "snapshot_data": '{"version_id": "gv_active"}',
            "entity_count": 12,
            "relation_count": 28,
        }
    )

    stub_modules = {
        "graphrag_agent": types.ModuleType("graphrag_agent"),
        "graphrag_agent.config": types.ModuleType("graphrag_agent.config"),
        "graphrag_agent.config.settings": types.ModuleType("graphrag_agent.config.settings"),
        "graphrag_agent.runtime_logging": types.ModuleType("graphrag_agent.runtime_logging"),
        "services": types.ModuleType("services"),
        "services.admin_metadata_service": metadata_module,
        "services.graph_version_service": graph_version_module,
    }
    stub_modules["graphrag_agent.config.settings"].FILES_DIR = temp_root / "files"
    stub_modules["graphrag_agent.config.settings"].GRAPH_ADMIN_BUILD_LOG_DIR = temp_root / "logs"
    stub_modules["graphrag_agent.config.settings"].GRAPH_ADMIN_UPLOAD_DIR = temp_root / "uploads"
    stub_modules["graphrag_agent.runtime_logging"].emit_runtime_log = lambda *_args, **_kwargs: None

    original_modules = {name: sys.modules.get(name) for name in stub_modules}
    try:
        sys.modules.update(stub_modules)
        spec = importlib.util.spec_from_file_location(
            "test_admin_build_service_module",
            module_path,
        )
        assert spec is not None
        assert spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module, metadata_state
    finally:
        for name, original in original_modules.items():
            if original is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = original


class AdminBuildServiceCommunityRebuildTest(unittest.TestCase):
    """验证后台手动社区重构入口。"""

    @classmethod
    def setUpClass(cls) -> None:
        """预加载待测模块。"""
        cls.module, cls.metadata_state = _load_admin_build_service_module()

    def test_rebuild_active_version_communities_refreshes_snapshot(self) -> None:
        """手动重构社区后应同步刷新当前版本快照。"""
        self.metadata_state["updates"].clear()
        service = self.module.AdminBuildService()
        rebuild_calls = []
        service._rebuild_live_graph_communities = lambda: rebuild_calls.append("rebuild")
        service._count_community_nodes = lambda: 6

        result = service.rebuild_active_version_communities("gv_active")

        self.assertEqual(rebuild_calls, ["rebuild"])
        self.assertEqual(result["community_count"], 6)
        self.assertEqual(result["node_count"], 12)
        self.assertEqual(result["relation_count"], 28)
        self.assertEqual(
            self.metadata_state["updates"],
            [
                {
                    "version_id": "gv_active",
                    "status": "active",
                    "snapshot_path": result["snapshot_path"],
                    "snapshot_data": '{"version_id": "gv_active"}',
                    "entity_count": 12,
                    "relation_count": 28,
                }
            ],
        )

    def test_rebuild_active_version_communities_rejects_inactive_version(self) -> None:
        """非激活版本不应允许直接手动重构社区。"""
        service = self.module.AdminBuildService()
        self.metadata_state["active_version"] = {
            "version_id": "gv_other",
            "version_name": "其他版本",
            "is_active": True,
        }

        with self.assertRaisesRegex(ValueError, "仅支持对当前激活版本手动重构社区"):
            service.rebuild_active_version_communities("gv_active")

        self.metadata_state["active_version"] = {
            "version_id": "gv_active",
            "version_name": "当前激活版本",
            "is_active": True,
        }


if __name__ == "__main__":
    unittest.main()
