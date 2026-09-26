import logging
import re
import time
from typing import Any

from app.services.skills.base import AgentSkill
from app.services.skills.evaluation import EvaluationSkill
from app.services.skills.goal_management import GoalManagementSkill
from app.services.skills.memory import MemorySkill
from app.services.skills.models import (
    SkillExecutionContext,
    SkillMetadata,
    SkillPipelineRequest,
    SkillPipelineResult,
    SkillResult,
)
from app.services.skills.planning import PlanningSkill
from app.services.skills.replanning import ReplanningSkill

logger = logging.getLogger("lifethread.services.skills.registry")


class SkillRegistry:
    """Central registry and dispatch manager for all LifeThread Agent Skills."""

    _skills: dict[str, AgentSkill] = {}
    _initialized: bool = False

    @classmethod
    def register_skill(cls, skill: AgentSkill) -> None:
        """Register an agent skill in the catalog."""
        cls._skills[skill.name] = skill
        logger.debug("Registered agent skill '%s' (%s)", skill.name, skill.category.value)

    @classmethod
    def initialize_default_skills(cls) -> None:
        """Register the 5 canonical LifeThread domain skills."""
        if cls._initialized:
            return

        cls.register_skill(GoalManagementSkill())
        cls.register_skill(PlanningSkill())
        cls.register_skill(MemorySkill())
        cls.register_skill(EvaluationSkill())
        cls.register_skill(ReplanningSkill())
        cls._initialized = True
        logger.info("Initialized %d canonical agent skills.", len(cls._skills))

    @classmethod
    def get_skill(cls, name: str) -> AgentSkill | None:
        """Retrieve a registered skill by exact name."""
        cls.initialize_default_skills()
        return cls._skills.get(name)

    @classmethod
    def list_skills(cls) -> list[AgentSkill]:
        """List all discovered agent skills."""
        cls.initialize_default_skills()
        return list(cls._skills.values())

    @classmethod
    def list_skill_metadata(cls) -> list[SkillMetadata]:
        """Return introspective metadata for all discovered skills."""
        cls.initialize_default_skills()
        return [skill.get_metadata() for skill in cls._skills.values()]

    @classmethod
    def select_skill(
        cls,
        request_text: str,
        context: dict[str, Any] | None = None,
    ) -> AgentSkill | None:
        """Analyze user request and select the most appropriate agent skill.

        Deterministic rule-based keyword & intent scoring.
        """
        cls.initialize_default_skills()
        lower = request_text.strip().lower()

        # 1. Replanning Skill
        if re.search(
            r"\b(only have|limited to|capacity|replan|rebalance|reschedule plan|reschedule tasks|too much work)\b",
            lower,
        ) and any(w in lower for w in ["hour", "minute", "hr", "plan", "time"]):
            return cls._skills.get("replanning")

        # 2. Evaluation Skill
        if re.search(
            r"\b(what should i do next|what to do next|next action|next task|what is blocking|blockers|progress|how am i doing|velocity|risk)\b",
            lower,
        ):
            return cls._skills.get("evaluation")

        # 3. Planning Skill
        if re.search(
            r"\b(decompose|generate plan|create plan|make a plan|schedule tasks|build schedule|milestones for)\b",
            lower,
        ):
            return cls._skills.get("planning")

        # 4. Memory Skill
        if re.search(
            r"\b(remember that|remember i|remember my|remember:|don\'t forget|what do you remember|show memories|my weaknesses|my preferences)\b",
            lower,
        ):
            return cls._skills.get("memory")

        # 5. Goal Management Skill
        if re.search(
            r"\b(create a goal|new goal|start a goal|change the deadline|move deadline|update deadline|switch goal|switch to goal|make it critical|priority to|focus on goal)\b",
            lower,
        ):
            return cls._skills.get("goal_management")

        # Contextual fallback based on context dict
        if context:
            if "goal_id" in context and not context.get("has_plan"):
                return cls._skills.get("planning")

        return None

    @classmethod
    async def execute_skill(
        cls,
        skill_name: str,
        context: SkillExecutionContext,
        inputs: dict[str, Any],
    ) -> SkillResult:
        """Look up, validate, and execute a skill by name."""
        skill = cls.get_skill(skill_name)
        if not skill:
            return SkillResult(
                skill_name=skill_name,
                success=False,
                error=f"Agent skill '{skill_name}' is not registered.",
            )

        return await skill.execute(context=context, inputs=inputs)

    @classmethod
    async def execute_pipeline(
        cls,
        request: SkillPipelineRequest,
        context: SkillExecutionContext,
    ) -> SkillPipelineResult:
        """Execute a sequential pipeline of composable skills, piping outputs between steps."""
        cls.initialize_default_skills()
        start_time = time.perf_counter()
        step_results: list[SkillResult] = []
        last_output: dict[str, Any] = {}

        for idx, step in enumerate(request.steps):
            skill = cls.get_skill(step.skill_name)
            if not skill:
                err = f"Pipeline step {idx + 1} failed: Skill '{step.skill_name}' not found."
                logger.error(err)
                return SkillPipelineResult(
                    success=False,
                    total_steps=len(request.steps),
                    completed_steps=len(step_results),
                    step_results=step_results,
                    final_output=last_output,
                    total_time_ms=(time.perf_counter() - start_time) * 1000,
                    error=err,
                )

            # Build inputs with passed data if requested
            step_inputs = dict(step.inputs)
            if step.pass_previous_output_key and last_output:
                step_inputs[step.pass_previous_output_key] = last_output.get(step.pass_previous_output_key)

            # Execute step
            result = await skill.execute(context=context, inputs=step_inputs)
            step_results.append(result)

            if not result.success:
                err = f"Pipeline stopped at step {idx + 1} ('{step.skill_name}'): {result.error}"
                logger.warning(err)
                if request.stop_on_failure:
                    return SkillPipelineResult(
                        success=False,
                        total_steps=len(request.steps),
                        completed_steps=len(step_results),
                        step_results=step_results,
                        final_output=last_output,
                        total_time_ms=(time.perf_counter() - start_time) * 1000,
                        error=err,
                    )

            last_output = result.data

        total_time = (time.perf_counter() - start_time) * 1000
        return SkillPipelineResult(
            success=all(r.success for r in step_results),
            total_steps=len(request.steps),
            completed_steps=len(step_results),
            step_results=step_results,
            final_output=last_output,
            total_time_ms=total_time,
        )
