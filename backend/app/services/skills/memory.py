import uuid
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from app.db.models.memory import Memory, MemoryStatus, MemoryType
from app.schemas.memory import MemoryCreate
from app.services.agent_trace.models import EventStatus, ExecutionEventType
from app.services.agent_trace.service import AgentTraceService
from app.services.memory import MemoryService
from app.services.skills.base import AgentSkill
from app.services.skills.models import FailureBehavior, SkillCategory, SkillExecutionContext


class MemoryInputs(BaseModel):
    """Input contract for MemorySkill."""

    model_config = ConfigDict(from_attributes=True)

    action: Literal["store", "retrieve", "list", "delete"] = Field(
        ..., description="Memory operation to execute"
    )
    content: str | None = Field(default=None, description="Memory text content to record")
    category: str | None = Field(
        default=None, description="Category: 'Preference', 'Learned weakness', 'Relevant knowledge'"
    )
    memory_type: MemoryType = Field(default=MemoryType.SEMANTIC, description="Underlying memory type")
    query: str | None = Field(default=None, description="Search query for relevant memory retrieval")
    goal_id: uuid.UUID | None = Field(default=None, description="Related goal ID")
    memory_id: uuid.UUID | None = Field(default=None, description="Target memory ID for deletion or lookup")
    limit: int = Field(default=10, ge=1, le=50, description="Max memories to return")


class MemoryOutputs(BaseModel):
    """Output contract for MemorySkill."""

    model_config = ConfigDict(from_attributes=True)

    action: str
    memory_id: str | None = None
    content: str | None = None
    category: str | None = None
    count: int = 0
    memories: list[dict[str, Any]] = Field(default_factory=list)
    message: str


class MemorySkill(AgentSkill):
    """Reusable skill for persisting, categorizing, retrieving, and managing user memories."""

    name = "memory"
    purpose = "Persists, categorizes, retrieves, and maintains user context, preferences, and learned weaknesses across agent sessions."
    category = SkillCategory.MEMORY
    inputs_model = MemoryInputs
    outputs_model = MemoryOutputs
    required_permissions = ["memory:read", "memory:write"]
    tools = [
        "MemoryService.store_memory",
        "MemoryService.retrieve_relevant_memories",
        "MemoryService.list_memories",
        "MemoryService.delete_memory",
    ]
    failure_behavior = FailureBehavior.GRACEFUL_DEGRADATION

    async def _execute_internal(
        self,
        context: SkillExecutionContext,
        inputs: MemoryInputs,
    ) -> MemoryOutputs:
        db = context.db
        user_id = context.user_id
        run_id = context.run_id or ""

        if inputs.action == "store":
            if not inputs.content:
                raise ValueError("content is required for 'store' action")

            category = inputs.category or "Relevant knowledge"
            mem_type = MemoryType.PREFERENCE if category == "Preference" else inputs.memory_type

            mem_in = MemoryCreate(
                content=inputs.content,
                memory_type=mem_type,
                confidence=0.95,
                importance_score=0.85,
                source="skill:memory",
                metadata={
                    "category": category,
                    "related_goal_id": str(inputs.goal_id) if inputs.goal_id else None,
                },
            )
            mem = await MemoryService.store_memory(db=db, user_id=user_id, create_data=mem_in)

            AgentTraceService.record_event(
                run_id=run_id,
                user_id=user_id,
                event_type=ExecutionEventType.TOOL_CALL,
                status=EventStatus.SUCCESS,
                short_explanation=f"Stored memory under category '{category}'.",
                tool_name="MemoryService.store_memory",
                tool_parameters={"category": category, "memory_id": str(mem.id)},
            )

            return MemoryOutputs(
                action="store",
                memory_id=str(mem.id),
                content=mem.content,
                category=category,
                count=1,
                message=f"Recorded memory under '{category}'.",
            )

        elif inputs.action == "retrieve" or inputs.action == "list":
            # Retrieve active memories
            stmt = (
                select(Memory)
                .where(Memory.user_id == user_id, Memory.status == MemoryStatus.ACTIVE)
                .order_by(Memory.created_at.desc())
                .limit(inputs.limit)
            )
            res = await db.execute(stmt)
            memories = list(res.scalars().all())

            # Optional query filtering
            if inputs.query:
                q_lower = inputs.query.lower()
                memories = [m for m in memories if q_lower in m.content.lower()]

            mem_list = [
                {
                    "id": str(m.id),
                    "content": m.content,
                    "category": m.metadata_json.get("category", m.memory_type.value),
                    "confidence": m.confidence,
                    "created_at": m.created_at.isoformat() if m.created_at else None,
                }
                for m in memories
            ]

            return MemoryOutputs(
                action=inputs.action,
                count=len(mem_list),
                memories=mem_list,
                message=f"Retrieved {len(mem_list)} memories for user.",
            )

        elif inputs.action == "delete":
            if not inputs.memory_id:
                raise ValueError("memory_id required for 'delete' action")

            deleted = await MemoryService.delete_memory(db=db, memory_id=inputs.memory_id, user_id=user_id)
            if not deleted:
                raise ValueError(f"Memory '{inputs.memory_id}' not found or already deleted")

            return MemoryOutputs(
                action="delete",
                memory_id=str(inputs.memory_id),
                count=1,
                message=f"Deleted memory '{inputs.memory_id}'.",
            )

        raise ValueError(f"Unsupported memory action: {inputs.action}")

    async def _graceful_degrade(
        self,
        context: SkillExecutionContext,
        inputs: MemoryInputs,
        exc: Exception,
    ) -> dict[str, Any]:
        """Degrade gracefully to empty memory state without crashing pipeline."""
        return {
            "action": inputs.action,
            "count": 0,
            "memories": [],
            "message": f"Memory service temporarily degraded: {str(exc)}",
            "degraded": True,
        }
