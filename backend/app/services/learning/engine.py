import logging
import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.goal import GoalPriority
from app.db.models.memory import Memory, MemoryStatus
from app.db.models.task import Task, TaskStatus
from app.schemas.memory import MemoryCreate
from app.services.context_engine.models import ContextItem, ContextSource
from app.services.learning.evaluator import OutcomeEvaluator
from app.services.learning.models import (
    ExecutionOutcome,
    LearningImpact,
    LearningPlanningResult,
    LearningType,
    OutcomeEvaluation,
)
from app.services.memory import MemoryService

logger = logging.getLogger("lifethread.services.learning.engine")
audit_logger = logging.getLogger("lifethread.audit.learning")


class AgentLearningLoopEngine:
    """Agent Learning Loop Engine (Module 22).

    Connects execution results, evaluations, and memory so future decisions
    autonomously use previous outcomes.
    Pipeline: Action -> Result -> Evaluation -> Memory -> Future Decision
    """

    @classmethod
    async def record_and_learn(
        cls,
        db: AsyncSession,
        outcome: ExecutionOutcome,
    ) -> tuple[OutcomeEvaluation, Memory | None]:
        """Execute the learning loop: Evaluate outcome, extract learnings, and update/persist memory."""
        # 1. Evaluate Outcome against benchmarks (Requirements 1, 3, 8)
        eval_result = OutcomeEvaluator.evaluate(outcome)
        logger.info(
            "Evaluated outcome %s for user %s: type=%s finding='%s' conf=%.2f imp=%.2f is_factual=%s",
            outcome.outcome_id,
            outcome.user_id,
            eval_result.evaluation_type.value,
            eval_result.observed_finding,
            eval_result.confidence,
            eval_result.importance_score,
            eval_result.is_factual,
        )

        # 2. Check if outcome is meaningful for long-term memory retention (Requirements 1 & 2)
        if not eval_result.is_meaningful or eval_result.importance_score < 0.50:
            logger.info(
                "Outcome %s not converted to long-term memory (importance < 0.50)",
                outcome.outcome_id,
            )
            return eval_result, None

        # 3. Retrieve existing active memories for this user to check for duplicates and outdated memories
        domain = outcome.domain or OutcomeEvaluator._infer_domain_from_title(outcome.task_title)
        topic = outcome.topic or OutcomeEvaluator._infer_topic_from_text(
            f"{outcome.task_title} {outcome.notes or ''} {outcome.error_message or ''}"
        )

        existing_memories = await cls._find_related_active_memories(
            db=db,
            user_id=outcome.user_id,
            domain=domain,
            topic=topic,
        )

        now = datetime.now(UTC)

        # 4. Check for Outdated Memories (Requirement 5: Update outdated memories)
        for existing in existing_memories:
            existing_type = existing.metadata_json.get("learning_type")
            # If previous memory was a WEAKNESS and new evaluation demonstrates STRENGTH:
            if (
                existing_type == LearningType.WEAKNESS.value
                and eval_result.evaluation_type == LearningType.STRENGTH
            ):
                logger.info(
                    "Superseding outdated weakness memory %s for user %s following proven mastery",
                    existing.id,
                    outcome.user_id,
                )
                existing.status = MemoryStatus.SUPERSEDED
                updated_meta = dict(existing.metadata_json or {})
                updated_meta["superseded_at"] = now.isoformat()
                updated_meta["superseded_by_outcome_id"] = outcome.outcome_id
                existing.metadata_json = updated_meta
                await db.flush()

                audit_logger.info(
                    "AUDIT [MEMORY_SUPERSEDED_OUTDATED] user_id=%s old_memory_id=%s reason=SKILL_MASTERY",
                    outcome.user_id,
                    existing.id,
                )

        # 5. Check for Duplicate / Reinforcement (Requirement 4: Avoid duplicate memories)
        matching_duplicate: Memory | None = None
        for existing in existing_memories:
            if existing.status != MemoryStatus.ACTIVE:
                continue
            existing_type = existing.metadata_json.get("learning_type")
            if existing_type == eval_result.evaluation_type.value:
                matching_duplicate = existing
                break

        if matching_duplicate is not None:
            # Reinforce existing memory instead of creating redundant row
            matching_duplicate.access_count += 1
            matching_duplicate.last_accessed_at = now
            matching_duplicate.importance_score = min(
                1.0, max(matching_duplicate.importance_score, eval_result.importance_score)
            )

            # Bayesian/evidence confidence update
            new_conf = round(
                min(0.99, max(matching_duplicate.confidence, eval_result.confidence) + 0.05), 2
            )
            matching_duplicate.confidence = new_conf

            # If evidence now crosses factual certainty threshold, promote from hypothesis to fact
            meta = dict(matching_duplicate.metadata_json or {})
            if new_conf >= 0.70 and meta.get("is_hypothesis", False):
                meta["is_factual"] = True
                meta["is_hypothesis"] = False
                meta["epistemic_qualifier"] = "Verified observation"
                # Update text to assertive form
                concept = (
                    f"{domain} {topic}".strip()
                    if (domain and topic)
                    else (topic or domain or "this topic")
                )
                matching_duplicate.content = (
                    f"User struggles with {concept}"
                    if eval_result.evaluation_type == LearningType.WEAKNESS
                    else f"User has demonstrated proficiency in {concept}"
                )

            meta["last_reinforced_at"] = now.isoformat()
            meta["reinforcement_count"] = int(meta.get("reinforcement_count", 1)) + 1
            meta["latest_outcome_id"] = outcome.outcome_id
            matching_duplicate.metadata_json = meta

            await db.flush()
            await db.refresh(matching_duplicate)

            audit_logger.info(
                "AUDIT [LEARNING_MEMORY_REINFORCED] user_id=%s memory_id=%s confidence=%.2f access_count=%d",
                outcome.user_id,
                matching_duplicate.id,
                matching_duplicate.confidence,
                matching_duplicate.access_count,
            )
            return eval_result, matching_duplicate

        # 6. Store New Learning Memory (Requirements 2, 3, 6, 8)
        meta_payload = {
            "source_action": outcome.action_type,
            "goal_id": str(outcome.goal_id) if outcome.goal_id else None,
            "task_id": str(outcome.task_id) if outcome.task_id else None,
            "task_title": outcome.task_title,
            "domain": domain,
            "topic": topic,
            "outcome_id": outcome.outcome_id,
            "learning_type": eval_result.evaluation_type.value,
            "severity_or_strength": eval_result.severity_or_strength,
            "is_hypothesis": eval_result.is_hypothesis,
            "is_factual": eval_result.is_factual,
            "epistemic_qualifier": eval_result.epistemic_qualifier,
            "recommended_action": eval_result.recommended_planner_action,
            "recorded_at": now.isoformat(),
        }

        create_data = MemoryCreate(
            content=eval_result.suggested_memory_content,
            memory_type=eval_result.target_memory_type,
            importance_score=eval_result.importance_score,
            confidence=eval_result.confidence,
            source="agent_learning_loop",
            metadata=meta_payload,
            deduplicate=True,
        )

        stored_memory = await MemoryService.store_memory(
            db=db,
            user_id=outcome.user_id,
            create_data=create_data,
        )

        audit_logger.info(
            "AUDIT [LEARNING_MEMORY_CREATED] user_id=%s memory_id=%s type=%s finding='%s' conf=%.2f",
            outcome.user_id,
            stored_memory.id,
            eval_result.evaluation_type.value,
            eval_result.observed_finding,
            eval_result.confidence,
        )

        return eval_result, stored_memory

    @classmethod
    async def get_learning_memories(
        cls,
        db: AsyncSession,
        user_id: uuid.UUID,
        goal_id: uuid.UUID | None = None,
        task_id: uuid.UUID | None = None,
        domain: str | None = None,
        topic: str | None = None,
        min_confidence: float = 0.0,
    ) -> list[Memory]:
        """Retrieve active learning memories linked to specified context (Requirement 6)."""
        if goal_id:
            from app.services.goal import GoalService
            await GoalService.get_goal_by_id(db=db, goal_id=goal_id, user_id=user_id)

        stmt = (
            select(Memory)
            .where(
                Memory.user_id == user_id,
                Memory.status == MemoryStatus.ACTIVE,
                Memory.source == "agent_learning_loop",
                Memory.confidence >= min_confidence,
            )
            .order_by(Memory.importance_score.desc(), Memory.confidence.desc())
        )
        res = await db.execute(stmt)
        candidates = list(res.scalars().all())

        filtered: list[Memory] = []
        for mem in candidates:
            meta = mem.metadata_json or {}
            if goal_id and meta.get("goal_id") != str(goal_id):
                continue
            if task_id and meta.get("task_id") != str(task_id):
                continue
            if domain and meta.get("domain") and meta.get("domain").lower() != domain.lower():
                continue
            if topic and meta.get("topic") and meta.get("topic").lower() != topic.lower():
                continue
            filtered.append(mem)

        return filtered

    @classmethod
    async def build_learning_context_items(
        cls,
        db: AsyncSession,
        user_id: uuid.UUID,
        query: str | None = None,
        goal_id: uuid.UUID | None = None,
        task_id: uuid.UUID | None = None,
    ) -> list[ContextItem]:
        """Convert retrieved learning memories into structured ContextItems for Context Engine (Requirement 7)."""
        memories = await cls.get_learning_memories(
            db=db,
            user_id=user_id,
            goal_id=goal_id,
            task_id=task_id,
        )

        context_items: list[ContextItem] = []
        for mem in memories:
            meta = mem.metadata_json or {}
            # Base relevance on importance, confidence, and recency
            relevance = round(mem.importance_score * 0.6 + mem.confidence * 0.4, 2)
            if query and query.lower() in mem.content.lower():
                relevance = min(1.0, relevance + 0.20)

            c_item = ContextItem(
                id=str(mem.id),
                user_id=mem.user_id,
                source=ContextSource.MEMORIES,
                source_attribution=f"Memory: Learning Loop ({mem.memory_type.value})",
                content=mem.content,
                relevance_score=relevance,
                timestamp=mem.created_at,
                metadata={
                    "memory_id": str(mem.id),
                    "memory_type": mem.memory_type.value,
                    "confidence": mem.confidence,
                    "importance": mem.importance_score,
                    "is_factual": meta.get("is_factual", False),
                    "is_hypothesis": meta.get("is_hypothesis", True),
                    "epistemic_qualifier": meta.get(
                        "epistemic_qualifier", "Provisional hypothesis"
                    ),
                    "domain": meta.get("domain"),
                    "topic": meta.get("topic"),
                    "recommended_action": meta.get("recommended_action"),
                },
            )
            context_items.append(c_item)

        return context_items

    @classmethod
    async def apply_learnings_to_planner(
        cls,
        db: AsyncSession,
        user_id: uuid.UUID,
        goal_id: uuid.UUID,
        tasks: list[Task] | None = None,
        commit: bool = True,
    ) -> LearningPlanningResult:
        """Future Planner Integration:

        Inspects persisted learning memories and adapts the plan or tasks accordingly.
        Example:
        Weakness in SQL joins -> Increase SQL joins practice duration and priority.
        """
        # 1. Fetch Goal and enforce strict ownership
        from app.services.goal import GoalService
        goal = await GoalService.get_goal_by_id(db=db, goal_id=goal_id, user_id=user_id)

        # 2. Fetch active tasks if not provided
        if tasks is None:
            tasks_q = select(Task).where(Task.goal_id == goal_id).order_by(Task.created_at.asc())
            tasks_res = await db.execute(tasks_q)
            tasks = list(tasks_res.scalars().all())

        # 3. Retrieve relevant learning memories for this user
        memories = await cls.get_learning_memories(db=db, user_id=user_id)

        memories_applied: list[LearningImpact] = []
        tasks_modified_count = 0
        tasks_injected_count = 0
        summary_lines: list[str] = []

        if not memories:
            return LearningPlanningResult(
                goal_id=goal_id,
                user_id=user_id,
                relevant_memories_count=0,
                memories_applied=[],
                tasks_modified_count=0,
                tasks_injected_count=0,
                summary_rationale="No past learning memories found; standard baseline plan generated.",
            )

        for mem in memories:
            meta = mem.metadata_json or {}
            m_domain = meta.get("domain") or ""
            m_topic = meta.get("topic") or ""
            m_type = meta.get("learning_type")
            is_factual = meta.get("is_factual", False)

            # Match tasks that relate to this learned topic/domain
            matching_tasks = [
                t
                for t in tasks
                if (m_topic and m_topic.lower() in t.title.lower())
                or (m_domain and m_domain.lower() in t.title.lower())
                or (m_topic and t.description and m_topic.lower() in t.description.lower())
            ]

            if m_type == LearningType.WEAKNESS.value:
                if matching_tasks:
                    for t in matching_tasks:
                        old_mins = t.estimated_minutes
                        # Increase practice duration: 1.5x - 2.0x (Requirement example: Increase SQL joins practice)
                        new_mins = int(old_mins * 2.0) if is_factual else int(old_mins * 1.5)
                        t.estimated_minutes = new_mins

                        # Elevate priority to ensure foundational mastery
                        old_p = t.priority
                        if t.priority != GoalPriority.CRITICAL:
                            t.priority = (
                                GoalPriority.HIGH
                                if old_p == GoalPriority.MEDIUM
                                else GoalPriority.CRITICAL
                            )

                        tasks_modified_count += 1
                        impact = LearningImpact(
                            memory_id=mem.id,
                            memory_content=mem.content,
                            domain=m_domain,
                            topic=m_topic,
                            target_task_id=t.id,
                            target_task_title=t.title,
                            adjustment_type="INCREASE_PRACTICE",
                            details=(
                                f"Adapted '{t.title}': Increased practice duration from {old_mins}m to {new_mins}m "
                                f"and elevated priority to {t.priority.value} due to past learning: '{mem.content}'."
                            ),
                            confidence=mem.confidence,
                        )
                        memories_applied.append(impact)
                        summary_lines.append(impact.details)
                else:
                    # If goal is in same domain but has no practice task for this weakness, inject one
                    if (goal and m_domain and m_domain.lower() in goal.title.lower()) or (
                        goal and m_domain and m_domain.lower() in goal.objective.lower()
                    ):
                        reinforcement_title = f"Targeted Reinforcement: {m_domain} {m_topic.capitalize()} Practice".strip()
                        new_task = Task(
                            goal_id=goal_id,
                            title=reinforcement_title,
                            status=TaskStatus.PENDING,
                            priority=GoalPriority.CRITICAL if is_factual else GoalPriority.HIGH,
                            estimated_minutes=90 if is_factual else 60,
                            version=tasks[0].version if tasks else 1,
                        )
                        tasks.append(new_task)
                        if commit:
                            db.add(new_task)
                        tasks_injected_count += 1
                        impact = LearningImpact(
                            memory_id=mem.id,
                            memory_content=mem.content,
                            domain=m_domain,
                            topic=m_topic,
                            target_task_id=new_task.id,
                            target_task_title=new_task.title,
                            adjustment_type="INJECT_REINFORCEMENT_TASK",
                            details=(
                                f"Injected new task '{reinforcement_title}' ({new_task.estimated_minutes}m, "
                                f"{new_task.priority.value}) based on observed weakness: '{mem.content}'."
                            ),
                            confidence=mem.confidence,
                        )
                        memories_applied.append(impact)
                        summary_lines.append(impact.details)

        if commit and (tasks_modified_count > 0 or tasks_injected_count > 0):
            await db.commit()

        summary_rationale = (
            "Future Planner applied previous outcomes: " + "; ".join(summary_lines)
            if summary_lines
            else "Relevant memories inspected; existing plan already aligns with past learnings."
        )

        return LearningPlanningResult(
            goal_id=goal_id,
            user_id=user_id,
            relevant_memories_count=len(memories),
            memories_applied=memories_applied,
            tasks_modified_count=tasks_modified_count,
            tasks_injected_count=tasks_injected_count,
            summary_rationale=summary_rationale,
        )

    @classmethod
    async def _find_related_active_memories(
        cls,
        db: AsyncSession,
        user_id: uuid.UUID,
        domain: str | None,
        topic: str | None,
    ) -> list[Memory]:
        """Find active learning memories for this user matching domain and topic."""
        stmt = select(Memory).where(
            Memory.user_id == user_id,
            Memory.status == MemoryStatus.ACTIVE,
            Memory.source == "agent_learning_loop",
        )
        res = await db.execute(stmt)
        candidates = list(res.scalars().all())

        matched: list[Memory] = []
        for mem in candidates:
            meta = mem.metadata_json or {}
            m_domain = (meta.get("domain") or "").lower()
            m_topic = (meta.get("topic") or "").lower()

            if topic and m_topic and topic.lower() == m_topic:
                matched.append(mem)
            elif domain and m_domain and domain.lower() == m_domain:
                if not topic or not m_topic:
                    matched.append(mem)

        return matched
