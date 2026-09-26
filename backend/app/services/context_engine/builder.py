import logging
import uuid
from collections import defaultdict
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models.goal import Goal
from app.db.models.memory import Memory, MemoryStatus
from app.db.models.task import Task
from app.services.context_engine.models import (
    BuiltContext,
    ContextBudget,
    ContextItem,
    ContextSource,
)
from app.services.context_engine.scorer import RelevanceScorer
from app.services.context_engine.tokenizer import count_tokens

logger = logging.getLogger("lifethread.services.context_engine")
audit_logger = logging.getLogger("lifethread.audit.context_engine")


class ContextBuilder:
    """Intelligent, token-budgeted, relevance-scored Context Engine for LifeThread.

    Assembles context in strict accordance with the 7-level Context Priority hierarchy:
    1. Current task
    2. Current goal state
    3. Current constraints
    4. Recent relevant conversation
    5. Relevant memories
    6. Relevant documents
    7. Relevant historical events
    """

    _build_cache: dict[str, BuiltContext] = {}
    _cache_max_size: int = 512

    def __init__(self, default_budget: ContextBudget | None = None) -> None:
        self.default_budget = default_budget or ContextBudget()

    def build(
        self,
        user_id: uuid.UUID,
        items: Sequence[ContextItem],
        budget: ContextBudget | None = None,
        query: str | None = None,
    ) -> BuiltContext:
        """Build an optimized, token-bounded context from candidate items.

        Enforces:
        - Strict multi-tenant user isolation.
        - Text deduplication across and within sources.
        - Relevance scoring against query/task objective.
        - Token budgeting with per-source reservation & caps.
        - Deterministic ordering by priority hierarchy.
        """
        active_budget = (
            budget.model_copy(deep=True) if budget else self.default_budget.model_copy(deep=True)
        )
        active_budget.reset()

        # Cache check for identical query & item sequence
        cache_key = None
        if items:
            cache_key = f"{user_id}:{active_budget.total_tokens}:{query}:{hash(tuple(it.content_hash for it in items))}"
            if cache_key in self._build_cache:
                return self._build_cache[cache_key].model_copy(deep=True)

        total_candidates = len(items)

        # -------------------------------------------------------------
        # 1. Multi-Tenant User Isolation
        # -------------------------------------------------------------
        valid_user_items: list[ContextItem] = []
        for it in items:
            if it.user_id != user_id:
                audit_logger.warning(
                    "SECURITY: ContextItem %s belonging to user %s rejected for target user %s",
                    it.id,
                    it.user_id,
                    user_id,
                )
                continue
            valid_user_items.append(it)

        # -------------------------------------------------------------
        # 2. Content Deduplication
        # -------------------------------------------------------------
        # If identical or near-identical text exists, keep the highest priority item.
        # Key: content_hash -> best ContextItem
        deduped_map: dict[str, ContextItem] = {}
        for it in valid_user_items:
            h = it.content_hash
            if h not in deduped_map:
                deduped_map[h] = it
            else:
                existing = deduped_map[h]
                # Compare priority (lower number = higher priority)
                if it.effective_priority < existing.effective_priority:
                    deduped_map[h] = it
                elif it.effective_priority == existing.effective_priority:
                    if it.relevance_score > existing.relevance_score:
                        deduped_map[h] = it

        candidates = list(deduped_map.values())

        # -------------------------------------------------------------
        # 3. Relevance Scoring & Filtering
        # -------------------------------------------------------------
        scored_candidates: list[ContextItem] = []
        for it in candidates:
            # Ensure token count is set
            if it.tokens <= 0:
                it.tokens = count_tokens(it.content)

            # Score relevance if query is present
            is_high_priority = it.source in (
                ContextSource.CURRENT_TASK,
                ContextSource.CURRENT_GOAL,
                ContextSource.CONSTRAINTS,
            )
            score = RelevanceScorer.score_item(
                item_content=it.content,
                query=query,
                base_relevance=it.relevance_score,
                timestamp=it.timestamp,
                is_high_priority_source=is_high_priority,
            )
            it.relevance_score = score

            # Filter out below-threshold items (never filter out priority 1 & 2 items)
            if not is_high_priority and it.relevance_score < active_budget.min_relevance_threshold:
                continue

            scored_candidates.append(it)

        # -------------------------------------------------------------
        # 4. Token-Aware Selection within Budget
        # -------------------------------------------------------------
        # Phase A: Guaranteed / Reserved high-priority items
        # Priority 1 (Current Task), 2 (Goal), 3 (Constraints) get first right of inclusion.
        selected_items: list[ContextItem] = []
        selected_ids: set[str] = set()

        # Group candidates by source
        by_source: dict[ContextSource, list[ContextItem]] = defaultdict(list)
        for it in scored_candidates:
            by_source[it.source].append(it)

        # Process reserved budgets first
        for source, reserved_tokens in active_budget.reserved_tokens_per_source.items():
            source_candidates = by_source.get(source, [])
            # Sort within reserved category by relevance descending, recency descending
            source_candidates.sort(
                key=lambda x: (
                    -x.relevance_score,
                    -(x.timestamp.timestamp() if x.timestamp else 0.0),
                    x.id,
                )
            )
            source_tokens_used = 0
            for it in source_candidates:
                if it.id in selected_ids:
                    continue
                if source_tokens_used + it.tokens <= reserved_tokens and active_budget.can_fit(
                    it.tokens, it.source
                ):
                    if active_budget.consume(it):
                        selected_items.append(it)
                        selected_ids.add(it.id)
                        source_tokens_used += it.tokens

        # Phase B: Ranked Greedy Selection for remaining budget
        # Sort remaining candidates deterministically:
        # 1. effective_priority ascending (1 to 7)
        # 2. relevance_score descending (1.0 to 0.0)
        # 3. recency descending (newest first)
        # 4. id ascending (deterministic tiebreaker)
        remaining_candidates = [it for it in scored_candidates if it.id not in selected_ids]
        remaining_candidates.sort(
            key=lambda x: (
                x.effective_priority,
                -round(x.relevance_score, 4),
                -(x.timestamp.timestamp() if x.timestamp else 0.0),
                x.id,
            )
        )

        for it in remaining_candidates:
            if active_budget.remaining_tokens <= 0:
                break
            if active_budget.can_fit(it.tokens, it.source):
                if active_budget.consume(it):
                    selected_items.append(it)
                    selected_ids.add(it.id)

        # -------------------------------------------------------------
        # 5. Deterministic Ordering by Context Priority
        # -------------------------------------------------------------
        # Structure final context presentation strictly in 1-7 priority order:
        # Within conversation & historical events: chronological order makes conversational sense.
        # Within other categories: relevance score descending, then chunk index/timestamp, then ID.
        def item_presentation_sort_key(it: ContextItem) -> tuple[Any, ...]:
            p = it.effective_priority
            if it.source in (ContextSource.CONVERSATION, ContextSource.HISTORICAL_EVENTS):
                # Chronological order within conversation and history
                ts = it.timestamp.timestamp() if it.timestamp else 0.0
                return (p, ts, it.id)
            else:
                # Relevance descending
                return (p, -it.relevance_score, it.id)

        final_items = sorted(selected_items, key=item_presentation_sort_key)

        # -------------------------------------------------------------
        # 6. Structured Output & Prompt Generation
        # -------------------------------------------------------------
        grouped_by_source: dict[str, list[ContextItem]] = defaultdict(list)
        sources_present: list[str] = []
        for it in final_items:
            src_key = it.source.value
            if src_key not in sources_present:
                sources_present.append(src_key)
            grouped_by_source[src_key].append(it)

        formatted_prompt = self._format_context_prompt(final_items)

        dropped_count = max(0, total_candidates - len(final_items))

        built = BuiltContext(
            items=final_items,
            total_tokens=active_budget.used_tokens,
            token_budget=active_budget.total_tokens,
            items_by_source=dict(grouped_by_source),
            sources_included=sources_present,
            dropped_items_count=dropped_count,
            formatted_prompt=formatted_prompt,
        )

        if cache_key:
            if len(self._build_cache) >= self._cache_max_size:
                self._build_cache.pop(next(iter(self._build_cache)))
            self._build_cache[cache_key] = built

        return built

    def _format_context_prompt(self, items: list[ContextItem]) -> str:
        """Render deterministic, structured context markdown for the agent prompt."""
        if not items:
            return ""

        sections: list[str] = ["# AGENT CONTEXT"]

        # Group by source adhering to priority 1 -> 7
        ordered_sources = [
            ContextSource.CURRENT_TASK,
            ContextSource.CURRENT_GOAL,
            ContextSource.CONSTRAINTS,
            ContextSource.CONVERSATION,
            ContextSource.MEMORIES,
            ContextSource.DOCUMENTS,
            ContextSource.HISTORICAL_EVENTS,
        ]

        items_by_source: dict[ContextSource, list[ContextItem]] = defaultdict(list)
        for it in items:
            items_by_source[it.source].append(it)

        for src in ordered_sources:
            src_items = items_by_source.get(src, [])
            if not src_items:
                continue

            sections.append(f"\n## {src.display_label}")
            for it in src_items:
                sections.append(f"[{it.source_attribution}]")
                content_text = it.content.strip()
                if src in (ContextSource.DOCUMENTS, ContextSource.CONVERSATION):
                    from app.core.prompt_guard import PromptGuard
                    content_text = PromptGuard.wrap_untrusted_data(
                        content_text,
                        label="untrusted_retrieved_data",
                        source_attribution=it.source_attribution,
                    )
                sections.append(content_text)
                sections.append("")

        return "\n".join(sections).strip()

    async def build_from_domain(
        self,
        db: AsyncSession,
        user_id: uuid.UUID,
        task_id: uuid.UUID | None = None,
        goal_id: uuid.UUID | None = None,
        query: str | None = None,
        conversation_history: list[dict[str, Any]] | None = None,
        historical_events: list[dict[str, Any]] | None = None,
        budget: ContextBudget | None = None,
        max_memories: int = 10,
    ) -> BuiltContext:
        """Asynchronously assemble domain data into candidate items and build context.

        Gathers:
        - Active Task (if task_id provided)
        - Active Goal & Constraints (if goal_id provided, or from task)
        - Relevant active memories
        - Conversation history
        - Historical events
        """
        candidates: list[ContextItem] = []
        active_goal_id = goal_id

        # 1. Current Task (Priority 1)
        if task_id:
            stmt = (
                select(Task)
                .join(Goal, Task.goal_id == Goal.id)
                .where(Task.id == task_id, Goal.user_id == user_id)
            )
            res = await db.execute(stmt)
            task = res.scalar_one_or_none()
            if task:
                active_goal_id = active_goal_id or task.goal_id
                task_content = f"Task: {task.title}\nStatus: {task.status.value}\nPriority: {task.priority.value}"
                if task.description:
                    task_content += f"\nDescription: {task.description}"
                candidates.append(
                    ContextItem(
                        id=str(task.id),
                        source=ContextSource.CURRENT_TASK,
                        content=task_content,
                        user_id=user_id,
                        source_attribution=f"Current Task: {task.title} (#{task.id})",
                        relevance_score=1.0,
                        timestamp=task.created_at,
                    )
                )
            else:
                # Detect IDOR attempt if task belongs to another user
                from app.core.audit import SecurityAuditService, SecurityEventType
                idor_stmt = select(Goal.user_id).join(Goal, Task.goal_id == Goal.id).where(Task.id == task_id)
                idor_res = await db.execute(idor_stmt)
                owner_id = idor_res.scalar_one_or_none()
                if owner_id and owner_id != user_id:
                    SecurityAuditService.record_event(
                        event_type=SecurityEventType.IDOR_ATTEMPT_DETECTED,
                        user_id=str(user_id),
                        resource_type="task",
                        resource_id=str(task_id),
                        action="BUILD_CONTEXT_TASK",
                        details={"actual_owner_id": str(owner_id)},
                        severity="CRITICAL",
                    )

        # 2. Current Goal State (Priority 2) & 3. Constraints (Priority 3)
        if active_goal_id:
            goal_stmt = (
                select(Goal)
                .options(selectinload(Goal.constraints))
                .where(Goal.id == active_goal_id, Goal.user_id == user_id)
            )
            res = await db.execute(goal_stmt)
            goal = res.scalar_one_or_none()
            if goal:
                goal_content = (
                    f"Goal: {goal.title}\nStatus: {goal.status.value}\nObjective: {goal.objective}"
                )
                if goal.description:
                    goal_content += f"\nDescription: {goal.description}"
                if goal.deadline:
                    goal_content += f"\nDeadline: {goal.deadline.isoformat()}"

                candidates.append(
                    ContextItem(
                        id=str(goal.id),
                        source=ContextSource.CURRENT_GOAL,
                        content=goal_content,
                        user_id=user_id,
                        source_attribution=f"Goal State: {goal.title} (#{goal.id})",
                        relevance_score=1.0,
                        timestamp=goal.created_at,
                    )
                )

                # Constraints (Priority 3)
                for constraint in goal.constraints:
                    c_content = f"Constraint [{constraint.type}]: {constraint.value}"
                    candidates.append(
                        ContextItem(
                            id=str(constraint.id),
                            source=ContextSource.CONSTRAINTS,
                            content=c_content,
                            user_id=user_id,
                            source_attribution=f"Constraint: {constraint.type} (#{constraint.id})",
                            relevance_score=1.0,
                            timestamp=constraint.created_at,
                        )
                    )
            else:
                from app.core.audit import SecurityAuditService, SecurityEventType
                idor_stmt = select(Goal.user_id).where(Goal.id == active_goal_id)
                idor_res = await db.execute(idor_stmt)
                owner_id = idor_res.scalar_one_or_none()
                if owner_id and owner_id != user_id:
                    SecurityAuditService.record_event(
                        event_type=SecurityEventType.IDOR_ATTEMPT_DETECTED,
                        user_id=str(user_id),
                        resource_type="goal",
                        resource_id=str(active_goal_id),
                        action="BUILD_CONTEXT_GOAL",
                        details={"actual_owner_id": str(owner_id)},
                        severity="CRITICAL",
                    )

        # 4. Recent Relevant Conversation (Priority 4)
        if conversation_history:
            for idx, msg in enumerate(conversation_history):
                role = msg.get("role", "user")
                text = msg.get("content", "")
                ts = msg.get("timestamp")
                if isinstance(ts, str):
                    try:
                        ts = datetime.fromisoformat(ts)
                    except ValueError:
                        ts = None
                elif not isinstance(ts, datetime):
                    ts = datetime.now(UTC)

                candidates.append(
                    ContextItem(
                        id=msg.get("id", f"msg_{idx}"),
                        source=ContextSource.CONVERSATION,
                        content=f"{role.capitalize()}: {text}",
                        user_id=user_id,
                        source_attribution=f"Conversation: {role} (Turn {idx + 1})",
                        relevance_score=msg.get("relevance_score", 0.9),
                        timestamp=ts,
                    )
                )

        # 5. Relevant Memories (Priority 5)
        # Fetch active memories for this user
        mem_stmt = (
            select(Memory)
            .where(Memory.user_id == user_id, Memory.status == MemoryStatus.ACTIVE)
            .order_by(Memory.importance_score.desc(), Memory.created_at.desc())
            .limit(max_memories)
        )
        res = await db.execute(mem_stmt)
        memories = res.scalars().all()
        for mem in memories:
            candidates.append(
                ContextItem(
                    id=str(mem.id),
                    source=ContextSource.MEMORIES,
                    content=f"[{mem.memory_type.value}] {mem.content}",
                    user_id=user_id,
                    source_attribution=f"Memory: {mem.memory_type.value} (#{mem.id})",
                    relevance_score=mem.importance,
                    timestamp=mem.created_at,
                    metadata={"source": mem.source, "confidence": mem.confidence},
                )
            )

        # 6. Relevant Historical Events (Priority 7)
        if historical_events:
            for idx, evt in enumerate(historical_events):
                evt_text = evt.get("description") or evt.get("content") or str(evt)
                evt_ts = evt.get("timestamp")
                if isinstance(evt_ts, str):
                    try:
                        evt_ts = datetime.fromisoformat(evt_ts)
                    except ValueError:
                        evt_ts = None
                candidates.append(
                    ContextItem(
                        id=evt.get("id", f"evt_{idx}"),
                        source=ContextSource.HISTORICAL_EVENTS,
                        content=evt_text,
                        user_id=user_id,
                        source_attribution=f"Historical Event: {evt.get('title', 'Event')} (#{idx + 1})",
                        relevance_score=evt.get("relevance_score", 0.7),
                        timestamp=evt_ts,
                    )
                )

        return self.build(
            user_id=user_id,
            items=candidates,
            budget=budget,
            query=query,
        )
