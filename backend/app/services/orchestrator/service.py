import logging
import threading
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models.goal import Goal, GoalPriority, GoalStatus
from app.db.models.memory import Memory, MemoryStatus, MemoryType
from app.db.models.plan import Plan
from app.db.models.task import GoalDecomposition, Task, TaskStatus
from app.db.models.user import User
from app.schemas.decomposition import DecompositionRequest
from app.schemas.goal import GoalCreate
from app.schemas.memory import MemoryCreate
from app.schemas.plan import PlanCreateRequest
from app.services.agent_trace.models import EventStatus, ExecutionEventType
from app.services.agent_trace.service import AgentTraceService
from app.services.decomposition import DecompositionService
from app.services.evaluation import EvaluationService
from app.services.goal import GoalService
from app.services.memory import MemoryService
from app.services.orchestrator.context_resolver import ContextResolver
from app.services.orchestrator.date_parser import DateParser
from app.services.orchestrator.models import (
    AgentIntent,
    AgentSession,
    ChatMessage,
    ChatMessageRole,
    ChatRequest,
    ChatResponse,
    ClarificationOption,
    ClarificationPrompt,
    ConversationContextSummary,
)
from app.services.orchestrator.nlu import NLUEngine
from app.services.planning import PlanningService
from app.services.replanning.engine import AutonomousReplanningEngine
from app.services.replanning.models import ReplanningEvent, ReplanningReason

logger = logging.getLogger("lifethread.services.orchestrator")


class AgentOrchestrator:
    """Core domain Agent Orchestrator connecting conversational commands to real LifeThread state."""

    _lock = threading.Lock()
    _sessions: dict[str, AgentSession] = {}

    @classmethod
    def get_or_create_session(
        cls,
        user_id: uuid.UUID,
        session_id: str | None = None,
        active_goal_id: uuid.UUID | None = None,
        current_task_id: uuid.UUID | None = None,
    ) -> AgentSession:
        """Retrieve existing agent conversation session or initialize a fresh stateful session."""
        with cls._lock:
            if session_id and session_id in cls._sessions:
                session = cls._sessions[session_id]
                # Enforce tenant isolation on session
                if session.user_id == user_id:
                    if active_goal_id:
                        session.active_goal_id = active_goal_id
                    if current_task_id:
                        session.current_task_id = current_task_id
                    session.updated_at = datetime.now(UTC)
                    return session

            # Create new session
            new_id = session_id or str(uuid.uuid4())
            session = AgentSession(
                session_id=new_id,
                user_id=user_id,
                active_goal_id=active_goal_id,
                current_task_id=current_task_id,
            )
            cls._sessions[new_id] = session
            return session

    @classmethod
    async def process_chat(
        cls,
        db: AsyncSession,
        user_id: uuid.UUID,
        request: ChatRequest,
    ) -> ChatResponse:
        """Main conversational entrypoint executing natural-language commands against real agent operations."""
        # 1. Session resolution
        session = cls.get_or_create_session(
            user_id=user_id,
            session_id=request.session_id,
            active_goal_id=request.active_goal_id,
            current_task_id=request.current_task_id,
        )

        # 2. Record User message in session
        user_msg = ChatMessage(
            role=ChatMessageRole.USER,
            content=request.message,
        )
        session.messages.append(user_msg)

        # 3. Handle pending clarification if active
        resumed_from_clarification = False
        if session.pending_clarification:
            matched_option, is_cancel = await ContextResolver.resolve_clarification_response(
                db=db,
                user_id=user_id,
                session=session,
                user_utterance=request.message,
            )
            if is_cancel:
                session.pending_clarification = None
                cancel_text = "No problem, I've cancelled that request. What would you like to work on instead?"
                assistant_msg = ChatMessage(
                    role=ChatMessageRole.ASSISTANT,
                    content=cancel_text,
                    intent=AgentIntent.UNKNOWN,
                )
                session.messages.append(assistant_msg)
                session.updated_at = datetime.now(UTC)
                return ChatResponse(
                    session_id=session.session_id,
                    message=assistant_msg,
                    intent=AgentIntent.UNKNOWN,
                    active_goal_id=session.active_goal_id,
                    active_goal_title=session.active_goal_title,
                    current_task_id=session.current_task_id,
                    current_task_title=session.current_task_title,
                    active_milestone_id=session.active_milestone_id,
                    active_milestone_title=session.active_milestone_title,
                    last_referenced_memory_id=session.last_referenced_memory_id,
                    suggested_replies=["What should I do next?", "What changed?"],
                )

            if matched_option:
                orig_prompt = session.pending_clarification
                session.pending_clarification = None
                if matched_option.entity_type == "goal":
                    session.active_goal_id = uuid.UUID(matched_option.entity_id)
                    session.active_goal_title = matched_option.label
                elif matched_option.entity_type == "task":
                    session.current_task_id = uuid.UUID(matched_option.entity_id)
                    session.current_task_title = matched_option.label
                elif matched_option.entity_type == "milestone":
                    session.active_milestone_id = uuid.UUID(matched_option.entity_id)
                    session.active_milestone_title = matched_option.label

                intent = AgentIntent(orig_prompt.original_intent)
                slots = orig_prompt.original_slots
                resumed_from_clarification = True
            else:
                # User typed a fresh utterance; clear clarification and parse normally
                session.pending_clarification = None
                intent, slots = NLUEngine.parse_intent(request.message)
        else:
            intent, slots = NLUEngine.parse_intent(request.message)

        user_msg.intent = intent

        # 4. Context Resolution & Ambiguity Detection
        active_goal = None
        if intent == AgentIntent.CHANGE_DEADLINE:
            target_hint = slots.get("target")
            active_goal, clarification_prompt = await ContextResolver.resolve_active_goal(
                db=db,
                user_id=user_id,
                session=session,
                target_hint=target_hint,
                original_intent=intent.value,
                original_slots=slots,
                require_clarification_on_ambiguity=True,
            )
            if clarification_prompt:
                session.pending_clarification = clarification_prompt
                clarification_msg = ChatMessage(
                    role=ChatMessageRole.ASSISTANT,
                    content=clarification_prompt.prompt_message,
                    intent=intent,
                )
                session.messages.append(clarification_msg)
                session.updated_at = datetime.now(UTC)
                return ChatResponse(
                    session_id=session.session_id,
                    message=clarification_msg,
                    intent=intent,
                    active_goal_id=session.active_goal_id,
                    active_goal_title=session.active_goal_title,
                    current_task_id=session.current_task_id,
                    current_task_title=session.current_task_title,
                    active_milestone_id=session.active_milestone_id,
                    active_milestone_title=session.active_milestone_title,
                    last_referenced_memory_id=session.last_referenced_memory_id,
                    clarification_prompt=clarification_prompt,
                    suggested_replies=[opt.label for opt in clarification_prompt.options[:4]],
                )

        elif intent == AgentIntent.UPDATE_PRIORITY and slots.get("target_type") == "goal":
            target_hint = slots.get("target_name")
            active_goal, clarification_prompt = await ContextResolver.resolve_active_goal(
                db=db,
                user_id=user_id,
                session=session,
                target_hint=target_hint,
                original_intent=intent.value,
                original_slots=slots,
                require_clarification_on_ambiguity=True,
            )
            if clarification_prompt:
                session.pending_clarification = clarification_prompt
                clarification_msg = ChatMessage(
                    role=ChatMessageRole.ASSISTANT,
                    content=clarification_prompt.prompt_message,
                    intent=intent,
                )
                session.messages.append(clarification_msg)
                session.updated_at = datetime.now(UTC)
                return ChatResponse(
                    session_id=session.session_id,
                    message=clarification_msg,
                    intent=intent,
                    active_goal_id=session.active_goal_id,
                    active_goal_title=session.active_goal_title,
                    current_task_id=session.current_task_id,
                    current_task_title=session.current_task_title,
                    active_milestone_id=session.active_milestone_id,
                    active_milestone_title=session.active_milestone_title,
                    last_referenced_memory_id=session.last_referenced_memory_id,
                    clarification_prompt=clarification_prompt,
                    suggested_replies=[opt.label for opt in clarification_prompt.options[:4]],
                )

        else:
            active_goal = await cls._resolve_active_goal(db, user_id, session)

        # 5. Start Agent Run Trace for provenance
        run = AgentTraceService.start_run(
            user_id=user_id,
            trigger=f"CONVERSATION:{intent.value}",
            goal_id=active_goal.id if active_goal else None,
            goal_title=active_goal.title if active_goal else None,
            task_id=session.current_task_id,
            task_title=session.current_task_title,
            summary=f"Executing conversational command: '{request.message[:80]}'",
            correlation_id=session.session_id,
            input_data={"message": request.message, "intent": intent.value, "slots": slots},
        )

        # Stage 2: Selected Context
        AgentTraceService.record_selected_context(
            run_id=run.id,
            user_id=user_id,
            context={
                "session_id": session.session_id,
                "active_goal_id": str(session.active_goal_id) if session.active_goal_id else None,
                "active_goal_title": session.active_goal_title,
                "current_task_id": str(session.current_task_id) if session.current_task_id else None,
                "current_task_title": session.current_task_title,
                "active_milestone_id": str(session.active_milestone_id) if session.active_milestone_id else None,
                "active_milestone_title": session.active_milestone_title,
            },
            rationale="Resolved active conversational context entities.",
        )

        # Record DECISION event with skill selection
        from app.services.skills.registry import SkillRegistry

        selected_skill = SkillRegistry.select_skill(
            request.message,
            {"goal_id": active_goal.id if active_goal else None},
        )
        selected_skill_name = selected_skill.name if selected_skill else None

        # Stage 4: Selected Tools / Skills
        AgentTraceService.record_selected_tools(
            run_id=run.id,
            user_id=user_id,
            tools=[selected_skill_name] if selected_skill_name else ["orchestrator"],
            rationale=f"Selected {selected_skill_name or 'orchestrator'} for intent {intent.value}.",
        )

        decision_notes = f"Parsed intent '{intent.value}' and selected skill '{selected_skill_name or 'orchestrator'}'."
        if resumed_from_clarification:
            decision_notes = f"Resolved clarification choice. Executing '{intent.value}' on {session.active_goal_title}."

        AgentTraceService.record_event(
            run_id=run.id,
            user_id=user_id,
            event_type=ExecutionEventType.DECISION,
            status=EventStatus.SUCCESS,
            short_explanation=decision_notes,
            goal_id=active_goal.id if active_goal else None,
            goal_title=active_goal.title if active_goal else None,
            metadata={
                "intent": intent.value,
                "slots": slots,
                "selected_skill": selected_skill_name,
                "resumed_from_clarification": resumed_from_clarification,
            },
        )

        # 6. Dispatch to specific intent handler
        response_text = ""
        card_type: str | None = None
        card_data: dict[str, Any] | None = None
        state_updates: dict[str, Any] = {}
        suggested_replies: list[str] = []

        try:
            if intent == AgentIntent.CHANGE_DEADLINE:
                (
                    response_text,
                    card_type,
                    card_data,
                    state_updates,
                    suggested_replies,
                ) = await cls._handle_change_deadline(db, user_id, session, active_goal, slots, run.id)

            elif intent == AgentIntent.UPDATE_PRIORITY:
                (
                    response_text,
                    card_type,
                    card_data,
                    state_updates,
                    suggested_replies,
                ) = await cls._handle_update_priority(db, user_id, session, active_goal, slots, run.id)

            elif intent == AgentIntent.MILESTONE_QUERY:
                (
                    response_text,
                    card_type,
                    card_data,
                    state_updates,
                    suggested_replies,
                ) = await cls._handle_milestone_query(db, user_id, session, active_goal, slots, run.id)

            elif intent == AgentIntent.MEMORY_QUERY:
                (
                    response_text,
                    card_type,
                    card_data,
                    state_updates,
                    suggested_replies,
                ) = await cls._handle_memory_query(db, user_id, session, run.id)

            elif intent == AgentIntent.CREATE_GOAL:
                (
                    response_text,
                    card_type,
                    card_data,
                    state_updates,
                    suggested_replies,
                ) = await cls._handle_create_goal(db, user_id, session, slots, run.id)

            elif intent == AgentIntent.NEXT_ACTION:
                (
                    response_text,
                    card_type,
                    card_data,
                    state_updates,
                    suggested_replies,
                ) = await cls._handle_next_action(db, user_id, session, active_goal, run.id)

            elif intent == AgentIntent.WHAT_CHANGED:
                (
                    response_text,
                    card_type,
                    card_data,
                    state_updates,
                    suggested_replies,
                ) = await cls._handle_what_changed(db, user_id, session, active_goal, run.id)

            elif intent == AgentIntent.WHY_PLAN_CHANGED:
                (
                    response_text,
                    card_type,
                    card_data,
                    state_updates,
                    suggested_replies,
                ) = await cls._handle_why_plan_changed(db, user_id, session, active_goal, run.id)

            elif intent == AgentIntent.CAPACITY_CONSTRAINT:
                (
                    response_text,
                    card_type,
                    card_data,
                    state_updates,
                    suggested_replies,
                ) = await cls._handle_capacity_constraint(
                    db, user_id, session, active_goal, slots, run.id
                )

            elif intent == AgentIntent.REMEMBER_FACT:
                (
                    response_text,
                    card_type,
                    card_data,
                    state_updates,
                    suggested_replies,
                ) = await cls._handle_remember_fact(
                    db, user_id, session, active_goal, slots, run.id
                )

            elif intent == AgentIntent.WHAT_IS_BLOCKING:
                (
                    response_text,
                    card_type,
                    card_data,
                    state_updates,
                    suggested_replies,
                ) = await cls._handle_what_is_blocking(db, user_id, session, active_goal, run.id)

            elif intent == AgentIntent.COMPLETE_TASK:
                (
                    response_text,
                    card_type,
                    card_data,
                    state_updates,
                    suggested_replies,
                ) = await cls._handle_complete_task(db, user_id, session, active_goal, slots, run.id)

            elif intent == AgentIntent.SWITCH_GOAL:
                (
                    response_text,
                    card_type,
                    card_data,
                    state_updates,
                    suggested_replies,
                ) = await cls._handle_switch_goal(db, user_id, session, slots, run.id)

            else:
                response_text = (
                    "I am connected to your LifeThread Agent Orchestrator. Here is what I can do:\n\n"
                    "- **\"Change the deadline to Friday.\"** &rarr; Updates goal deadline and autonomous schedule\n"
                    "- **\"What should I do next?\"** &rarr; Identifies your unblocked critical path task\n"
                    "- **\"What changed?\"** &rarr; Visualizes the real plan diff between versions\n"
                    "- **\"Why did my plan change?\"** &rarr; Explains replanning causes without exposing CoT\n"
                    "- **\"I only have one hour today.\"** &rarr; Rebalances your plan to match capacity\n"
                    "- **\"Remember that I struggle with SQL joins.\"** &rarr; Persists learned weaknesses & preferences\n"
                    "- **\"What is blocking my goal?\"** &rarr; Diagnoses dependency blockers & risks\n"
                    "- **\"Create a goal: [Title]\"** &rarr; Initializes, decomposes, and plans a new goal"
                )
                suggested_replies = [
                    "What should I do next?",
                    "What is blocking my goal?",
                    "Change the deadline to Friday",
                    "What changed?",
                ]

            if state_updates:
                AgentTraceService.record_state_changes(
                    run_id=run.id,
                    user_id=user_id,
                    state_changes=state_updates,
                )

            if card_type in ("plan_diff", "capacity_replan") and card_data:
                AgentTraceService.record_replanning_event(
                    run_id=run.id,
                    user_id=user_id,
                    replanning_data=card_data,
                )

            AgentTraceService.record_final_result(
                run_id=run.id,
                user_id=user_id,
                final_result={
                    "response_text": response_text,
                    "card_type": card_type,
                    "card_data": card_data,
                    "suggested_replies": suggested_replies,
                },
                rationale="Completed execution of conversational command.",
            )

            AgentTraceService.finish_run(run_id=run.id, user_id=user_id, status=EventStatus.SUCCESS)

        except Exception as e:
            logger.exception("Error executing conversational intent %s: %s", intent, e)
            AgentTraceService.record_event(
                run_id=run.id,
                user_id=user_id,
                event_type=ExecutionEventType.EVALUATION,
                status=EventStatus.FAILED,
                short_explanation=f"Error processing command: {str(e)}",
            )
            AgentTraceService.record_final_result(
                run_id=run.id,
                user_id=user_id,
                final_result={"error": str(e)},
                rationale="Agent execution failed during command processing.",
            )
            AgentTraceService.finish_run(run_id=run.id, user_id=user_id, status=EventStatus.FAILED)
            response_text = f"I encountered an issue executing that command: {str(e)}"
            suggested_replies = ["What should I do next?", "Status"]

        # 7. Record Assistant response in session
        assistant_msg = ChatMessage(
            role=ChatMessageRole.ASSISTANT,
            content=response_text,
            intent=intent,
            card_type=card_type,
            card_data=card_data,
            run_id=run.id,
            trace_id=run.trace_id,
            correlation_id=run.correlation_id,
        )
        session.messages.append(assistant_msg)
        session.updated_at = datetime.now(UTC)

        return ChatResponse(
            session_id=session.session_id,
            message=assistant_msg,
            intent=intent,
            active_goal_id=session.active_goal_id,
            active_goal_title=session.active_goal_title,
            current_task_id=session.current_task_id,
            current_task_title=session.current_task_title,
            active_milestone_id=session.active_milestone_id,
            active_milestone_title=session.active_milestone_title,
            last_referenced_memory_id=session.last_referenced_memory_id,
            clarification_prompt=session.pending_clarification,
            run_id=run.id,
            trace_id=run.trace_id,
            correlation_id=run.correlation_id,
            state_updates=state_updates,
            card_type=card_type,
            card_data=card_data,
            suggested_replies=suggested_replies,
        )

    # -------------------------------------------------------------------------
    # Helper: Active Goal Resolution
    # -------------------------------------------------------------------------
    @classmethod
    async def _resolve_active_goal(
        cls,
        db: AsyncSession,
        user_id: uuid.UUID,
        session: AgentSession,
    ) -> Goal | None:
        """Resolve current active goal from session or retrieve user's primary active goal."""
        goal, _ = await ContextResolver.resolve_active_goal(
            db=db,
            user_id=user_id,
            session=session,
            require_clarification_on_ambiguity=False,
        )
        return goal

    # -------------------------------------------------------------------------
    # Handler 1: Create Goal
    # -------------------------------------------------------------------------
    @classmethod
    async def _handle_create_goal(
        cls,
        db: AsyncSession,
        user_id: uuid.UUID,
        session: AgentSession,
        slots: dict[str, Any],
        run_id: str,
    ) -> tuple[str, str | None, dict[str, Any] | None, dict[str, Any], list[str]]:
        title = slots.get("title")
        days = slots.get("days", 30)

        if not title:
            # Underspecified: prompt user
            return (
                "I'm ready to create your goal! What would you like to achieve, and do you have a target timeframe?\n\n"
                "You can say:\n"
                "- *\"Create a goal: Learn Advanced Rust in 30 days\"*\n"
                "- *\"Create a goal: Launch SaaS MVP in 60 days\"*\n"
                "- *\"Create a goal to run a 10k in 6 weeks\"*",
                None,
                None,
                {},
                [
                    "Create a goal: Learn Advanced Rust in 30 days",
                    "Create a goal: Launch SaaS MVP in 60 days",
                ],
            )

        now = datetime.now(UTC)
        deadline = now + timedelta(days=days)

        # 1. Create Goal
        goal_in = GoalCreate(
            title=title,
            objective=f"Complete '{title}' within {days} days",
            description=f"Autonomously created via Conversational Interface with {days}-day horizon.",
            priority=GoalPriority.HIGH,
            deadline=deadline,
        )
        goal = await GoalService.create_goal(db=db, user_id=user_id, goal_in=goal_in)

        # Record Tool Call
        AgentTraceService.record_event(
            run_id=run_id,
            user_id=user_id,
            event_type=ExecutionEventType.TOOL_CALL,
            status=EventStatus.SUCCESS,
            short_explanation=f"Executed Tool 'create_goal' for title: '{goal.title}'",
            goal_id=goal.id,
            goal_title=goal.title,
            tool_name="create_goal",
            tool_parameters={"title": goal.title, "deadline": deadline.isoformat()},
        )

        # 2. Decompose Goal with fallback for offline/test environments
        import json

        from app.core.config import get_settings
        from app.services.llm.mock import MockLLMProvider

        def _get_mock_decomp_provider(goal_title: str) -> MockLLMProvider:
            mock_json = json.dumps({
                "milestones": [
                    {"title": f"Phase 1: {goal_title} Foundations", "description": "Core concepts and initial setup", "order_index": 0},
                    {"title": f"Phase 2: {goal_title} Implementation", "description": "Execution and validation", "order_index": 1},
                ],
                "tasks": [
                    {
                        "temp_id": "T1",
                        "milestone_index": 0,
                        "title": f"Set up environment and study {goal_title} fundamentals",
                        "description": "Establish workspace and review core concepts",
                        "priority": "HIGH",
                        "estimated_minutes": 60,
                    },
                    {
                        "temp_id": "T2",
                        "milestone_index": 0,
                        "title": f"Build initial core module for {goal_title}",
                        "description": "Implement essential functionality and write unit tests",
                        "priority": "HIGH",
                        "estimated_minutes": 120,
                    },
                    {
                        "temp_id": "T3",
                        "milestone_index": 1,
                        "title": f"Finalize implementation and benchmarks for {goal_title}",
                        "description": "Complete capstone requirements and optimize execution",
                        "priority": "MEDIUM",
                        "estimated_minutes": 180,
                    },
                ],
                "dependencies": [
                    {"task_temp_id": "T2", "depends_on_temp_id": "T1", "dependency_type": "BLOCKS"},
                    {"task_temp_id": "T3", "depends_on_temp_id": "T2", "dependency_type": "BLOCKS"},
                ],
            })
            return MockLLMProvider(default_response=mock_json)

        settings = get_settings()
        llm_provider = _get_mock_decomp_provider(title) if (not settings.OPENAI_API_KEY or "CHANGEME" in settings.OPENAI_API_KEY) else None

        try:
            decomp = await DecompositionService.decompose_goal(
                db=db,
                goal_id=goal.id,
                user_id=user_id,
                request=DecompositionRequest(),
                llm_provider=llm_provider,
            )
        except Exception as decomp_err:
            logger.warning("Primary decomposition failed (%s), using structured fallback", decomp_err)
            decomp = await DecompositionService.decompose_goal(
                db=db,
                goal_id=goal.id,
                user_id=user_id,
                request=DecompositionRequest(),
                llm_provider=_get_mock_decomp_provider(title),
            )

        # 3. Generate Initial Plan v1
        plan_resp = await PlanningService.generate_plan(
            db=db,
            goal_id=goal.id,
            user_id=user_id,
            request=PlanCreateRequest(start_date=now),
        )

        # 4. Update session context
        session.active_goal_id = goal.id
        session.active_goal_title = goal.title

        first_task = plan_resp.items[0] if plan_resp.items else None
        if first_task:
            session.current_task_id = first_task.task_id
            session.current_task_title = first_task.task_title

        # Record State Update event
        AgentTraceService.record_event(
            run_id=run_id,
            user_id=user_id,
            event_type=ExecutionEventType.STATE_UPDATE,
            status=EventStatus.SUCCESS,
            short_explanation=f"Created Goal '{goal.title}', decomposed {len(decomp.tasks)} tasks, and generated Plan v1.",
            goal_id=goal.id,
            goal_title=goal.title,
            metadata={"tasks_count": len(decomp.tasks), "plan_version": plan_resp.version},
        )

        resp_text = (
            f"Successfully created and scheduled your new goal: **{goal.title}**!\n\n"
            f"- **Target Timeline**: {days} days (Due {deadline.strftime('%b %d, %Y')})\n"
            f"- **Milestones**: {len(decomp.milestones)} decomposed\n"
            f"- **Tasks Scheduled**: {len(decomp.tasks)} items across Plan v1\n"
            f"- **First Action**: {first_task.task_title if first_task else 'None'}"
        )

        card_data = {
            "goal_id": str(goal.id),
            "title": goal.title,
            "deadline": deadline.isoformat(),
            "milestones_count": len(decomp.milestones),
            "tasks_count": len(decomp.tasks),
            "first_task_id": str(first_task.task_id) if first_task else None,
            "first_task_title": first_task.task_title if first_task else None,
        }

        return (
            resp_text,
            "goal_created",
            card_data,
            {"goal_id": str(goal.id), "active_goal_title": goal.title},
            ["What should I do next?", "What is blocking my goal?", "What changed?"],
        )

    # -------------------------------------------------------------------------
    # Handler 2: Next Action
    # -------------------------------------------------------------------------
    @classmethod
    async def _handle_next_action(
        cls,
        db: AsyncSession,
        user_id: uuid.UUID,
        session: AgentSession,
        active_goal: Goal | None,
        run_id: str,
    ) -> tuple[str, str | None, dict[str, Any] | None, dict[str, Any], list[str]]:
        if not active_goal:
            return (
                "You don't have any active goals yet! You can say *'Create a goal: Learn Rust in 30 days'* to start your journey.",
                None,
                None,
                {},
                ["Create a goal: Learn Advanced Rust in 30 days"],
            )

        # Retrieve tasks for active goal with dependencies
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
            .options(selectinload(Task.outgoing_dependencies))
        )
        tasks_res = await db.execute(tasks_q)
        all_tasks = list(tasks_res.scalars().all())

        if not all_tasks:
            return (
                f"Goal **{active_goal.title}** has no scheduled tasks yet. Would you like me to generate a plan?",
                None,
                None,
                {},
                ["What changed?", "What is blocking my goal?"],
            )

        task_status_map = {t.id: t.status for t in all_tasks}

        # Filter to uncompleted and unblocked tasks
        unblocked_candidates: list[Task] = []
        for t in all_tasks:
            if t.status in [TaskStatus.COMPLETED, TaskStatus.CANCELLED]:
                continue
            # Check outgoing dependencies (all prerequisites must be completed)
            prereqs_done = True
            for dep in t.outgoing_dependencies:
                prereq_status = task_status_map.get(dep.depends_on_task_id)
                if prereq_status != TaskStatus.COMPLETED:
                    prereqs_done = False
                    break
            if prereqs_done:
                unblocked_candidates.append(t)

        if not unblocked_candidates:
            # Check if all completed
            if all(t.status == TaskStatus.COMPLETED for t in all_tasks):
                return (
                    f"Congratulations! All tasks for **{active_goal.title}** have been completed! What would you like to tackle next?",
                    None,
                    None,
                    {},
                    ["Create a goal.", "What changed?"],
                )
            else:
                return (
                    f"All remaining tasks for **{active_goal.title}** are currently waiting on prerequisites. Ask *'What is blocking my goal?'* to inspect dependencies.",
                    None,
                    None,
                    {},
                    ["What is blocking my goal?", "What changed?"],
                )

        # Prioritize: IN_PROGRESS first, then priority CRITICAL > HIGH > MEDIUM > LOW
        prio_order = {
            GoalPriority.CRITICAL: 4,
            GoalPriority.HIGH: 3,
            GoalPriority.MEDIUM: 2,
            GoalPriority.LOW: 1,
        }
        unblocked_candidates.sort(
            key=lambda t: (
                1 if t.status == TaskStatus.IN_PROGRESS else 0,
                prio_order.get(t.priority, 1),
                -t.estimated_minutes,
            ),
            reverse=True,
        )

        chosen = unblocked_candidates[0]
        session.current_task_id = chosen.id
        session.current_task_title = chosen.title

        AgentTraceService.record_event(
            run_id=run_id,
            user_id=user_id,
            event_type=ExecutionEventType.EVALUATION,
            status=EventStatus.SUCCESS,
            short_explanation=f"Evaluated task graph: selected '{chosen.title}' as next unblocked action.",
            goal_id=active_goal.id,
            goal_title=active_goal.title,
            task_id=chosen.id,
            task_title=chosen.title,
            metadata={"priority": chosen.priority.value, "status": chosen.status.value},
        )

        resp_text = (
            f"Based on your active goal **{active_goal.title}**, your next recommended action is:\n\n"
            f"### **{chosen.title}**\n"
            f"- **Priority**: {chosen.priority.value}\n"
            f"- **Estimated Time**: {chosen.estimated_minutes} min\n"
            f"- **Status**: {chosen.status.value}\n\n"
            f"All prerequisite dependencies are satisfied and this task is on your critical path. You can mark it complete when done."
        )

        card_data = {
            "task_id": str(chosen.id),
            "title": chosen.title,
            "priority": chosen.priority.value,
            "status": chosen.status.value,
            "estimated_minutes": chosen.estimated_minutes,
            "goal_id": str(active_goal.id),
            "goal_title": active_goal.title,
        }

        return (
            resp_text,
            "next_action",
            card_data,
            {"current_task_id": str(chosen.id), "current_task_title": chosen.title},
            ["I finished the task", "What is blocking my goal?", "I only have one hour today."],
        )

    # -------------------------------------------------------------------------
    # Handler 3: What Changed
    # -------------------------------------------------------------------------
    @classmethod
    async def _handle_what_changed(
        cls,
        db: AsyncSession,
        user_id: uuid.UUID,
        session: AgentSession,
        active_goal: Goal | None,
        run_id: str,
    ) -> tuple[str, str | None, dict[str, Any] | None, dict[str, Any], list[str]]:
        if not active_goal:
            return ("No active goal selected.", None, None, {}, ["Create a goal."])

        from app.api.v1.goals import get_replanning_diff

        user = await db.get(User, user_id)
        if not user:
            user = User(id=user_id, email="user@lifethread.ai")

        diff_resp = await get_replanning_diff(
            goal_id=active_goal.id,
            current_user=user,
            db=db,
        )

        if not diff_resp.plan_changed:
            v = diff_resp.new_plan.version if diff_resp.new_plan else 1
            return (
                f"**Plan v{v}** for **{active_goal.title}** is currently active on its baseline schedule. No replanning events have altered the tasks.",
                "plan_diff",
                {"plan_changed": False, "version": v, "goal_title": active_goal.title},
                {},
                ["What should I do next?", "I only have one hour today."],
            )

        prev_v = (
            diff_resp.previous_plan.version
            if diff_resp.previous_plan
            else (diff_resp.new_plan.version - 1 if diff_resp.new_plan else 1)
        )
        new_v = diff_resp.new_plan.version if diff_resp.new_plan else 2

        resched = diff_resp.changes.tasks_rescheduled if diff_resp.changes else []
        added = diff_resp.changes.tasks_added if diff_resp.changes else []
        removed = diff_resp.changes.tasks_removed if diff_resp.changes else []
        prios = diff_resp.priority_changes or []

        resched_lines = [
            f"- **{item.title}**: {item.shift_hours:+.1f}h shift ({item.rationale or 'adjusted window'})"
            for item in resched[:5]
        ]
        resched_text = "\n".join(resched_lines) if resched_lines else "None"

        resp_text = (
            f"### Plan Changes for **{active_goal.title}** (Plan v{prev_v} &rarr; Plan v{new_v}):\n\n"
            f"- **Rescheduled Tasks**: {len(resched)}\n"
            f"{resched_text}\n"
            f"- **Added Tasks**: {len(added)}\n"
            f"- **Removed Tasks**: {len(removed)}\n"
            f"- **Priority Changes**: {len(prios)}\n\n"
            f"**Reason**: {diff_resp.reason}\n"
            f"**Explanation**: {diff_resp.why_explanation}"
        )

        card_data = {
            "plan_changed": True,
            "prev_version": prev_v,
            "new_version": new_v,
            "rescheduled_count": len(resched),
            "added_count": len(added),
            "removed_count": len(removed),
            "priority_count": len(prios),
            "goal_title": active_goal.title,
            "reason": diff_resp.reason,
            "why_explanation": diff_resp.why_explanation,
        }

        return (
            resp_text,
            "plan_diff",
            card_data,
            {},
            ["Why did my plan change?", "What should I do next?"],
        )

    # -------------------------------------------------------------------------
    # Handler 4: Why Did My Plan Change
    # -------------------------------------------------------------------------
    @classmethod
    async def _handle_why_plan_changed(
        cls,
        db: AsyncSession,
        user_id: uuid.UUID,
        session: AgentSession,
        active_goal: Goal | None,
        run_id: str,
    ) -> tuple[str, str | None, dict[str, Any] | None, dict[str, Any], list[str]]:
        if not active_goal:
            return ("No active goal selected.", None, None, {}, ["Create a goal."])

        # Retrieve latest plan
        plan_q = (
            select(Plan)
            .where(Plan.goal_id == active_goal.id)
            .order_by(Plan.version.desc())
        )
        plan_res = await db.execute(plan_q)
        latest_plan = plan_res.scalars().first()

        if not latest_plan or latest_plan.version <= 1:
            return (
                f"Your plan for **{active_goal.title}** has not changed. It is operating on the initial baseline Plan v1.",
                None,
                None,
                {},
                ["What should I do next?", "I only have one hour today."],
            )

        meta = latest_plan.metadata_ or {}
        reason = meta.get(
            "replanning_reason",
            meta.get("trigger_reason", latest_plan.reason or "AVAILABLE_TIME_CHANGED"),
        )
        explanation = meta.get(
            "rationale",
            meta.get(
                "explanation_why",
                f"The plan adapted to satisfy schedule constraints and resource capacity without violating your deadline of {active_goal.deadline.strftime('%b %d, %Y') if active_goal.deadline else 'target date'}.",
            ),
        )

        AgentTraceService.record_event(
            run_id=run_id,
            user_id=user_id,
            event_type=ExecutionEventType.EVALUATION,
            status=EventStatus.SUCCESS,
            short_explanation=f"Retrieved replanning rationale for Plan v{latest_plan.version}.",
            goal_id=active_goal.id,
            goal_title=active_goal.title,
            metadata={"reason": reason, "explanation": explanation},
        )

        resp_text = (
            f"### Why Did Your Plan Change? (Plan v{latest_plan.version})\n\n"
            f"**Reason**: `{reason}`\n\n"
            f"**Explanation**: {explanation}\n\n"
            f"The Autonomous Replanning Engine rebalanced your critical path tasks to maintain your target completion date while ensuring realistic execution windows."
        )

        card_data = {
            "version": latest_plan.version,
            "trigger_reason": reason,
            "explanation": explanation,
            "goal_title": active_goal.title,
        }

        return (
            resp_text,
            "replanning_why",
            card_data,
            {},
            ["What changed?", "What should I do next?"],
        )

    # -------------------------------------------------------------------------
    # Handler 5: Capacity Constraint ("I only have one hour today.")
    # -------------------------------------------------------------------------
    @classmethod
    async def _handle_capacity_constraint(
        cls,
        db: AsyncSession,
        user_id: uuid.UUID,
        session: AgentSession,
        active_goal: Goal | None,
        slots: dict[str, Any],
        run_id: str,
    ) -> tuple[str, str | None, dict[str, Any] | None, dict[str, Any], list[str]]:
        if not active_goal:
            return (
                "You don't have an active goal to replan. Say *'Create a goal: Learn Rust in 30 days'* to start!",
                None,
                None,
                {},
                ["Create a goal: Learn Advanced Rust in 30 days"],
            )

        hours = slots.get("hours", 1.0)

        # Trigger real replanning event
        event = ReplanningEvent(
            goal_id=active_goal.id,
            user_id=user_id,
            reason=ReplanningReason.AVAILABLE_TIME_CHANGED,
            description=f"User indicated limited daily availability: {hours:.1f} hour(s) today.",
            details={"daily_available_hours": hours},
        )

        decision = await AutonomousReplanningEngine.process_event(
            db=db,
            event=event,
            commit=True,
        )

        AgentTraceService.record_event(
            run_id=run_id,
            user_id=user_id,
            event_type=ExecutionEventType.TOOL_CALL,
            status=EventStatus.SUCCESS,
            short_explanation=f"Executed Autonomous Replanning Engine for {hours:.1f}h capacity.",
            goal_id=active_goal.id,
            goal_title=active_goal.title,
            tool_name="process_replanning_event",
            tool_parameters={"daily_available_hours": hours, "reason": "AVAILABLE_TIME_CHANGED"},
        )

        new_v = decision.new_plan_version or 2
        resched_count = len(decision.diff.tasks_rescheduled) if decision.diff else 0

        resp_text = (
            f"Understood! I've updated your daily capacity to **{hours:.1f} hour(s)** for **{active_goal.title}**.\n\n"
            f"- **New Plan v{new_v}** committed autonomously\n"
            f"- **Feasibility**: {'Feasible' if decision.is_feasible else 'At risk'}\n"
            f"- **Tasks Rescheduled**: {resched_count} task(s) adjusted to avoid overloading today\n\n"
            f"{decision.explanation}"
        )

        card_data = {
            "hours": hours,
            "new_version": new_v,
            "rescheduled_count": resched_count,
            "rationale": decision.explanation,
            "goal_title": active_goal.title,
        }

        return (
            resp_text,
            "capacity_replan",
            card_data,
            {"plan_version": new_v},
            ["What changed?", "What should I do next?", "Why did my plan change?"],
        )

    # -------------------------------------------------------------------------
    # Handler 6: Remember Fact / Weakness / Preference
    # -------------------------------------------------------------------------
    @classmethod
    async def _handle_remember_fact(
        cls,
        db: AsyncSession,
        user_id: uuid.UUID,
        session: AgentSession,
        active_goal: Goal | None,
        slots: dict[str, Any],
        run_id: str,
    ) -> tuple[str, str | None, dict[str, Any] | None, dict[str, Any], list[str]]:
        fact = slots.get("fact", "")
        category = slots.get("category", "Relevant knowledge")

        if not fact:
            return ("What would you like me to remember?", None, None, {}, [])

        memory_type = (
            MemoryType.PREFERENCE
            if category == "Preference"
            else MemoryType.SEMANTIC
        )

        mem_in = MemoryCreate(
            content=fact,
            memory_type=memory_type,
            confidence=0.95,
            importance_score=0.85,
            source="conversation",
            metadata={
                "category": category,
                "related_goal_id": str(active_goal.id) if active_goal else None,
            },
        )
        mem = await MemoryService.store_memory(db=db, user_id=user_id, create_data=mem_in)

        AgentTraceService.record_event(
            run_id=run_id,
            user_id=user_id,
            event_type=ExecutionEventType.TOOL_CALL,
            status=EventStatus.SUCCESS,
            short_explanation=f"Stored persistent memory: category='{category}', id='{mem.id}'.",
            goal_id=active_goal.id if active_goal else None,
            goal_title=active_goal.title if active_goal else None,
            tool_name="store_memory",
            tool_parameters={"category": category, "content": fact},
        )

        resp_text = (
            f"I have recorded this to your persistent memory under **{category}**:\n\n"
            f"> *\"{fact}\"*\n\n"
            f"Confidence: **95%** &bull; Source: **Conversation**\n\n"
            f"I will factor this into future task scheduling, resource suggestions, and dependency buffers."
        )

        card_data = {
            "memory_id": str(mem.id),
            "content": fact,
            "category": category,
            "confidence": 0.95,
        }

        return (
            resp_text,
            "memory_stored",
            card_data,
            {"memory_id": str(mem.id), "category": category},
            ["What should I do next?", "What is blocking my goal?"],
        )

    # -------------------------------------------------------------------------
    # Handler 7: What is Blocking
    # -------------------------------------------------------------------------
    @classmethod
    async def _handle_what_is_blocking(
        cls,
        db: AsyncSession,
        user_id: uuid.UUID,
        session: AgentSession,
        active_goal: Goal | None,
        run_id: str,
    ) -> tuple[str, str | None, dict[str, Any] | None, dict[str, Any], list[str]]:
        if not active_goal:
            return ("No active goal selected.", None, None, {}, ["Create a goal."])

        # Run real evaluation
        progress_eval = await EvaluationService.evaluate_progress(
            db=db,
            goal_id=active_goal.id,
            user_id=user_id,
        )

        # Retrieve tasks with dependencies to locate blockers
        tasks_q = (
            select(Task)
            .where(Task.goal_id == active_goal.id)
            .options(selectinload(Task.outgoing_dependencies))
        )
        tasks_res = await db.execute(tasks_q)
        tasks = list(tasks_res.scalars().all())
        task_map = {t.id: t for t in tasks}

        blocker_items: list[dict[str, str]] = []
        for t in tasks:
            if t.status in [TaskStatus.COMPLETED, TaskStatus.CANCELLED]:
                continue
            for dep in t.outgoing_dependencies:
                prereq = task_map.get(dep.depends_on_task_id)
                if prereq and prereq.status != TaskStatus.COMPLETED:
                    blocker_items.append({
                        "task_title": t.title,
                        "blocked_by": prereq.title,
                        "prereq_status": prereq.status.value,
                    })

        AgentTraceService.record_event(
            run_id=run_id,
            user_id=user_id,
            event_type=ExecutionEventType.EVALUATION,
            status=EventStatus.SUCCESS,
            short_explanation=f"Evaluated goal blockers: {len(blocker_items)} dependency blocks found.",
            goal_id=active_goal.id,
            goal_title=active_goal.title,
            metadata={"blockers_count": len(blocker_items), "deadline_risk": progress_eval.deadline_risk},
        )

        if blocker_items:
            lines = [
                f"- **{b['task_title']}** is waiting on **{b['blocked_by']}** ({b['prereq_status']})"
                for b in blocker_items[:5]
            ]
            resp_text = (
                f"### Current Blockers for **{active_goal.title}**\n\n"
                f"**Deadline Risk**: `{progress_eval.deadline_risk.upper()}`\n\n"
                f"**Dependency Blockers ({len(blocker_items)})**:\n"
                f"{chr(10).join(lines)}\n\n"
                f"**Recommendation**: {progress_eval.recommended_action}"
            )
        else:
            resp_text = (
                f"### Blocker Diagnostic for **{active_goal.title}**\n\n"
                f"Great news! There are **no blocked tasks** or dependency deadlocks. "
                f"Your execution pipeline is clear.\n\n"
                f"- **Deadline Risk**: `{progress_eval.deadline_risk.upper()}`\n"
                f"- **Next Recommendation**: {progress_eval.recommended_action}"
            )

        card_data = {
            "goal_title": active_goal.title,
            "blockers_count": len(blocker_items),
            "deadline_risk": progress_eval.deadline_risk,
            "recommended_action": progress_eval.recommended_action,
            "blockers": blocker_items,
        }

        return (
            resp_text,
            "blockers_diagnostic",
            card_data,
            {},
            ["What should I do next?", "I only have one hour today."],
        )

    # -------------------------------------------------------------------------
    # Handler 8: Complete Task
    # -------------------------------------------------------------------------
    # -------------------------------------------------------------------------
    # Handler 8: Complete Task
    # -------------------------------------------------------------------------
    @classmethod
    async def _handle_complete_task(
        cls,
        db: AsyncSession,
        user_id: uuid.UUID,
        session: AgentSession,
        active_goal: Goal | None,
        slots: dict[str, Any] | str | None = None,
        run_id: str = "",
    ) -> tuple[str, str | None, dict[str, Any] | None, dict[str, Any], list[str]]:
        if isinstance(slots, str) and not run_id:
            actual_run_id = slots
            slots_dict: dict[str, Any] = {}
        else:
            actual_run_id = run_id
            slots_dict = slots if isinstance(slots, dict) else {}

        target_task = None
        task_hint = slots_dict.get("task_hint")
        if task_hint and active_goal:
            target_task, _ = await ContextResolver.resolve_task(
                db=db,
                user_id=user_id,
                session=session,
                active_goal=active_goal,
                task_hint=task_hint,
            )

        if not target_task and session.current_task_id:
            target_task = await db.get(Task, session.current_task_id)

        if not target_task:
            return (
                "Which task did you complete? You can ask *'What should I do next?'* to review your current task.",
                None,
                None,
                {},
                ["What should I do next?"],
            )

        target_task.status = TaskStatus.COMPLETED
        target_task.completed_at = datetime.now(UTC)
        await db.flush()

        AgentTraceService.record_event(
            run_id=actual_run_id,
            user_id=user_id,
            event_type=ExecutionEventType.STATE_UPDATE,
            status=EventStatus.SUCCESS,
            short_explanation=f"Updated task '{target_task.title}' status to COMPLETED.",
            task_id=target_task.id,
            task_title=target_task.title,
            goal_id=target_task.goal_id,
            goal_title=active_goal.title if active_goal else None,
        )

        completed_title = target_task.title

        # Check next action immediately
        (
            next_resp,
            next_card_type,
            next_card_data,
            state_updates,
            replies,
        ) = await cls._handle_next_action(db, user_id, session, active_goal, actual_run_id)

        resp_text = f"Awesome work! Marked **{completed_title}** as COMPLETED.\n\n{next_resp}"
        return (
            resp_text,
            next_card_type,
            next_card_data,
            {"completed_task_id": str(target_task.id), **state_updates},
            replies,
        )

    # -------------------------------------------------------------------------
    # Handler 9: Switch Goal
    # -------------------------------------------------------------------------
    @classmethod
    async def _handle_switch_goal(
        cls,
        db: AsyncSession,
        user_id: uuid.UUID,
        session: AgentSession,
        slots: dict[str, Any],
        run_id: str,
    ) -> tuple[str, str | None, dict[str, Any] | None, dict[str, Any], list[str]]:
        target = slots.get("target", "").strip().lower()
        goals, _ = await GoalService.list_goals(db, user_id, status_filter=GoalStatus.ACTIVE)
        if not target:
            lines = [f"- {g.title}" for g in goals[:5]]
            return (
                f"Which goal would you like to focus on?\n\n{chr(10).join(lines)}",
                None,
                None,
                {},
                [f"Switch to goal '{g.title}'" for g in goals[:2]],
            )

        matches = [g for g in goals if target in g.title.lower()]
        if not matches:
            return (f"Could not find an active goal matching '{target}'.", None, None, {}, ["What should I do next?"])

        if len(matches) > 1:
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
            session.pending_clarification = ClarificationPrompt(
                clarification_type="AMBIGUOUS_GOAL",
                prompt_message=f"Multiple goals match '{target}'. Which one would you like to focus on?",
                original_intent=AgentIntent.SWITCH_GOAL.value,
                original_slots=slots,
                options=options,
            )
            return (
                f"Multiple goals match '{target}'. Which one would you like to focus on?",
                "clarification_choice",
                {"options": [opt.model_dump() for opt in options]},
                {},
                [opt.label for opt in options],
            )

        matched = matches[0]
        session.active_goal_id = matched.id
        session.active_goal_title = matched.title
        session.current_task_id = None
        session.current_task_title = None

        return (
            f"Switched active focus to goal: **{matched.title}**.",
            None,
            None,
            {"active_goal_id": str(matched.id), "active_goal_title": matched.title},
            ["What should I do next?", "What is blocking my goal?", "What changed?"],
        )

    # -------------------------------------------------------------------------
    # Handler 10: Change Deadline ("Change the deadline to Friday.")
    # -------------------------------------------------------------------------
    @classmethod
    async def _handle_change_deadline(
        cls,
        db: AsyncSession,
        user_id: uuid.UUID,
        session: AgentSession,
        active_goal: Goal | None,
        slots: dict[str, Any],
        run_id: str,
    ) -> tuple[str, str | None, dict[str, Any] | None, dict[str, Any], list[str]]:
        if not active_goal:
            return (
                "You don't have an active goal to update. Say *'Create a goal: Learn Rust in 30 days'* to start!",
                None,
                None,
                {},
                ["Create a goal: Learn Advanced Rust in 30 days"],
            )

        raw_date = slots.get("raw_date", "")
        if not raw_date:
            return (
                f"What deadline should I set for **{active_goal.title}**? You can specify e.g. *'Friday'*, *'tomorrow'*, or a date like *'2026-10-15'*.",
                None,
                None,
                {},
                ["Change deadline to Friday", "Move deadline to tomorrow"],
            )

        new_deadline = DateParser.parse_deadline(raw_date)
        if not new_deadline:
            return (
                f"I couldn't parse '{raw_date}' as a date. Please try e.g. *'Friday'*, *'next Monday'*, or *'2026-10-15'*.",
                None,
                None,
                {},
                ["Change deadline to Friday", "Move deadline to tomorrow"],
            )

        old_deadline = active_goal.deadline
        active_goal.deadline = new_deadline
        await db.flush()

        # Record Tool Call
        AgentTraceService.record_event(
            run_id=run_id,
            user_id=user_id,
            event_type=ExecutionEventType.TOOL_CALL,
            status=EventStatus.SUCCESS,
            short_explanation=f"Updated deadline for '{active_goal.title}' from {old_deadline.strftime('%b %d, %Y') if old_deadline else 'None'} to {new_deadline.strftime('%b %d, %Y')}.",
            goal_id=active_goal.id,
            goal_title=active_goal.title,
            tool_name="update_goal_deadline",
            tool_parameters={"goal_id": str(active_goal.id), "deadline": new_deadline.isoformat()},
        )

        # Trigger Autonomous Replanning Engine if active plan exists
        replan_msg = ""
        try:
            event = ReplanningEvent(
                goal_id=active_goal.id,
                user_id=user_id,
                reason=ReplanningReason.GOAL_DEADLINE_CHANGED,
                description=f"Goal deadline moved to {new_deadline.strftime('%b %d, %Y')}.",
                details={"new_deadline": new_deadline.isoformat()},
            )
            decision = await AutonomousReplanningEngine.process_event(db=db, event=event, commit=True)
            if decision and decision.new_plan_version:
                replan_msg = f"\n\n- **Plan v{decision.new_plan_version}** updated autonomously to align with the new timeline."
        except Exception as e:
            logger.warning("Replanning on deadline change: %s", e)

        date_str = new_deadline.strftime("%A, %b %d, %Y")
        resp_text = (
            f"Successfully updated the deadline for **{active_goal.title}** to **{date_str}**.{replan_msg}\n\n"
            f"Contextual commands will continue operating on **{active_goal.title}**."
        )

        card_data = {
            "goal_id": str(active_goal.id),
            "goal_title": active_goal.title,
            "previous_deadline": old_deadline.isoformat() if old_deadline else None,
            "new_deadline": new_deadline.isoformat(),
            "formatted_date": date_str,
        }

        return (
            resp_text,
            "deadline_updated",
            card_data,
            {"active_goal_id": str(active_goal.id), "deadline": new_deadline.isoformat()},
            ["What should I do next?", "What changed?", "What is blocking my goal?"],
        )

    # -------------------------------------------------------------------------
    # Handler 11: Update Priority ("Make it critical")
    # -------------------------------------------------------------------------
    @classmethod
    async def _handle_update_priority(
        cls,
        db: AsyncSession,
        user_id: uuid.UUID,
        session: AgentSession,
        active_goal: Goal | None,
        slots: dict[str, Any],
        run_id: str,
    ) -> tuple[str, str | None, dict[str, Any] | None, dict[str, Any], list[str]]:
        prio_str = slots.get("priority", "HIGH")
        prio_enum = GoalPriority(prio_str)
        target_type = slots.get("target_type", "goal")

        if target_type == "task" and session.current_task_id:
            task = await db.get(Task, session.current_task_id)
            if task:
                task.priority = prio_enum
                await db.flush()
                return (
                    f"Updated priority of task **{task.title}** to **{prio_enum.value}**.",
                    "task_priority_updated",
                    {"task_id": str(task.id), "title": task.title, "priority": prio_enum.value},
                    {"current_task_priority": prio_enum.value},
                    ["What should I do next?", "Status"],
                )

        if not active_goal:
            return ("No active goal to update priority for.", None, None, {}, ["What should I do next?"])

        active_goal.priority = prio_enum
        await db.flush()

        AgentTraceService.record_event(
            run_id=run_id,
            user_id=user_id,
            event_type=ExecutionEventType.STATE_UPDATE,
            status=EventStatus.SUCCESS,
            short_explanation=f"Updated goal '{active_goal.title}' priority to {prio_enum.value}.",
            goal_id=active_goal.id,
            goal_title=active_goal.title,
        )

        return (
            f"Updated priority of goal **{active_goal.title}** to **{prio_enum.value}**.",
            "goal_priority_updated",
            {"goal_id": str(active_goal.id), "title": active_goal.title, "priority": prio_enum.value},
            {"active_goal_priority": prio_enum.value},
            ["What should I do next?", "What changed?"],
        )

    # -------------------------------------------------------------------------
    # Handler 12: Milestone Query ("What is the current milestone?")
    # -------------------------------------------------------------------------
    @classmethod
    async def _handle_milestone_query(
        cls,
        db: AsyncSession,
        user_id: uuid.UUID,
        session: AgentSession,
        active_goal: Goal | None,
        slots: dict[str, Any],
        run_id: str,
    ) -> tuple[str, str | None, dict[str, Any] | None, dict[str, Any], list[str]]:
        if not active_goal:
            return (
                "You don't have an active goal selected. Say *'Create a goal: Learn Rust in 30 days'* to start!",
                None,
                None,
                {},
                ["Create a goal: Learn Advanced Rust in 30 days"],
            )

        milestone_hint = slots.get("milestone_hint")
        active_m, all_m = await ContextResolver.resolve_milestone(db, user_id, session, active_goal, milestone_hint)

        if not all_m:
            return (
                f"Goal **{active_goal.title}** currently has no defined milestones.",
                None,
                None,
                {},
                ["What should I do next?"],
            )

        lines = [
            f"- **{m.title}** ({m.status.value})" + (" &larr; *Active*" if active_m and m.id == active_m.id else "")
            for m in all_m
        ]
        resp_text = (
            f"### Milestones for **{active_goal.title}**\n\n"
            f"{chr(10).join(lines)}\n\n"
            f"Current milestone: **{active_m.title if active_m else all_m[0].title}**"
        )
        card_data = {
            "goal_title": active_goal.title,
            "active_milestone_id": str(active_m.id) if active_m else None,
            "active_milestone_title": active_m.title if active_m else None,
            "milestones": [{"id": str(m.id), "title": m.title, "status": m.status.value} for m in all_m],
        }
        return (
            resp_text,
            "milestones_view",
            card_data,
            {"active_milestone_title": active_m.title if active_m else None},
            ["What should I do next?", "What is blocking my goal?"],
        )

    # -------------------------------------------------------------------------
    # Handler 13: Memory Query ("What do you remember?")
    # -------------------------------------------------------------------------
    @classmethod
    async def _handle_memory_query(
        cls,
        db: AsyncSession,
        user_id: uuid.UUID,
        session: AgentSession,
        run_id: str,
    ) -> tuple[str, str | None, dict[str, Any] | None, dict[str, Any], list[str]]:
        mem_q = (
            select(Memory)
            .where(Memory.user_id == user_id, Memory.status == MemoryStatus.ACTIVE)
            .order_by(Memory.created_at.desc())
            .limit(10)
        )
        res = await db.execute(mem_q)
        memories = list(res.scalars().all())

        if not memories:
            return (
                "I haven't recorded any memories for you yet. You can tell me e.g. *\"Remember that I struggle with SQL joins.\"*",
                None,
                None,
                {},
                ["Remember that I struggle with SQL joins."],
            )

        AgentTraceService.record_retrieved_memories(
            run_id=run_id,
            user_id=user_id,
            memories=[
                {
                    "id": str(m.id),
                    "content": m.content,
                    "category": m.metadata_json.get("category", m.memory_type.value),
                    "confidence": m.confidence,
                }
                for m in memories
            ],
            query="user active memories",
            rationale="Retrieved active memories for conversational query.",
        )

        session.last_referenced_memory_id = memories[0].id

        lines = [
            f"- **[{m.metadata_json.get('category', m.memory_type.value)}]**: \"{m.content}\""
            for m in memories
        ]
        resp_text = (
            f"### What I Remember About You ({len(memories)} items)\n\n"
            f"{chr(10).join(lines)}\n\n"
            f"These memories are applied autonomously to your plan generation and task scheduling."
        )
        card_data = {
            "count": len(memories),
            "memories": [
                {"id": str(m.id), "content": m.content, "category": m.metadata_json.get("category", m.memory_type.value)}
                for m in memories
            ],
        }
        return (
            resp_text,
            "memories_view",
            card_data,
            {"last_referenced_memory_id": str(memories[0].id)},
            ["What should I do next?", "Status"],
        )

    # -------------------------------------------------------------------------
    # Context Summary
    # -------------------------------------------------------------------------
    @classmethod
    async def get_context_summary(
        cls,
        db: AsyncSession,
        user_id: uuid.UUID,
        user_name: str,
        session_id: str | None = None,
    ) -> ConversationContextSummary:
        """Produce real-time context summary showing active goal, current task, milestone, and user memories."""
        session = cls.get_or_create_session(user_id=user_id, session_id=session_id)
        active_goal = await cls._resolve_active_goal(db, user_id, session)

        # Count active goals
        goals_q = select(Goal).where(Goal.user_id == user_id, Goal.status == GoalStatus.ACTIVE)
        goals_res = await db.execute(goals_q)
        active_goals = list(goals_res.scalars().all())

        # Count memories
        mem_q = select(Memory).where(Memory.user_id == user_id, Memory.status == MemoryStatus.ACTIVE)
        mem_res = await db.execute(mem_q)
        memories = list(mem_res.scalars().all())

        learned_weaknesses = sum(
            1 for m in memories if m.metadata_json.get("category") == "Learned weakness"
        )
        preferences = sum(
            1 for m in memories if m.memory_type == MemoryType.PREFERENCE or m.metadata_json.get("category") == "Preference"
        )

        recent_intents = [
            m.intent.value for m in session.messages if m.intent and m.intent != AgentIntent.UNKNOWN
        ][-5:]

        return ConversationContextSummary(
            session_id=session.session_id,
            user_id=user_id,
            user_name=user_name,
            active_goal_id=active_goal.id if active_goal else None,
            active_goal_title=active_goal.title if active_goal else None,
            active_goal_status=active_goal.status.value if active_goal else None,
            current_task_id=session.current_task_id,
            current_task_title=session.current_task_title,
            active_milestone_id=session.active_milestone_id,
            active_milestone_title=session.active_milestone_title,
            last_referenced_memory_id=session.last_referenced_memory_id,
            pending_clarification=session.pending_clarification,
            active_goals_count=len(active_goals),
            total_memories_count=len(memories),
            learned_weaknesses_count=learned_weaknesses,
            preferences_count=preferences,
            recent_intents=recent_intents,
        )
