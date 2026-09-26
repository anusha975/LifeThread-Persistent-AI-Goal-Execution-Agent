import asyncio
import json
import logging
import uuid
from abc import ABC, abstractmethod
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.services.aws.config import AWSConfigManager
from app.services.skills.models import SkillExecutionContext
from app.services.skills.registry import SkillRegistry

logger = logging.getLogger("lifethread.aws.agent_core")


class AgentCoreActionRequest(BaseModel):
    """Normalized request payload for an AgentCore action group execution."""

    model_config = ConfigDict(from_attributes=True)

    action_group: str = Field(..., description="Action group or skill category name")
    action_name: str = Field(..., description="Specific action or skill name (e.g. goal_management, planning)")
    parameters: dict[str, Any] = Field(default_factory=dict, description="Action arguments")
    session_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    user_id: uuid.UUID
    goal_id: uuid.UUID | None = None


class AgentCoreTraceStep(BaseModel):
    """Normalized trace step emitted during AgentCore reasoning and action execution."""

    step_type: str = Field(..., description="OBSERVATION, ACTION_CALL, ACTION_RESULT, or RATIONALE")
    description: str
    action_group: str | None = None
    action_name: str | None = None
    output_payload: dict[str, Any] | None = None
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))


class AgentCoreResponse(BaseModel):
    """Normalized response from AgentCore execution."""

    model_config = ConfigDict(from_attributes=True)

    session_id: str
    output_text: str
    action_group: str
    action_name: str
    success: bool
    data: dict[str, Any] = Field(default_factory=dict)
    trace_steps: list[AgentCoreTraceStep] = Field(default_factory=list)
    provider: str
    error: str | None = None


class BaseAgentCoreProvider(ABC):
    """Abstract provider abstraction for AgentCore orchestration and action group dispatch."""

    @abstractmethod
    async def execute_action(
        self,
        request: AgentCoreActionRequest,
        db: AsyncSession,
        user_permissions: list[str] | None = None,
    ) -> AgentCoreResponse:
        """Execute a structured action group request."""
        pass


class LocalAgentCoreProvider(BaseAgentCoreProvider):
    """Local provider adapter using LifeThread's native SkillRegistry.

    Ensures full offline operation, zero cloud cost, and instant testing.
    """

    async def execute_action(
        self,
        request: AgentCoreActionRequest,
        db: AsyncSession,
        user_permissions: list[str] | None = None,
    ) -> AgentCoreResponse:
        trace_steps: list[AgentCoreTraceStep] = []
        action_name = request.action_name.lower()

        trace_steps.append(
            AgentCoreTraceStep(
                step_type="RATIONALE",
                description=f"LocalAgentCore selected skill '{action_name}' for action group '{request.action_group}'.",
                action_group=request.action_group,
                action_name=action_name,
            )
        )

        trace_steps.append(
            AgentCoreTraceStep(
                step_type="ACTION_CALL",
                description=f"Dispatching action '{action_name}' with parameters {json.dumps(request.parameters)}.",
                action_group=request.action_group,
                action_name=action_name,
            )
        )

        context = SkillExecutionContext(
            db=db,
            user_id=request.user_id,
            goal_id=request.goal_id,
            session_id=request.session_id,
            user_permissions=set(user_permissions or ["*"]),
        )

        result = await SkillRegistry.execute_skill(
            skill_name=action_name,
            context=context,
            inputs=request.parameters,
        )

        trace_steps.append(
            AgentCoreTraceStep(
                step_type="ACTION_RESULT",
                description=f"Action '{action_name}' completed with success={result.success}.",
                action_group=request.action_group,
                action_name=action_name,
                output_payload=result.data,
            )
        )

        return AgentCoreResponse(
            session_id=request.session_id,
            output_text=result.data.get("message", f"Action {action_name} executed successfully.") if result.data else (result.error or "Action completed."),
            action_group=request.action_group,
            action_name=action_name,
            success=result.success,
            data=result.data,
            trace_steps=trace_steps,
            provider="local-agentcore",
            error=result.error,
        )


class BedrockAgentCoreProvider(BaseAgentCoreProvider):
    """AWS Bedrock Agent runtime adapter for AgentCore.

    Connects to Amazon Bedrock Agent runtime when AWS_AGENTCORE_AGENT_ID is configured,
    and falls back to LocalAgentCoreProvider on failures or missing credentials.
    """

    def __init__(
        self,
        agent_id: str | None = None,
        agent_alias_id: str | None = None,
        fallback_provider: BaseAgentCoreProvider | None = None,
    ) -> None:
        settings = get_settings()
        self.agent_id = agent_id or settings.AWS_AGENTCORE_AGENT_ID
        self.agent_alias_id = agent_alias_id or settings.AWS_AGENTCORE_AGENT_ALIAS_ID or "TSTALIASID"
        self.fallback = fallback_provider or LocalAgentCoreProvider()

    async def execute_action(
        self,
        request: AgentCoreActionRequest,
        db: AsyncSession,
        user_permissions: list[str] | None = None,
    ) -> AgentCoreResponse:
        # Check prerequisites
        if not self.agent_id or not AWSConfigManager.is_aws_available():
            logger.info("Bedrock Agent ID or credentials unconfigured; delegating to LocalAgentCoreProvider.")
            return await self.fallback.execute_action(request, db, user_permissions)

        try:
            client = AWSConfigManager.get_client("bedrock-agent-runtime")
            # Invoke Bedrock Agent Runtime
            response = await asyncio.to_thread(
                client.invoke_agent,
                agentId=self.agent_id,
                agentAliasId=self.agent_alias_id,
                sessionId=request.session_id,
                inputText=json.dumps({
                    "actionGroup": request.action_group,
                    "action": request.action_name,
                    "parameters": request.parameters,
                }),
            )

            # Consume event stream
            event_stream = response.get("completion", [])
            completion_text = ""
            trace_steps: list[AgentCoreTraceStep] = []

            for event in event_stream:
                if "chunk" in event:
                    chunk = event["chunk"]
                    completion_text += chunk.get("bytes", b"").decode("utf-8")
                if "trace" in event:
                    tr = event["trace"].get("trace", {})
                    trace_steps.append(
                        AgentCoreTraceStep(
                            step_type="OBSERVATION",
                            description=str(tr.get("orchestrationTrace", "Trace observation")),
                            action_group=request.action_group,
                            action_name=request.action_name,
                        )
                    )

            return AgentCoreResponse(
                session_id=request.session_id,
                output_text=completion_text or "AgentCore invocation succeeded.",
                action_group=request.action_group,
                action_name=request.action_name,
                success=True,
                data={"raw_output": completion_text},
                trace_steps=trace_steps,
                provider="aws-bedrock-agentcore",
            )

        except Exception as e:
            logger.warning("Bedrock AgentCore invocation failed (%s); falling back to LocalAgentCoreProvider.", e)
            fallback_res = await self.fallback.execute_action(request, db, user_permissions)
            fallback_res.trace_steps.insert(
                0,
                AgentCoreTraceStep(
                    step_type="RATIONALE",
                    description=f"Bedrock AgentCore failed ({e}); gracefully fell back to LocalAgentCore.",
                ),
            )
            return fallback_res


def get_agent_core_provider() -> BaseAgentCoreProvider:
    """Factory helper to obtain the configured AgentCore provider instance."""
    settings = get_settings()
    local_provider = LocalAgentCoreProvider()
    if settings.AWS_AGENTCORE_AGENT_ID and AWSConfigManager.is_aws_available():
        return BedrockAgentCoreProvider(fallback_provider=local_provider)
    return local_provider
