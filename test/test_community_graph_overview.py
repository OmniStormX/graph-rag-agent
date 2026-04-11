"""社区压缩图构建测试。"""

from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest


def _load_community_graph_module():
    """按文件路径加载社区压缩图构建模块。"""
    module_path = (
        Path(__file__).resolve().parent.parent
        / "frontend"
        / "utils"
        / "community_graph.py"
    )
    spec = importlib.util.spec_from_file_location(
        "test_community_graph_module",
        module_path,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class CommunityGraphOverviewTest(unittest.TestCase):
    """验证社区全局图谱会输出压缩后的社区超图。"""

    @classmethod
    def setUpClass(cls) -> None:
        """预加载待测模块。"""
        cls.module = _load_community_graph_module()

    def test_build_returns_only_community_nodes_and_aggregated_edges(self) -> None:
        """压缩图应只包含社区节点，不再直接混入实体节点。"""
        snapshot = {
            "nodes": [
                {
                    "neo4j_id": "e1",
                    "labels": ["__Entity__"],
                    "properties": {"id": "entity_1", "name": "泵站"},
                },
                {
                    "neo4j_id": "e2",
                    "labels": ["__Entity__"],
                    "properties": {"id": "entity_2", "name": "回路"},
                },
                {
                    "neo4j_id": "e3",
                    "labels": ["__Entity__"],
                    "properties": {"id": "entity_3", "name": "阀门"},
                },
                {
                    "neo4j_id": "c1",
                    "labels": ["__Community__"],
                    "properties": {"id": "0-1", "level": 0, "summary": "供水系统"},
                },
                {
                    "neo4j_id": "c2",
                    "labels": ["__Community__"],
                    "properties": {"id": "0-2", "level": 0, "summary": "控制系统"},
                },
            ],
            "relationships": [
                {"source_id": "e1", "target_id": "c1", "type": "IN_COMMUNITY", "properties": {}},
                {"source_id": "e2", "target_id": "c1", "type": "IN_COMMUNITY", "properties": {}},
                {"source_id": "e3", "target_id": "c2", "type": "IN_COMMUNITY", "properties": {}},
                {"source_id": "e1", "target_id": "e3", "type": "RELATED_TO", "properties": {"weight": 2}},
                {"source_id": "e2", "target_id": "e3", "type": "CAUSES", "properties": {}},
                {"source_id": "e1", "target_id": "e2", "type": "LOCATED_IN", "properties": {}},
            ],
        }

        result = self.module.build_community_overview_visualization(snapshot)

        self.assertFalse(result["directed"])
        self.assertEqual(result["meta"]["community_count"], 2)
        self.assertEqual(len(result["nodes"]), 2)
        self.assertEqual({node["id"] for node in result["nodes"]}, {"0-1", "0-2"})
        self.assertEqual(len(result["links"]), 1)
        self.assertEqual(result["links"][0]["label"], "2")
        self.assertIn("RELATED_TO", result["links"][0]["title"])
        self.assertIn("CAUSES", result["links"][0]["title"])

    def test_build_prefers_highest_nontrivial_community_level(self) -> None:
        """存在多层社区时，应优先展示仍有多个社区的最高层。"""
        snapshot = {
            "nodes": [
                {
                    "neo4j_id": "e1",
                    "labels": ["__Entity__"],
                    "properties": {"id": "entity_1", "name": "泵站"},
                },
                {
                    "neo4j_id": "e2",
                    "labels": ["__Entity__"],
                    "properties": {"id": "entity_2", "name": "回路"},
                },
                {
                    "neo4j_id": "e3",
                    "labels": ["__Entity__"],
                    "properties": {"id": "entity_3", "name": "阀门"},
                },
                {
                    "neo4j_id": "c1",
                    "labels": ["__Community__"],
                    "properties": {"id": "0-1", "level": 0, "summary": "底层社区 1"},
                },
                {
                    "neo4j_id": "c2",
                    "labels": ["__Community__"],
                    "properties": {"id": "0-2", "level": 0, "summary": "底层社区 2"},
                },
                {
                    "neo4j_id": "c3",
                    "labels": ["__Community__"],
                    "properties": {"id": "0-3", "level": 0, "summary": "底层社区 3"},
                },
                {
                    "neo4j_id": "p1",
                    "labels": ["__Community__"],
                    "properties": {"id": "1-10", "level": 1, "summary": "上层社区 A"},
                },
                {
                    "neo4j_id": "p2",
                    "labels": ["__Community__"],
                    "properties": {"id": "1-20", "level": 1, "summary": "上层社区 B"},
                },
            ],
            "relationships": [
                {"source_id": "e1", "target_id": "c1", "type": "IN_COMMUNITY", "properties": {}},
                {"source_id": "e2", "target_id": "c2", "type": "IN_COMMUNITY", "properties": {}},
                {"source_id": "e3", "target_id": "c3", "type": "IN_COMMUNITY", "properties": {}},
                {"source_id": "c1", "target_id": "p1", "type": "IN_COMMUNITY", "properties": {}},
                {"source_id": "c2", "target_id": "p1", "type": "IN_COMMUNITY", "properties": {}},
                {"source_id": "c3", "target_id": "p2", "type": "IN_COMMUNITY", "properties": {}},
                {"source_id": "e1", "target_id": "e3", "type": "RELATED_TO", "properties": {}},
                {"source_id": "e2", "target_id": "e3", "type": "CAUSES", "properties": {}},
            ],
        }

        result = self.module.build_community_overview_visualization(snapshot)

        self.assertEqual(result["meta"]["display_level"], 1)
        self.assertEqual({node["id"] for node in result["nodes"]}, {"1-10", "1-20"})
        self.assertEqual(len(result["links"]), 1)
        self.assertEqual(result["links"][0]["source"], "1-10")
        self.assertEqual(result["links"][0]["target"], "1-20")

    def test_drilldown_returns_child_community_graph(self) -> None:
        """下钻后应切换到所选社区的子社区层。"""
        snapshot = {
            "nodes": [
                {
                    "neo4j_id": "e1",
                    "labels": ["__Entity__"],
                    "properties": {"id": "entity_1", "name": "泵站"},
                },
                {
                    "neo4j_id": "e2",
                    "labels": ["__Entity__"],
                    "properties": {"id": "entity_2", "name": "回路"},
                },
                {
                    "neo4j_id": "e3",
                    "labels": ["__Entity__"],
                    "properties": {"id": "entity_3", "name": "阀门"},
                },
                {
                    "neo4j_id": "c1",
                    "labels": ["__Community__"],
                    "properties": {"id": "0-1", "level": 0, "topic": "底层社区 1"},
                },
                {
                    "neo4j_id": "c2",
                    "labels": ["__Community__"],
                    "properties": {"id": "0-2", "level": 0, "topic": "底层社区 2"},
                },
                {
                    "neo4j_id": "c3",
                    "labels": ["__Community__"],
                    "properties": {"id": "0-3", "level": 0, "topic": "底层社区 3"},
                },
                {
                    "neo4j_id": "p1",
                    "labels": ["__Community__"],
                    "properties": {"id": "1-10", "level": 1, "topic": "上层社区 A"},
                },
                {
                    "neo4j_id": "p2",
                    "labels": ["__Community__"],
                    "properties": {"id": "1-20", "level": 1, "topic": "上层社区 B"},
                },
            ],
            "relationships": [
                {"source_id": "e1", "target_id": "c1", "type": "IN_COMMUNITY", "properties": {}},
                {"source_id": "e2", "target_id": "c2", "type": "IN_COMMUNITY", "properties": {}},
                {"source_id": "e3", "target_id": "c3", "type": "IN_COMMUNITY", "properties": {}},
                {"source_id": "c1", "target_id": "p1", "type": "IN_COMMUNITY", "properties": {}},
                {"source_id": "c2", "target_id": "p1", "type": "IN_COMMUNITY", "properties": {}},
                {"source_id": "c3", "target_id": "p2", "type": "IN_COMMUNITY", "properties": {}},
                {"source_id": "e1", "target_id": "e2", "type": "RELATED_TO", "properties": {}},
            ],
        }

        result = self.module.build_community_drilldown_visualization(
            snapshot,
            community_path=["1-10"],
        )

        self.assertEqual(result["meta"]["path"], ["1-10"])
        self.assertEqual({node["id"] for node in result["nodes"]}, {"0-1", "0-2"})
        self.assertEqual(result["meta"]["community_count"], 2)


if __name__ == "__main__":
    unittest.main()
