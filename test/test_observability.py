"""可观测性适配层测试。"""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import unittest


class ObservabilityTracingTest(unittest.TestCase):
    """验证追踪适配层在未启用时不会影响业务逻辑。"""

    def test_observe_is_noop_when_langfuse_disabled(self) -> None:
        """未启用 Langfuse 时，装饰器应保持函数行为不变。"""
        previous_enabled = os.environ.get("LANGFUSE_ENABLED")
        try:
            os.environ["LANGFUSE_ENABLED"] = "false"
            module_path = (
                Path(__file__).resolve().parent.parent
                / "graphrag_agent"
                / "observability"
                / "tracing.py"
            )
            spec = importlib.util.spec_from_file_location(
                "test_observability_tracing",
                module_path,
            )
            self.assertIsNotNone(spec)
            self.assertIsNotNone(spec.loader)
            tracing = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(tracing)

            @tracing.observe(name="unit-test.observe")
            def add(left: int, right: int) -> int:
                return left + right

            self.assertEqual(add(2, 3), 5)
        finally:
            if previous_enabled is None:
                os.environ.pop("LANGFUSE_ENABLED", None)
            else:
                os.environ["LANGFUSE_ENABLED"] = previous_enabled


if __name__ == "__main__":
    unittest.main()
