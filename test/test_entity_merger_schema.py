import unittest
from pathlib import Path


class EntityMergerSchemaTest(unittest.TestCase):
    """验证实体合并器不会创建阻塞图写入的普通索引。"""

    def test_create_indexes_uses_unique_constraint(self):
        """应删除旧普通索引，并创建与 GraphDocument 写入兼容的唯一约束。"""
        source_path = (
            Path(__file__).resolve().parent.parent
            / "graphrag_agent"
            / "graph"
            / "processing"
            / "entity_merger.py"
        )
        source = source_path.read_text(encoding="utf-8")

        self.assertIn('drop_index("entity_id")', source)
        self.assertIn("CREATE CONSTRAINT entity_id_unique IF NOT EXISTS", source)
        self.assertIn("REQUIRE e.id IS UNIQUE", source)
        self.assertNotIn(
            "CREATE INDEX IF NOT EXISTS FOR (e:`__Entity__`) ON (e.id)",
            source,
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
