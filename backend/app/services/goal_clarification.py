import re
from datetime import datetime

from app.schemas.goal_understanding import AmbiguityReport, GoalConstraintDraft


class GoalClarificationService:
    """Evaluates goal ambiguity, identifies missing critical information, and generates targeted clarification questions."""

    # Words and phrases that commonly signal underspecified or ambiguous intent
    VAGUE_PATTERNS = [
        r"\b(?:stuff|things|something|someday|eventually|maybe|kinda|sort of)\b",
        r"\b(?:asap|as soon as possible|quickly|soon)\b",
        r"\b(?:get better|be good|learn stuff|make money|be successful)\b",
    ]

    @classmethod
    def evaluate(
        cls,
        raw_text: str,
        objective: str,
        deadline: datetime | None,
        constraints: list[GoalConstraintDraft],
        success_criteria: list[str],
        llm_ambiguity_report: AmbiguityReport | None = None,
        clarification_answers: dict[str, str] | None = None,
    ) -> AmbiguityReport:
        """Analyze the goal input and extracted attributes to detect ambiguity and missing details."""
        missing_info: list[str] = []
        questions: list[str] = []
        is_ambiguous = False
        confidence = 1.0

        # Incorporate LLM's assessment if provided
        if llm_ambiguity_report is not None:
            is_ambiguous = llm_ambiguity_report.is_ambiguous
            missing_info.extend(llm_ambiguity_report.missing_information)
            questions.extend(llm_ambiguity_report.clarification_questions)
            confidence = min(confidence, llm_ambiguity_report.confidence_score)

        cleaned_raw = raw_text.strip().lower()
        cleaned_obj = objective.strip().lower()

        # Rule 1: Check for extremely brief or non-specific goals
        word_count = len(cleaned_raw.split())
        if word_count < 5 and not success_criteria and deadline is None:
            is_ambiguous = True
            confidence = min(confidence, 0.4)
            if "Target deliverable or specific milestone" not in missing_info:
                missing_info.append("Target deliverable or specific milestone")
            q = f"Could you provide more specific details on what '{objective}' entails for you?"
            if q not in questions:
                questions.append(q)

        # Rule 2: Check for vague phrasing patterns
        for pattern in cls.VAGUE_PATTERNS:
            if re.search(pattern, cleaned_raw) or re.search(pattern, cleaned_obj):
                is_ambiguous = True
                confidence = min(confidence, 0.6)
                if "Concrete scope and timeline" not in missing_info:
                    missing_info.append("Concrete scope and timeline")
                q = "What concrete timeline or milestone would define success for this goal?"
                if q not in questions:
                    questions.append(q)
                break

        # Rule 3: Check for empty success criteria on complex objectives
        if not success_criteria and word_count > 6 and is_ambiguous:
            if "Measurable completion criteria" not in missing_info:
                missing_info.append("Measurable completion criteria")
            q = "How will you verify when this objective is completed?"
            if q not in questions:
                questions.append(q)

        # If user answered clarifications in this round, mark resolved unless still empty
        if clarification_answers:
            # User provided answers to clarifications
            if len(clarification_answers) >= len(questions):
                is_ambiguous = False
                questions = []
                missing_info = []
                confidence = max(confidence, 0.85)

        # Clean duplicates while preserving order
        deduped_missing = list(dict.fromkeys(missing_info))
        deduped_questions = list(dict.fromkeys(questions))

        return AmbiguityReport(
            is_ambiguous=is_ambiguous,
            missing_information=deduped_missing,
            clarification_questions=deduped_questions,
            confidence_score=round(confidence, 2),
        )
