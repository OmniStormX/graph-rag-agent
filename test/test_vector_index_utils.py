"""向量索引解析测试。"""

from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest


def _load_vector_index_utils_module():
    """按文件路径加载向量索引工具模块。"""
    module_path = (
        Path(__file__).resolve().parent.parent
        / "graphrag_agent"
        / "search"
        / "vector_index_utils.py"
    )
    spec = importlib.util.spec_from_file_location(
        "test_vector_index_utils_module",
        module_path,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class VectorIndexUtilsTest(unittest.TestCase):
    """验证向量索引选择逻辑。"""

    @classmethod
    def setUpClass(cls) -> None:
        """预加载待测模块。"""
        cls.module = _load_vector_index_utils_module()

    def test_resolve_vector_index_name_prefers_exact_match(self) -> None:
        """优先返回配置中显式指定且在线的索引。"""
        rows = [
            {
                "name": "vector",
                "type": "VECTOR",
                "state": "ONLINE",
                "entityType": "NODE",
                "labelsOrTypes": ["__Entity__"],
                "properties": ["embedding"],
            },
            {
                "name": "chunk_embedding",
                "type": "VECTOR",
                "state": "ONLINE",
                "entityType": "NODE",
                "labelsOrTypes": ["__Chunk__"],
                "properties": ["embedding"],
            },
        ]
        result = self.module.resolve_vector_index_name(
            rows,
            preferred_name="vector",
        )
        self.assertEqual(result, "vector")

    def test_resolve_vector_index_name_falls_back_to_entity_index(self) -> None:
        """当默认索引不存在时，应回退到实体 embedding 索引。"""
        rows = [
            {
                "name": "entity_embedding",
                "type": "VECTOR",
                "state": "ONLINE",
                "entityType": "NODE",
                "labelsOrTypes": ["__Entity__"],
                "properties": ["embedding"],
            },
            {
                "name": "chunk_embedding",
                "type": "VECTOR",
                "state": "ONLINE",
                "entityType": "NODE",
                "labelsOrTypes": ["__Chunk__"],
                "properties": ["embedding"],
            },
        ]
        result = self.module.resolve_vector_index_name(
            rows,
            preferred_name="vector",
        )
        self.assertEqual(result, "entity_embedding")

    def test_resolve_vector_index_name_normalizes_preferred_name(self) -> None:
        """当配置值带引号或空白时，仍应匹配到正确索引。"""
        rows = [
            {
                "name": "vector",
                "type": "VECTOR",
                "state": "ONLINE",
                "entityType": "NODE",
                "labelsOrTypes": ["__Entity__"],
                "properties": ["embedding"],
            },
        ]
        result = self.module.resolve_vector_index_name(
            rows,
            preferred_name=" 'vector' ",
        )
        self.assertEqual(result, "vector")

    def test_build_missing_vector_index_message_reports_non_online_state(self) -> None:
        """当索引存在但未上线时，应明确返回索引状态。"""
        rows = [
            {
                "name": "vector",
                "type": "VECTOR",
                "state": "POPULATING",
                "entityType": "NODE",
                "labelsOrTypes": ["__Entity__"],
                "properties": ["embedding"],
                "failureMessage": "",
            },
        ]
        message = self.module.build_missing_vector_index_message(
            preferred_name="vector",
            rows=rows,
        )
        self.assertIn("状态为 `POPULATING`", message)
        self.assertIn("未达到 `ONLINE`", message)


if __name__ == "__main__":
    unittest.main()
