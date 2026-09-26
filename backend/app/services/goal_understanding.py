import json
import logging
import re
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import status
from pydantic import BaseModel, Field

from app.core.exceptions import LifeThreadException
from app.db.models.goal import GoalPriority
from app.schemas.goal_understanding import (
    AmbiguityReport,
    GoalConstraintDraft,
    GoalMilestoneDraft,
    GoalStructuredSpecification,
    GoalUnderstandingSchema,
)
from app.services.goal_clarification import GoalClarificationService
from app.services.llm import BaseLLMProvider, LLMMessage, get_llm_provider

logger = logging.getLogger("lifethread.services.goal_understanding")


class _LLMGoalExtractionPayload(BaseModel):
    """Internal model for validating structured output from the LLM."""

    title: str = Field(..., min_length=1)
    objective: str = Field(..., min_length=1)
    description: str | None = None
    deadline: str | None = None
    priority: str = "medium"
    constraints: list[dict[str, Any]] = Field(default_factory=list)
    success_criteria: list[str] = Field(default_factory=list)
    milestones: list[dict[str, Any]] = Field(default_factory=list)
    is_ambiguous: bool = False
    missing_information: list[str] = Field(default_factory=list)
    clarification_questions: list[str] = Field(default_factory=list)
    confidence_score: float = 1.0


class GoalUnderstandingService:
    """Core domain service for interpreting natural language goals into validated specifications."""

    SYSTEM_PROMPT = """You are the LifeThread Goal Understanding Engine.
Your task is to convert the user's natural language goal into a validated, structured specification.

STRICT RULES:
1. Output MUST be a single, valid JSON object with NO commentary, preamble, or markdown surrounding text.
2. NEVER invent, hallucinate, or assume constraints. Only extract constraints explicitly stated by the user (e.g. time limits, budget caps, tool limitations). If none are stated, return an empty array [].
3. For deadlines, compute the normalized UTC timestamp using the provided Reference Time and User Timezone. If the user gives a relative timeframe (e.g., 'in 10 days', 'by next Friday'), calculate the exact date/time in ISO 8601 format. If no timeframe is mentioned, return null.
4. Extract 2-5 concrete, measurable success criteria that define when this objective is satisfied.
5. If the goal is vague, ambiguous, or lacks critical scope, set `is_ambiguous` to true, list `missing_information`, and generate 1-3 targeted `clarification_questions`.
6. Set `priority` to one of: 'low', 'medium', 'high', 'critical'.

Expected JSON Schema:
{
  "title": "Concise, meaningful goal title (<= 10 words)",
  "objective": "Clear target objective or mission statement",
  "description": "Optional elaborated context or null",
  "deadline": "2026-10-04T12:00:00Z" (or null),
  "priority": "medium",
  "constraints": [
    {"type": "time", "value": "10 days", "metadata": {}}
  ],
  "success_criteria": [
    "Complete mock interview scoring >= 85%",
    "Solve 30 advanced AI system design practice questions"
  ],
  "milestones": [
    {"title": "Review Core Concepts", "description": null, "deadline": null}
  ],
  "is_ambiguous": false,
  "missing_information": [],
  "clarification_questions": [],
  "confidence_score": 0.95
}
"""

    @classmethod
    async def understand_goal(
        cls,
        raw_text: str,
        user_timezone: str = "UTC",
        reference_time: datetime | None = None,
        clarification_answers: dict[str, str] | None = None,
        llm_provider: BaseLLMProvider | None = None,
    ) -> GoalUnderstandingSchema:
        """Interpret a natural language goal statement into a validated structured goal specification."""
        provider = llm_provider or get_llm_provider()

        # Establish deterministic reference time and user timezone
        ref_time_utc = reference_time or datetime.now(UTC)
        if ref_time_utc.tzinfo is None:
            ref_time_utc = ref_time_utc.replace(tzinfo=UTC)

        try:
            tz = ZoneInfo(user_timezone)
        except (ZoneInfoNotFoundError, ValueError):
            logger.warning(f"Invalid timezone '{user_timezone}' provided, falling back to UTC")
            tz = ZoneInfo("UTC")
            user_timezone = "UTC"

        ref_time_user = ref_time_utc.astimezone(tz)

        # Build prompt messages
        prompt_content = f"""Current Reference Time (UTC): {ref_time_utc.isoformat()}
User Timezone: {user_timezone}
Current Reference Time in User Timezone: {ref_time_user.isoformat()}

User Goal Request:
"{raw_text}"
"""
        if clarification_answers:
            prompt_content += f"\nUser Answers to Previous Clarifications:\n{json.dumps(clarification_answers, indent=2)}\n"

        messages = [
            LLMMessage(role="system", content=cls.SYSTEM_PROMPT),
            LLMMessage(role="user", content=prompt_content),
        ]

        logger.info(
            f"Calling LLM provider '{getattr(provider, 'default_model', 'default')}' for goal understanding"
        )
        response = await provider.chat(messages=messages, temperature=0.2)

        # Parse and validate LLM output safely
        extraction_data = cls._parse_and_validate_llm_response(response.content)

        # Normalize deadline with timezone
        normalized_deadline = cls._normalize_deadline(
            deadline_str=extraction_data.deadline,
            raw_text=raw_text,
            ref_time_utc=ref_time_utc,
            user_tz=tz,
        )

        # Transform constraints into validated draft objects
        validated_constraints: list[GoalConstraintDraft] = []
        for c in extraction_data.constraints:
            if isinstance(c, dict) and "type" in c and "value" in c:
                validated_constraints.append(
                    GoalConstraintDraft(
                        type=str(c["type"]).strip(),
                        value=str(c["value"]).strip(),
                        metadata=c.get("metadata", {})
                        if isinstance(c.get("metadata"), dict)
                        else {},
                    )
                )

        # Transform milestones
        validated_milestones: list[GoalMilestoneDraft] = []
        for m in extraction_data.milestones:
            if isinstance(m, dict) and "title" in m:
                m_deadline = None
                if m.get("deadline"):
                    m_deadline = cls._parse_iso_datetime(str(m["deadline"]), tz)
                validated_milestones.append(
                    GoalMilestoneDraft(
                        title=str(m["title"]).strip(),
                        description=m.get("description"),
                        deadline=m_deadline,
                    )
                )

        # Build ambiguity report from LLM output
        llm_ambiguity_report = AmbiguityReport(
            is_ambiguous=extraction_data.is_ambiguous,
            missing_information=extraction_data.missing_information,
            clarification_questions=extraction_data.clarification_questions,
            confidence_score=extraction_data.confidence_score,
        )

        # Run GoalClarificationService evaluation to enforce ambiguity detection rules
        final_ambiguity = GoalClarificationService.evaluate(
            raw_text=raw_text,
            objective=extraction_data.objective,
            deadline=normalized_deadline,
            constraints=validated_constraints,
            success_criteria=extraction_data.success_criteria,
            llm_ambiguity_report=llm_ambiguity_report,
            clarification_answers=clarification_answers,
        )

        # Normalize priority
        priority_val = cls._normalize_priority_str(extraction_data.priority)

        # Create structured interpretation specification
        structured_spec = GoalStructuredSpecification(
            title=extraction_data.title.strip(),
            objective=extraction_data.objective.strip(),
            description=extraction_data.description,
            deadline=normalized_deadline,
            priority=priority_val,
            constraints=validated_constraints,
            success_criteria=extraction_data.success_criteria,
            milestones=validated_milestones,
        )

        # Return complete schema storing raw_request separately from structured_interpretation
        return GoalUnderstandingSchema(
            raw_request=raw_text,
            objective=structured_spec.objective,
            title=structured_spec.title,
            description=structured_spec.description,
            deadline=structured_spec.deadline,
            priority=structured_spec.priority,
            constraints=structured_spec.constraints,
            success_criteria=structured_spec.success_criteria,
            milestones=structured_spec.milestones,
            is_ambiguous=final_ambiguity.is_ambiguous,
            missing_information=final_ambiguity.missing_information,
            clarification_questions=final_ambiguity.clarification_questions,
            needs_clarification=final_ambiguity.is_ambiguous
            or bool(final_ambiguity.clarification_questions),
            confidence_score=final_ambiguity.confidence_score,
            structured_interpretation=structured_spec,
        )

    @classmethod
    def _parse_and_validate_llm_response(cls, raw_content: str) -> _LLMGoalExtractionPayload:
        """Clean markdown wrapping, parse JSON, and validate against internal Pydantic schema."""
        if not raw_content or not raw_content.strip():
            raise LifeThreadException(
                message="Malformed LLM response: Empty completion received from model",
                code="MALFORMED_LLM_OUTPUT",
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                details={"raw_content": raw_content},
            )

        # Strip markdown code blocks if model wrapped output in ```json ... ```
        cleaned = raw_content.strip()
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s*```$", "", cleaned)
        cleaned = cleaned.strip()

        # Find outer-most JSON object if extraneous text is present
        start_idx = cleaned.find("{")
        end_idx = cleaned.rfind("}")
        if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
            cleaned = cleaned[start_idx : end_idx + 1]

        try:
            parsed_json = json.loads(cleaned)
        except json.JSONDecodeError as exc:
            logger.warning(f"Failed to decode LLM JSON: {exc} | Content: {raw_content[:200]}")
            raise LifeThreadException(
                message="Malformed LLM response: Invalid JSON returned by language model",
                code="MALFORMED_LLM_OUTPUT",
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                details={"decode_error": str(exc), "raw_content": raw_content},
            ) from exc

        try:
            return _LLMGoalExtractionPayload.model_validate(parsed_json)
        except Exception as exc:
            logger.warning(f"Schema mismatch on LLM output: {exc}")
            raise LifeThreadException(
                message="Malformed LLM response: Schema validation failed",
                code="MALFORMED_LLM_OUTPUT",
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                details={"validation_error": str(exc)},
            ) from exc

    @classmethod
    def _normalize_deadline(
        cls,
        deadline_str: str | None,
        raw_text: str,
        ref_time_utc: datetime,
        user_tz: ZoneInfo,
    ) -> datetime | None:
        """Parse and normalize date strings to UTC, accounting for relative day expressions and timezone."""
        if deadline_str and deadline_str.strip():
            parsed = cls._parse_iso_datetime(deadline_str.strip(), user_tz)
            if parsed is not None:
                return parsed

        # Regex fallback for explicit relative time expressions like "in 10 days"
        relative_match = re.search(r"\bin\s+(\d+)\s+days?\b", raw_text, re.IGNORECASE)
        if relative_match:
            days = int(relative_match.group(1))
            user_local_target = ref_time_utc.astimezone(user_tz) + timedelta(days=days)
            return user_local_target.astimezone(UTC)

        return None

    @classmethod
    def _parse_iso_datetime(cls, dt_str: str, user_tz: ZoneInfo) -> datetime | None:
        """Safely parse an ISO datetime string and convert to timezone-aware UTC datetime."""
        try:
            dt = datetime.fromisoformat(dt_str)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=user_tz)
            return dt.astimezone(UTC)
        except Exception:
            return None

    @classmethod
    def _normalize_priority_str(cls, p: str) -> str:
        """Normalize priority strings to canonical lowercase values."""
        clean = p.strip().lower()
        if clean in {GoalPriority.LOW.value.lower(), "low"}:
            return "low"
        if clean in {GoalPriority.HIGH.value.lower(), "high"}:
            return "high"
        if clean in {GoalPriority.CRITICAL.value.lower(), "critical"}:
            return "critical"
        return "medium"
