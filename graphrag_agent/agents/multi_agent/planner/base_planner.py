"""
Planner编排基类

整合Clarifier、TaskDecomposer、PlanReviewer，输出结构化的PlanSpec
"""
from typing import Optional, List, Set
from datetime import datetime
import logging
import re
import uuid

from pydantic import BaseModel, Field
from langchain_core.language_models.chat_models import BaseChatModel

from graphrag_agent.agents.multi_agent.core.state import (
    PlanExecuteState,
    PlanContext,
)
from graphrag_agent.agents.multi_agent.core.plan_spec import (
    PlanSpec,
    PlanExecutionSignal,
    TaskNode,
)
from graphrag_agent.agents.multi_agent.planner.clarifier import (
    Clarifier,
    ClarificationResult,
)
from graphrag_agent.agents.multi_agent.planner.task_decomposer import (
    TaskDecomposer,
    TaskDecompositionResult,
)
from graphrag_agent.agents.multi_agent.planner.plan_reviewer import (
    PlanReviewer,
    PlanReviewOutcome,
)
from graphrag_agent.models.get_models import get_llm_model
from graphrag_agent.config.settings import (
    MULTI_AGENT_PLANNER_MAX_TASKS,
    MULTI_AGENT_ALLOW_UNCLARIFIED_PLAN,
    MULTI_AGENT_DEFAULT_DOMAIN,
    MULTI_AGENT_REFLECTION_ALLOW_RETRY,
)

_LOGGER = logging.getLogger(__name__)


class PlannerConfig(BaseModel):
    """
    Planner配置
    """
    max_tasks: int = Field(default=6, description="单次任务分解允许的最大任务数")
    allow_unclarified_plan: bool = Field(
        default=True,
        description="若存在未解决的澄清问题，是否强制继续生成计划",
    )
    default_domain: str = Field(default="通用", description="默认领域背景，用于澄清提示")


class PlannerResult(BaseModel):
    """
    Planner综合输出
    """
    plan_spec: Optional[PlanSpec] = Field(default=None, description="最终生成的PlanSpec")
    clarification: ClarificationResult = Field(description="澄清结果")
    task_decomposition: Optional[TaskDecompositionResult] = Field(
        default=None,
        description="任务分解详细结果",
    )
    review_outcome: Optional[PlanReviewOutcome] = Field(
        default=None,
        description="计划审校产出详情",
    )
    executor_signal: Optional[PlanExecutionSignal] = Field(
        default=None,
        description="传递给Executor的计划信号"
    )

    def needs_clarification(self) -> bool:
        """是否仍需澄清"""
        if not self.clarification.needs_clarification:
            return False
        if not self.clarification.questions:
            return False
        # 未生成PlanSpec时视为待澄清
        return self.plan_spec is None

    def executor_signal_json(self) -> Optional[str]:
        """
        将执行信号转换为JSON字符串，便于跨组件传递
        """
        if self.executor_signal is None:
            return None
        # Pydantic v1/v2 兼容性处理
        import json
        return json.dumps(self.executor_signal.model_dump(mode="json"), ensure_ascii=False, indent=2)


class BasePlanner:
    """
    Planner基类

    提供生成PlanSpec的标准流程：澄清 → 任务分解 → 计划审校
    """

    def __init__(
        self,
        *,
        llm: Optional[BaseChatModel] = None,
        config: Optional[PlannerConfig] = None,
        clarifier: Optional[Clarifier] = None,
        task_decomposer: Optional[TaskDecomposer] = None,
        plan_reviewer: Optional[PlanReviewer] = None,
    ) -> None:
        if config is None:
            config = PlannerConfig(
                max_tasks=MULTI_AGENT_PLANNER_MAX_TASKS,
                allow_unclarified_plan=MULTI_AGENT_ALLOW_UNCLARIFIED_PLAN,
                default_domain=MULTI_AGENT_DEFAULT_DOMAIN,
            )
        self.config = config
        self._llm = llm or get_llm_model()

        # 所有子组件共享同一个LLM实例，便于缓存与限流
        self._clarifier = clarifier or Clarifier(self._llm, default_domain=self.config.default_domain)
        self._task_decomposer = task_decomposer or TaskDecomposer(self._llm, max_tasks=self.config.max_tasks)
        self._plan_reviewer = plan_reviewer or PlanReviewer(self._llm)

    def generate_plan(
        self,
        state: PlanExecuteState,
        *,
        assumptions: Optional[List[str]] = None,
    ) -> PlannerResult:
        """
        核心入口：生成任务执行计划

        参数:
            state: 当前会话的PlanExecuteState
            assumptions: 用户确认的前提条件

        返回:
            PlannerResult
        """
        # 确保PlanContext存在
        context = self._ensure_plan_context(state)

        # Step 1: 澄清分析
        clarification = self._clarifier.analyze(context)
        _LOGGER.info("Clarification result: %s", clarification.model_dump())
        self._record_clarification(context, clarification)

        if not clarification.is_satisfied(context) and not self.config.allow_unclarified_plan:
            _LOGGER.info("澄清问题尚未全部回答，暂停计划生成")
            return PlannerResult(
                plan_spec=None,
                clarification=clarification,
                task_decomposition=None,
                review_outcome=None,
            )

        # Step 2: 任务分解
        refined_query = context.refined_query or context.original_query
        task_decomposition = self._task_decomposer.decompose(refined_query)

        # Step 3: 计划审校
        review_outcome = self._plan_reviewer.review(
            original_query=context.original_query,
            refined_query=refined_query,
            task_graph=task_decomposition.task_graph,
            assumptions=assumptions or [],
            background_info=context.domain_context,
            user_intent=context.user_preferences.get("intent"),
        )

        plan_spec = review_outcome.plan_spec
        self._mark_lightweight_preferences(context.original_query, plan_spec)
        self._ensure_reflection_task(plan_spec)
        # 将生成的计划写回状态
        state.plan = plan_spec
        state.plan_context = context
        state.update_timestamp()

        executor_signal = plan_spec.to_execution_signal()

        return PlannerResult(
            plan_spec=plan_spec,
            clarification=clarification,
            task_decomposition=task_decomposition,
            review_outcome=review_outcome,
            executor_signal=executor_signal,
        )

    def _ensure_reflection_task(self, plan_spec: Optional[PlanSpec]) -> None:
        """
        若配置允许反思且当前计划未包含反思节点，则自动附加一个反思任务。
        """
        if not MULTI_AGENT_REFLECTION_ALLOW_RETRY:
            return
        if plan_spec is None or plan_spec.task_graph is None:
            return

        task_graph = plan_spec.task_graph
        if any(node.task_type == "reflection" for node in task_graph.nodes):
            return

        sink_ids: Set[str] = {node.task_id for node in task_graph.nodes}
        for node in task_graph.nodes:
            for dep in node.depends_on:
                sink_ids.discard(dep)

        depends_on = [task_id for task_id in sink_ids if task_id]
        if not depends_on and task_graph.nodes:
            depends_on = [task_graph.nodes[-1].task_id]

        reflection_node = TaskNode(
            task_id=f"task_reflection_{uuid.uuid4().hex[:6]}",
            task_type="reflection",
            description="复核整体答案并提出改进建议",
            priority=3,
            depends_on=depends_on,
        )

        task_graph.nodes.append(reflection_node)
        try:
            task_graph.validate_dependencies()
        except ValueError as exc:  # noqa: BLE001
            task_graph.nodes.pop()
            _LOGGER.warning("反思节点插入失败，保持原计划: %s", exc)

    def _mark_lightweight_preferences(
        self,
        query: str,
        plan_spec: Optional[PlanSpec],
    ) -> None:
        """
        为简单解释型问题标记轻量执行偏好，但不改写任务类型。

        说明：
            Planner/Reviewer 已经完成“做什么任务”的决策，这里不应直接将
            ``deep_research`` 改写为 ``global_search``。否则会绕过研究执行器，
            导致原本需要深度研究的问题退化成浅层检索。

            因此这里只写入轻量化提示，供后续执行层或工具层按需消费。
        """
        if plan_spec is None or plan_spec.task_graph is None:
            return
        if not self._should_constrain_deep_research(query, plan_spec):
            return

        for node in plan_spec.task_graph.nodes:
            if node.task_type not in {"deep_research", "deeper_research", "chain_exploration"}:
                continue

            # 仅记录轻量偏好，避免覆盖 Planner 对任务语义的判断。
            node.parameters["lightweight_preference"] = True
            node.parameters["lightweight_reason"] = "simple_explainer_query"

            # 仅温和压低预算，保留原始任务类型和执行器路由。
            if node.task_type in {"deep_research", "deeper_research"}:
                node.estimated_tokens = min(node.estimated_tokens, 600)
            elif node.task_type == "chain_exploration":
                node.estimated_tokens = min(node.estimated_tokens, 400)

            _LOGGER.info(
                "为任务标记轻量执行偏好: task_id=%s task_type=%s",
                node.task_id,
                node.task_type,
            )

    def _should_constrain_deep_research(
        self,
        query: str,
        plan_spec: PlanSpec,
    ) -> bool:
        """
        判断是否应当压低 deep_research 的触发门槛。
        """
        normalized_query = (query or "").strip().lower()
        if not normalized_query:
            return False

        has_deep_research = any(
            node.task_type in {"deep_research", "deeper_research"}
            for node in plan_spec.task_graph.nodes
        )
        if not has_deep_research:
            return False

        # 显式研究型意图保留深度研究能力。
        research_patterns = [
            r"深入",
            r"详细",
            r"系统",
            r"综述",
            r"调研",
            r"研究现状",
            r"发展趋势",
            r"多角度",
            r"案例分析",
            r"完整报告",
            r"comprehensive",
            r"survey",
            r"in-depth",
        ]
        if any(re.search(pattern, normalized_query) for pattern in research_patterns):
            return False

        # 定义解释型问答默认走轻路径。
        explainer_patterns = [
            r"什么是",
            r"为什么",
            r"如何",
            r"区别",
            r"定义",
            r"意义",
            r"作用",
            r"原理",
            r"特点",
            r"适用",
            r"what is",
            r"why",
            r"how",
        ]
        looks_like_explainer = any(
            re.search(pattern, normalized_query) for pattern in explainer_patterns
        )
        if not looks_like_explainer:
            return False

        lightweight_task_count = sum(
            1
            for node in plan_spec.task_graph.nodes
            if node.task_type in {"local_search", "global_search", "hybrid_search", "naive_search"}
        )
        return lightweight_task_count >= 1

    def _ensure_plan_context(self, state: PlanExecuteState) -> PlanContext:
        """
        确保PlanContext存在并回填基础字段
        """
        if state.plan_context is None:
            state.plan_context = PlanContext(original_query=state.input or "")

        context = state.plan_context
        if not context.original_query:
            context.original_query = state.input
        if not context.refined_query:
            # 若尚未有澄清后的查询，则默认等同于原始查询
            context.refined_query = context.original_query
        return context

    def _record_clarification(self, context: PlanContext, clarification: ClarificationResult) -> None:
        """
        将澄清问题写入上下文，便于后续记录与测试观察。
        """
        if not clarification.questions:
            return
        existing = {entry.get("question") for entry in context.clarification_history}
        timestamp = datetime.now().isoformat()
        for question in clarification.questions:
            if question in existing:
                continue
            context.clarification_history.append(
                {
                    "question": question,
                    "answer": None,
                    "asked_at": timestamp,
                }
            )
        if clarification.ambiguity_types:
            context.user_preferences.setdefault("ambiguity_types", clarification.ambiguity_types)
