import logging
import re

from app.db.models.memory import MemoryType
from app.services.learning.models import (
    ExecutionOutcome,
    LearningType,
    OutcomeEvaluation,
)

logger = logging.getLogger("lifethread.services.learning.evaluator")


class OutcomeEvaluator:
    """Evaluates execution outcomes to identify meaningful learning signals, weaknesses, strengths, and preferences."""

    @classmethod
    def evaluate(cls, outcome: ExecutionOutcome) -> OutcomeEvaluation:
        """Analyze an execution outcome and produce a structured OutcomeEvaluation."""
        status = outcome.status
        status_val = status.value if hasattr(status, "value") else str(status)
        perf = outcome.performance_score
        domain = outcome.domain or cls._infer_domain_from_title(outcome.task_title)
        topic = outcome.topic or cls._infer_topic_from_text(
            f"{outcome.task_title} {outcome.notes or ''} {outcome.error_message or ''}"
        )
        context_label = (
            f"{domain} {topic}".strip()
            if (domain and topic)
            else (domain or topic or outcome.task_title)
        )

        # -------------------------------------------------------------
        # 1. Detect Category: WEAKNESS, STRENGTH, PREFERENCE, ROUTINE
        # -------------------------------------------------------------
        eval_type = LearningType.NEUTRAL_ROUTINE
        severity_or_strength = "LOW"
        finding = f"Completed {outcome.task_title}"
        reasoning_parts: list[str] = []
        is_meaningful = False
        target_memory_type = MemoryType.SEMANTIC
        recommended_action: str | None = None

        # Check Preference in notes or artifacts
        notes_lower = (outcome.notes or "").lower()
        if "prefer" in notes_lower or "preference" in notes_lower or "work style" in notes_lower:
            eval_type = LearningType.PREFERENCE
            target_memory_type = MemoryType.PREFERENCE
            is_meaningful = True
            severity_or_strength = "MEDIUM"
            finding = f"User preference noted in {context_label}"
            reasoning_parts.append(
                "Explicit user workflow preference expressed in execution notes."
            )

        # Check Weakness: Low performance, task failure, or explicit struggle notes
        elif (
            status_val in ("FAILED", "BLOCKED")
            or (perf is not None and perf < 0.60)
            or any(
                kw in notes_lower
                for kw in ["struggled", "difficulty", "failed", "confused", "weakness"]
            )
            or outcome.error_message is not None
        ):
            eval_type = LearningType.WEAKNESS
            target_memory_type = MemoryType.SEMANTIC
            is_meaningful = True
            severity_or_strength = (
                "HIGH" if (perf is not None and perf < 0.40) or status_val == "FAILED" else "MEDIUM"
            )
            finding = f"Weakness in {topic or domain or 'task execution'}"
            recommended_action = f"Increase {context_label} practice"
            reasoning_parts.append(
                f"Observed performance degradation (score={perf if perf is not None else 'N/A'}, status={status_val})."
            )
            if outcome.error_message:
                reasoning_parts.append(f"Encountered error: {outcome.error_message}")

        # Check Strength: High performance or rapid mastery
        elif perf is not None and perf >= 0.85:
            eval_type = LearningType.STRENGTH
            target_memory_type = MemoryType.SEMANTIC
            is_meaningful = True
            severity_or_strength = "HIGH" if perf >= 0.95 else "MEDIUM"
            finding = f"Proficiency in {topic or domain or 'task execution'}"
            recommended_action = f"Advance to next complexity level in {context_label}"
            reasoning_parts.append(f"Demonstrated high mastery (score={perf:.2f}).")

        else:
            # Routine expected execution
            eval_type = LearningType.NEUTRAL_ROUTINE
            is_meaningful = False
            reasoning_parts.append(
                "Execution met baseline expected parameters without notable deviation."
            )

        # -------------------------------------------------------------
        # 2. Confidence Assignment & Epistemic Status (Requirements 3 & 8)
        # -------------------------------------------------------------
        confidence, is_factual, is_hypothesis, epistemic_qualifier = (
            cls._calculate_confidence_and_epistemic_status(
                outcome=outcome,
                eval_type=eval_type,
            )
        )

        # -------------------------------------------------------------
        # 3. Memory Importance Scoring (Requirements 1 & 2)
        # -------------------------------------------------------------
        importance_score = cls._calculate_importance_score(
            eval_type=eval_type,
            severity_or_strength=severity_or_strength,
            confidence=confidence,
            is_meaningful=is_meaningful,
        )

        # -------------------------------------------------------------
        # 4. Formulate Memory Content with Epistemic Precision (Requirement 8)
        # -------------------------------------------------------------
        suggested_content = cls._format_memory_content(
            eval_type=eval_type,
            context_label=context_label,
            domain=domain,
            topic=topic,
            finding=finding,
            confidence=confidence,
            is_factual=is_factual,
            notes=outcome.notes,
        )

        reasoning = (
            " ".join(reasoning_parts)
            if reasoning_parts
            else "Outcome evaluated against skill benchmarks."
        )

        return OutcomeEvaluation(
            outcome_id=outcome.outcome_id,
            is_meaningful=is_meaningful,
            evaluation_type=eval_type,
            observed_finding=finding,
            severity_or_strength=severity_or_strength,
            confidence=confidence,
            importance_score=importance_score,
            is_factual=is_factual,
            is_hypothesis=is_hypothesis,
            epistemic_qualifier=epistemic_qualifier,
            target_memory_type=target_memory_type,
            suggested_memory_content=suggested_content,
            recommended_planner_action=recommended_action,
            reasoning=reasoning,
        )

    @classmethod
    def _calculate_confidence_and_epistemic_status(
        cls,
        outcome: ExecutionOutcome,
        eval_type: LearningType,
    ) -> tuple[float, bool, bool, str]:
        """Compute rigorous confidence score and determine whether finding is a verified fact or hypothesis.

        CRITICAL INVARIANT (Requirement 8):
        Never treat uncertain information as fact.
        - Single unverified or ambiguous outcomes are strictly hypotheses with confidence < 0.70.
        - Verified, multi-attempt, or definitive scored tests achieve factual confidence >= 0.70.
        """
        # Baseline confidence from evidence quality
        has_quant_score = outcome.performance_score is not None
        has_error = bool(outcome.error_message)
        attempt_count = outcome.attempt_count

        status_val = (
            outcome.status.value if hasattr(outcome.status, "value") else str(outcome.status)
        )

        if eval_type == LearningType.NEUTRAL_ROUTINE:
            return 0.50, False, True, "Baseline observation"

        # Evidence accumulation
        if attempt_count >= 2:
            # Repeated observation gives high confidence
            base_conf = 0.85 + min(0.10, (attempt_count - 2) * 0.05)
        elif attempt_count == 1:
            # Single trial: provisional unless extreme decisive score
            if has_quant_score and (
                outcome.performance_score <= 0.30 or outcome.performance_score >= 0.95
            ):
                base_conf = 0.70
            elif has_quant_score:
                base_conf = 0.60
            elif has_error and status_val in ("FAILED", "BLOCKED"):
                base_conf = 0.65
            else:
                base_conf = 0.50
        else:
            base_conf = 0.50

        confidence = round(min(0.99, max(0.10, base_conf)), 2)

        # Threshold for Factual vs Hypothesis
        # Threshold: 0.70. Anything strictly below 0.70 is an uncertain hypothesis!
        if confidence >= 0.70:
            is_factual = True
            is_hypothesis = False
            epistemic_qualifier = "Verified observation"
        else:
            is_factual = False
            is_hypothesis = True
            epistemic_qualifier = "Provisional hypothesis"

        return confidence, is_factual, is_hypothesis, epistemic_qualifier

    @classmethod
    def _calculate_importance_score(
        cls,
        eval_type: LearningType,
        severity_or_strength: str,
        confidence: float,
        is_meaningful: bool,
    ) -> float:
        """Compute long-term memory retention priority score [0.0 to 1.0]."""
        if not is_meaningful or eval_type == LearningType.NEUTRAL_ROUTINE:
            return 0.30

        base_importance = {
            LearningType.WEAKNESS: 0.80,
            LearningType.STRENGTH: 0.75,
            LearningType.PREFERENCE: 0.70,
            LearningType.NEUTRAL_ROUTINE: 0.30,
        }.get(eval_type, 0.50)

        severity_bonus = {"CRITICAL": 0.15, "HIGH": 0.10, "MEDIUM": 0.0, "LOW": -0.10}.get(
            severity_or_strength, 0.0
        )

        importance = base_importance + severity_bonus + (confidence - 0.70) * 0.10
        return round(min(1.0, max(0.1, importance)), 2)

    @classmethod
    def _format_memory_content(
        cls,
        eval_type: LearningType,
        context_label: str,
        domain: str | None,
        topic: str | None,
        finding: str,
        confidence: float,
        is_factual: bool,
        notes: str | None,
    ) -> str:
        """Format the memory content with epistemic clarity."""
        concept = (
            f"{domain} {topic}".strip()
            if (domain and topic)
            else (topic or domain or context_label)
        )

        if eval_type == LearningType.WEAKNESS:
            if is_factual:
                return f"User struggles with {concept}"
            else:
                return f"Hypothesis: User may have difficulty with {concept} (provisional, confidence {confidence:.2f})"

        elif eval_type == LearningType.STRENGTH:
            if is_factual:
                return f"User has demonstrated proficiency in {concept}"
            else:
                return f"Hypothesis: User may excel at {concept} (provisional, confidence {confidence:.2f})"

        elif eval_type == LearningType.PREFERENCE:
            return f"User preference: {notes or finding}"

        return finding

    @staticmethod
    def _infer_domain_from_title(title: str) -> str | None:
        title_lower = title.lower()
        if "sql" in title_lower or "database" in title_lower or "postgres" in title_lower:
            return "SQL"
        if "python" in title_lower or "pandas" in title_lower or "fastapi" in title_lower:
            return "Python"
        if "machine learning" in title_lower or "model" in title_lower:
            return "Machine Learning"
        if "docker" in title_lower or "kubernetes" in title_lower:
            return "DevOps"
        return None

    @staticmethod
    def _infer_topic_from_text(text: str) -> str | None:
        text_lower = text.lower()
        candidates = [
            "joins",
            "join",
            "indexing",
            "subquery",
            "subqueries",
            "aggregations",
            "window functions",
            "recursion",
            "concurrency",
            "asyncio",
            "dockerfile",
        ]
        for c in candidates:
            if re.search(rf"\b{c}\b", text_lower):
                if c == "join":
                    return "joins"
                if c == "subquery":
                    return "subqueries"
                return c
        return None
