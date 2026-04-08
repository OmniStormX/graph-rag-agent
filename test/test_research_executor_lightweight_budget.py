import sys
import unittest
from pathlib import Path
from typing import Any, Dict, List, Tuple
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
        PlanExecutionSignal,
        TaskNode,
    )
    from graphrag_agent.agents.multi_agent.core.state import PlanExecuteState  # noqa: E402
    from graphrag_agent.agents.multi_agent.executor.research_executor import (  # noqa: E402
        ResearchExecutor,
    )
    TEST_IMPORT_ERROR = None
except ModuleNotFoundError as exc:  # pragma: no cover
    PlanExecutionSignal = None  # type: ignore[assignment]
    PlanExecuteState = None  # type: ignore[assignment]
    ResearchExecutor = None  # type: ignore[assignment]
    TaskNode = None  # type: ignore[assignment]
    TEST_IMPORT_ERROR = exc


if TEST_IMPORT_ERROR is None:
    class _FakeDeepResearchTool:
        """用于验证轻量预算控制的研究工具桩。"""

        def __init__(self) -> None:
            self.max_iterations = 5
            self.seen_iterations: List[int] = []

        def search(self, _payload: Dict[str, Any]) -> Dict[str, Any]:
            self.seen_iterations.append(self.max_iterations)
            return {"answer": f"iterations={self.max_iterations}"}


    class _FakeDeeperResearchTool:
        """模拟带嵌套 deep_research 的增强研究工具。"""

        def __init__(self) -> None:
            self.deep_research = _FakeDeepResearchTool()
            self.seen_nested_iterations: List[int] = []

        def search(self, _payload: Dict[str, Any]) -> Dict[str, Any]:
            self.seen_nested_iterations.append(self.deep_research.max_iterations)
            return {"answer": f"nested={self.deep_research.max_iterations}"}


    class _TestResearchExecutor(ResearchExecutor):
        """注入假工具，避免依赖真实研究链路。"""

        def __init__(self, tool: Any) -> None:
            super().__init__()
            self._tool = tool

        def _get_tool_instance(self, task_type: str) -> Any:
            return self._tool

        def _wrap_research_output(
            self,
            state: PlanExecuteState,
            task: TaskNode,
            tool_name: str,
            result_payload: Any,
        ) -> Tuple[List[Any], str, List[str]]:
            return [], result_payload.get("answer", ""), []


class ResearchExecutorLightweightBudgetTest(unittest.TestCase):
    """验证 ResearchExecutor 会消费 lightweight hint，但不改变任务语义。"""

    def setUp(self) -> None:
        if TEST_IMPORT_ERROR is not None:
            self.skipTest(f"缺少测试依赖: {TEST_IMPORT_ERROR}")

    def _make_signal(self, task: TaskNode) -> PlanExecutionSignal:
        return PlanExecutionSignal(
            plan_id="plan-1",
            version=1,
            execution_mode="sequential",
            tasks=[task.model_dump(mode="json")],
            execution_sequence=[task.task_id],
            assumptions=[],
            acceptance_criteria={},
        )

    def test_lightweight_preference_caps_iterations_for_deep_research(self) -> None:
        tool = _FakeDeepResearchTool()
        executor = _TestResearchExecutor(tool)
        task = TaskNode(
            task_id="task_research",
            task_type="deep_research",
            description="执行深度研究",
            parameters={
                "query": "什么是 GraphRAG",
                "lightweight_preference": True,
            },
        )
        state = PlanExecuteState(input="什么是 GraphRAG")

        result = executor.execute_task(task, state, self._make_signal(task))

        self.assertTrue(result.success)
        self.assertEqual(tool.seen_iterations, [ResearchExecutor.LIGHTWEIGHT_MAX_ITERATIONS])
        self.assertEqual(tool.max_iterations, 5)
        self.assertTrue(result.record.metadata.environment["lightweight_preference"])
        self.assertEqual(result.record.tool_calls[0].tool_name, "deep_research")

    def test_lightweight_preference_caps_nested_iterations_for_deeper_research(self) -> None:
        tool = _FakeDeeperResearchTool()
        executor = _TestResearchExecutor(tool)
        task = TaskNode(
            task_id="task_deeper_research",
            task_type="deeper_research",
            description="执行增强深度研究",
            parameters={
                "query": "什么是 GraphRAG",
                "lightweight_preference": True,
            },
        )
        state = PlanExecuteState(input="什么是 GraphRAG")

        result = executor.execute_task(task, state, self._make_signal(task))

        self.assertTrue(result.success)
        self.assertEqual(
            tool.seen_nested_iterations,
            [ResearchExecutor.LIGHTWEIGHT_MAX_ITERATIONS],
        )
        self.assertEqual(tool.deep_research.max_iterations, 5)
        self.assertEqual(result.record.tool_calls[0].tool_name, "deeper_research")


if __name__ == "__main__":
    unittest.main()
