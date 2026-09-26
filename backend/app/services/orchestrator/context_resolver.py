import logging
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.goal import Goal, GoalMilestone, GoalStatus
from app.db.models.memory import Memory, MemoryStatus
from app.db.models.task import GoalDecomposition, Task, TaskStatus
from app.services.orchestrator.models import (
    AgentIntent,
    AgentSession,
    ClarificationOption,
    ClarificationPrompt,
)

logger = logging.getLogger("lifethread.services.orchestrator.context_resolver")


class ContextResolutionResult:
    """Encapsulates resolved entities and any clarification prompt if ambiguity was detected."""

    def __init__(
        self,
        goal: Goal | None = None,
        task: Task | None = None,
        milestone: GoalMilestone | None = None,
        memory: Memory | None = None,
        clarification_prompt: ClarificationPrompt | None = None,
        is_ambiguous: bool = False,
    ) -> None:
        self.goal = goal
        self.task = task
        self.milestone = milestone
        self.memory = memory
        self.clarification_prompt = clarification_prompt
        self.is_ambiguous = is_ambiguous


class ContextResolver:
    """Domain context resolution and ambiguity detection engine for conversational agent interactions."""

    @classmethod
    async def resolve_active_goal(
        cls,
        db: AsyncSession,
        user_id: uuid.UUID,
        session: AgentSession,
        target_hint: str | None = None,
        original_intent: str | None = None,
        original_slots: dict[str, Any] | None = None,
        require_clarification_on_ambiguity: bool = True,
    ) -> tuple[Goal | None, ClarificationPrompt | None]:
        """Resolve the target active goal using session state, hints, and ambiguity detection.

        Rules:
        1. If user explicitly provided target_hint:
           - Match against user's active goals.
           - If 1 match -> return goal.
           - If >1 match -> Ambiguity is HIGH -> return ClarificationPrompt.
           - If 0 matches -> return None (or check all user goals).
        2. If no target_hint provided:
           - Check session.active_goal_id. If valid & active -> Ambiguity is LOW -> return session goal.
           - If no active goal in session:
             - Fetch all user active goals.
             - If count == 1: Exactly 1 active goal -> Ambiguity is LOW -> return goal & bind to session.
             - If count == 0: No active goals -> return (None, None).
             - If count > 1: Ambiguity is HIGH -> Do NOT guess! Return ClarificationPrompt with goal options.
        """
        # Fetch all user's active goals
        stmt = (
            select(Goal)
            .where(Goal.user_id == user_id, Goal.status == GoalStatus.ACTIVE)
            .order_by(Goal.priority.desc(), Goal.created_at.desc())
        )
        res = await db.execute(stmt)
        active_goals = list(res.scalars().all())

        if not active_goals:
            return None, None

        # 1. User gave an explicit goal name hint in the command
        if target_hint and target_hint.strip():
            hint_clean = target_hint.strip().lower()
            matches = [g for g in active_goals if hint_clean in g.title.lower()]

            if len(matches) == 1:
                matched = matches[0]
                session.active_goal_id = matched.id
                session.active_goal_title = matched.title
                return matched, None
            elif len(matches) > 1 and require_clarification_on_ambiguity:
                options = [
                    ClarificationOption(
                        id=str(g.id),
                        label=g.title,
                        entity_type="goal",
                        entity_id=str(g.id),
                        description=f"Due: {g.deadline.strftime('%b %d, %Y') if g.deadline else 'No deadline'} • Priority: {g.priority.value}",
                    )
                    for g in matches
                ]
                prompt = ClarificationPrompt(
                    clarification_type="AMBIGUOUS_GOAL",
                    prompt_message=f"I found multiple goals matching '{target_hint}'. Which one did you mean?",
                    original_intent=original_intent or AgentIntent.UNKNOWN.value,
                    original_slots=original_slots or {},
                    options=options,
                )
                return None, prompt

        # 2. Check existing session focus
        if session.active_goal_id:
            session_goal = next((g for g in active_goals if g.id == session.active_goal_id), None)
            if session_goal:
                session.active_goal_title = session_goal.title
                return session_goal, None
            # If not in active_goals, try DB directly (might be completed or paused)
            db_goal = await db.get(Goal, session.active_goal_id)
            if db_goal and db_goal.user_id == user_id and db_goal.status == GoalStatus.ACTIVE:
                session.active_goal_title = db_goal.title
                return db_goal, None

        # 3. No session focus: check count of active goals
        if len(active_goals) == 1:
            sole_goal = active_goals[0]
            session.active_goal_id = sole_goal.id
            session.active_goal_title = sole_goal.title
            return sole_goal, None

        # 4. Count > 1 and no session focus: HIGH AMBIGUITY!
        if require_clarification_on_ambiguity:
            intent_verb = "update"
            if original_intent == AgentIntent.CHANGE_DEADLINE.value:
                raw_d = (original_slots or {}).get("raw_date", "the requested date")
                intent_verb = f"change the deadline to {raw_d} for"
            elif original_intent == AgentIntent.UPDATE_PRIORITY.value:
                prio = (original_slots or {}).get("priority", "the requested priority")
                intent_verb = f"set the priority to {prio} for"

            options = [
                ClarificationOption(
                    id=str(g.id),
                    label=g.title,
                    entity_type="goal",
                    entity_id=str(g.id),
                    description=f"Due: {g.deadline.strftime('%b %d, %Y') if g.deadline else 'No deadline'} • Priority: {g.priority.value}",
                )
                for g in active_goals[:5]
            ]

            prompt = ClarificationPrompt(
                clarification_type="AMBIGUOUS_GOAL",
                prompt_message=f"You have {len(active_goals)} active goals. Which goal would you like to {intent_verb}?",
                original_intent=original_intent or AgentIntent.UNKNOWN.value,
                original_slots=original_slots or {},
                options=options,
            )
            return None, prompt

        # Non-strict fallback (e.g. for general status)
        fallback = active_goals[0]
        session.active_goal_id = fallback.id
        session.active_goal_title = fallback.title
        return fallback, None

    @classmethod
    async def resolve_task(
        cls,
        db: AsyncSession,
        user_id: uuid.UUID,
        session: AgentSession,
        active_goal: Goal | None,
        task_hint: str | None = None,
        original_intent: str | None = None,
        original_slots: dict[str, Any] | None = None,
    ) -> tuple[Task | None, ClarificationPrompt | None]:
        """Resolve target task from session or search matching tasks under active goal."""
        if not active_goal:
            return None, None

        # Fetch active decomposition tasks
        decomp_q = (
            select(GoalDecomposition)
            .where(GoalDecomposition.goal_id == active_goal.id, GoalDecomposition.is_active.is_(True))
            .order_by(GoalDecomposition.version.desc())
        )
        decomp_res = await db.execute(decomp_q)
        active_decomp = decomp_res.scalars().first()
        target_version = active_decomp.version if active_decomp else 1

        tasks_q = (
            select(Task)
            .where(Task.goal_id == active_goal.id, Task.version == target_version)
        )
        tasks_res = await db.execute(tasks_q)
        tasks = list(tasks_res.scalars().all())

        if not tasks:
            return None, None

        # 1. Hint provided (e.g. "mark setup environment done")
        if task_hint and task_hint.strip():
            hint_clean = task_hint.strip().lower()
            matches = [t for t in tasks if hint_clean in t.title.lower()]
            if len(matches) == 1:
                t = matches[0]
                session.current_task_id = t.id
                session.current_task_title = t.title
                return t, None
            elif len(matches) > 1:
                options = [
                    ClarificationOption(
                        id=str(t.id),
                        label=t.title,
                        entity_type="task",
                        entity_id=str(t.id),
                        description=f"Status: {t.status.value} • {t.estimated_minutes} min",
                    )
                    for t in matches
                ]
                prompt = ClarificationPrompt(
                    clarification_type="AMBIGUOUS_TASK",
                    prompt_message=f"Multiple tasks match '{task_hint}'. Which one did you mean?",
                    original_intent=original_intent or AgentIntent.UNKNOWN.value,
                    original_slots=original_slots or {},
                    options=options,
                )
                return None, prompt

        # 2. Check session current task
        if session.current_task_id:
            t = next((item for item in tasks if item.id == session.current_task_id), None)
            if t:
                session.current_task_title = t.title
                return t, None

        # 3. Find first in-progress or pending task
        pending = [t for t in tasks if t.status in [TaskStatus.IN_PROGRESS, TaskStatus.NOT_STARTED, TaskStatus.READY]]
        if pending:
            first_t = pending[0]
            session.current_task_id = first_t.id
            session.current_task_title = first_t.title
            return first_t, None

        return None, None

    @classmethod
    async def resolve_milestone(
        cls,
        db: AsyncSession,
        user_id: uuid.UUID,
        session: AgentSession,
        active_goal: Goal | None,
        milestone_hint: str | None = None,
    ) -> tuple[GoalMilestone | None, list[GoalMilestone]]:
        """Resolve active milestone for the given goal or list all milestones."""
        if not active_goal:
            return None, []

        stmt = (
            select(GoalMilestone)
            .where(GoalMilestone.goal_id == active_goal.id)
            .order_by(GoalMilestone.order_index.asc())
        )
        res = await db.execute(stmt)
        milestones = list(res.scalars().all())

        if not milestones:
            return None, []

        if milestone_hint and milestone_hint.strip():
            hint_clean = milestone_hint.strip().lower()
            matched = next((m for m in milestones if hint_clean in m.title.lower()), None)
            if matched:
                session.active_milestone_id = matched.id
                session.active_milestone_title = matched.title
                return matched, milestones

        if session.active_milestone_id:
            matched = next((m for m in milestones if m.id == session.active_milestone_id), None)
            if matched:
                session.active_milestone_title = matched.title
                return matched, milestones

        # Default to first milestone
        first_m = milestones[0]
        session.active_milestone_id = first_m.id
        session.active_milestone_title = first_m.title
        return first_m, milestones

    @classmethod
    async def resolve_memory(
        cls,
        db: AsyncSession,
        user_id: uuid.UUID,
        session: AgentSession,
        memory_id_hint: uuid.UUID | None = None,
    ) -> Memory | None:
        """Resolve referenced memory from session or hint."""
        target_id = memory_id_hint or session.last_referenced_memory_id
        if not target_id:
            return None

        mem = await db.get(Memory, target_id)
        if mem and mem.user_id == user_id and mem.status == MemoryStatus.ACTIVE:
            session.last_referenced_memory_id = mem.id
            return mem
        return None

    @classmethod
    async def resolve_clarification_response(
        cls,
        db: AsyncSession,
        user_id: uuid.UUID,
        session: AgentSession,
        user_utterance: str,
    ) -> tuple[ClarificationOption | None, bool]:
        """Determine if user's utterance answers a pending clarification question.

        Returns:
            (selected_option, is_cancel)
        """
        prompt = session.pending_clarification
        if not prompt or not prompt.options:
            return None, False

        raw = user_utterance.strip()
        lower = raw.lower()

        # Cancellation
        if lower in ["cancel", "never mind", "nevermind", "stop", "abort", "no"]:
            return None, True

        # Match against options
        from app.services.orchestrator.nlu import NLUEngine
        matched = NLUEngine.match_clarification_choice(raw, prompt.options)
        return matched, False
