import sys
import unittest
from pathlib import Path
from types import ModuleType


PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

if "PyPDF2" not in sys.modules:
    fake_pypdf2 = ModuleType("PyPDF2")

    class _FakePdfReader:
        def __init__(self, *_args, **_kwargs) -> None:
            self.pages = []

    fake_pypdf2.PdfReader = _FakePdfReader
    sys.modules["PyPDF2"] = fake_pypdf2

if "docx" not in sys.modules:
    fake_docx = ModuleType("docx")

    class _FakeDocument:
        def __init__(self, *_args, **_kwargs) -> None:
            self.paragraphs = []

    fake_docx.Document = _FakeDocument
    sys.modules["docx"] = fake_docx

try:
    from graphrag_agent.agents.multi_agent.core.plan_spec import (  # noqa: E402
        PlanSpec,
        ProblemStatement,
        TaskGraph,
        TaskNode,
    )
    from graphrag_agent.agents.multi_agent.planner.base_planner import BasePlanner  # noqa: E402
    TEST_IMPORT_ERROR = None
except ModuleNotFoundError as exc:  # pragma: no cover
    BasePlanner = None  # type: ignore[assignment]
    PlanSpec = None  # type: ignore[assignment]
    ProblemStatement = None  # type: ignore[assignment]
    TaskGraph = None  # type: ignore[assignment]
    TaskNode = None  # type: ignore[assignment]
    TEST_IMPORT_ERROR = exc


class PlannerLightweightHintTest(unittest.TestCase):
    """验证 Planner 仅标记轻量偏好，不改写研究任务类型。"""

    def setUp(self) -> None:
        if TEST_IMPORT_ERROR is not None:
            self.skipTest(f"缺少测试依赖: {TEST_IMPORT_ERROR}")

    def _make_plan(self) -> PlanSpec:
        return PlanSpec(
            problem_statement=ProblemStatement(original_query="什么是 GraphRAG"),
            task_graph=TaskGraph(
                nodes=[
                    TaskNode(
                        task_id="task_local",
                        task_type="local_search",
                        description="先做本地检索",
                    ),
                    TaskNode(
                        task_id="task_research",
                        task_type="deep_research",
                        description="再做深度研究",
                        estimated_tokens=1200,
                    ),
                    TaskNode(
                        task_id="task_chain",
                        task_type="chain_exploration",
                        description="最后做链式探索",
                        estimated_tokens=900,
                    ),
                ],
                execution_mode="sequential",
            ),
        )

    def test_mark_lightweight_preferences_keeps_task_types(self) -> None:
        planner = BasePlanner.__new__(BasePlanner)
        plan_spec = self._make_plan()

        planner._mark_lightweight_preferences("什么是 GraphRAG", plan_spec)

        research_node = plan_spec.task_graph.nodes[1]
        chain_node = plan_spec.task_graph.nodes[2]

        self.assertEqual(research_node.task_type, "deep_research")
        self.assertEqual(chain_node.task_type, "chain_exploration")
        self.assertTrue(research_node.parameters["lightweight_preference"])
        self.assertEqual(
            research_node.parameters["lightweight_reason"],
            "simple_explainer_query",
        )
        self.assertEqual(research_node.estimated_tokens, 600)
        self.assertEqual(chain_node.estimated_tokens, 400)

    def test_explicit_research_query_is_not_marked_lightweight(self) -> None:
        planner = BasePlanner.__new__(BasePlanner)
        plan_spec = self._make_plan()

        planner._mark_lightweight_preferences(
            "请系统分析 GraphRAG 在生产环境中的评估方法",
            plan_spec,
        )

        research_node = plan_spec.task_graph.nodes[1]
        self.assertNotIn("lightweight_preference", research_node.parameters)
        self.assertEqual(research_node.estimated_tokens, 1200)


if __name__ == "__main__":
    unittest.main()
