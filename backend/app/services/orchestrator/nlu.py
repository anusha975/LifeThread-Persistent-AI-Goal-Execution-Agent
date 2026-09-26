import re
from typing import Any

from app.services.orchestrator.models import AgentIntent, ClarificationOption


class NLUEngine:
    """Deterministic, resilient Natural Language Understanding engine for LifeThread Agent."""

    @classmethod
    def parse_intent(cls, text: str) -> tuple[AgentIntent, dict[str, Any]]:
        """Classify user intent and extract relevant structured slots."""
        raw = text.strip()
        lower = raw.lower()

        # 1. Change Deadline (e.g. "Change the deadline to Friday.", "Move deadline to tomorrow", "Extend deadline by 3 days")
        if re.search(
            r"\b(change|move|update|set|extend|reschedule)\b.*?\bdeadline\b|\bdeadline\b.*?\b(to|until|by)\b|\bmove it to (friday|monday|tuesday|wednesday|thursday|saturday|sunday|tomorrow)\b",
            lower,
        ):
            raw_date, target = cls._extract_deadline_info(raw)
            return AgentIntent.CHANGE_DEADLINE, {"raw_date": raw_date, "target": target}

        # 2. Update Priority (e.g. "Make it critical", "Set priority to high", "Make this task high priority")
        if re.search(
            r"\b(make it|set priority|change priority|update priority|mark as)\b.*?\b(critical|urgent|high|medium|low)\b|\b(critical|urgent|high|medium|low) priority\b",
            lower,
        ):
            priority, target_type, target_name = cls._extract_priority_info(raw)
            return AgentIntent.UPDATE_PRIORITY, {
                "priority": priority,
                "target_type": target_type,
                "target_name": target_name,
            }

        # 3. Capacity Constraint (e.g. "I only have one hour today.", "Can only work 2 hours")
        capacity_hours = cls._extract_capacity_hours(lower)
        if capacity_hours is not None or re.search(
            r"\b(only have|limited to|can only spend|can only work|available for)\b.*?\b(hour|minute|hr|min)",
            lower,
        ):
            hours = capacity_hours if capacity_hours is not None else 1.0
            return AgentIntent.CAPACITY_CONSTRAINT, {"hours": hours}

        # 4. Why Plan Changed (e.g. "Why did my plan change?", "Why was my schedule updated?")
        if re.search(
            r"\b(why did (my|the) plan change|why plan changed|why.*replan|reason for (plan )?change|why was (my|the) schedule)\b",
            lower,
        ):
            return AgentIntent.WHY_PLAN_CHANGED, {}

        # 5. What Changed (e.g. "What changed?", "What changed in my plan?", "Show changes")
        if re.search(
            r"\b(what changed|what\'s changed|what has changed|show changes|plan changes|what is different|plan diff)\b",
            lower,
        ):
            return AgentIntent.WHAT_CHANGED, {}

        # 6. What is Blocking (e.g. "What is blocking my goal?", "Any blockers?", "What's blocking?")
        if re.search(
            r"\b(what is blocking|what\'s blocking|any blockers|show blockers|what is stuck|why am i stuck|blocking my goal)\b",
            lower,
        ):
            return AgentIntent.WHAT_IS_BLOCKING, {}

        # 7. Milestone Query (e.g. "What is the current milestone?", "Show milestones", "What milestone are we on?")
        if re.search(
            r"\b(what is (the )?(current |next )?milestone|milestones\b|show milestones|which milestone)\b",
            lower,
        ):
            milestone_hint = cls._extract_milestone_hint(raw)
            return AgentIntent.MILESTONE_QUERY, {"milestone_hint": milestone_hint}

        # 8. Memory Query (e.g. "What do you remember?", "Show memories", "What are my preferences?")
        if re.search(
            r"\b(what do you remember|show (my )?memories|list memories|what are my (preferences|weaknesses)|show preferences|show weaknesses|what have you learned)\b",
            lower,
        ):
            return AgentIntent.MEMORY_QUERY, {}

        # 9. What should I do next (e.g. "What should I do next?", "What's next?", "Next action")
        if re.search(
            r"\b(what should i do next|what to do next|what\'s next|what next|next action|next task|what do i work on)\b",
            lower,
        ):
            return AgentIntent.NEXT_ACTION, {}

        # 10. Remember Fact / Weakness / Preference (e.g. "Remember that I struggle with SQL joins.")
        if re.search(
            r"\b(remember that|remember i|remember my|remember:|note that|don\'t forget that)\b",
            lower,
        ):
            fact, category = cls._extract_memory_fact(raw)
            return AgentIntent.REMEMBER_FACT, {"fact": fact, "category": category}

        # 11. Complete Task (e.g. "I finished the task", "Mark task as completed", "Done with current task")
        if re.search(
            r"\b(i finished (the|my|this)? task|completed (the|my|this)? task|mark.*done|mark.*completed|done with (the|my|this)? task)\b",
            lower,
        ):
            task_hint = cls._extract_task_hint(raw)
            return AgentIntent.COMPLETE_TASK, {"task_hint": task_hint}

        # 12. Create Goal (e.g. "Create a goal.", "Create a goal to learn Rust", "New goal: Build an app")
        if re.search(
            r"\b(create a goal|create goal|start a goal|new goal|set a goal|add a goal)\b",
            lower,
        ):
            title, days = cls._extract_goal_info(raw)
            return AgentIntent.CREATE_GOAL, {"title": title, "days": days}

        # 13. Switch Goal
        if re.search(r"\b(switch to goal|focus on goal|select goal|open goal)\b", lower):
            match = re.search(r"\b(?:switch to goal|focus on goal|select goal|open goal)\s+[\'\"]?([^\'\"]+)[\'\"]?", lower)
            goal_target = match.group(1).strip() if match else ""
            return AgentIntent.SWITCH_GOAL, {"target": goal_target}

        # 14. General Status
        if re.search(r"\b(status|overview|how am i doing|progress summary)\b", lower):
            return AgentIntent.GENERAL_STATUS, {}

        return AgentIntent.UNKNOWN, {}

    @classmethod
    def match_clarification_choice(
        cls,
        text: str,
        options: list[ClarificationOption],
    ) -> ClarificationOption | None:
        """Resolve user reply to one of the selectable clarification options."""
        raw = text.strip()
        lower = raw.lower()

        # 1. Exact ID match (from UI click)
        for opt in options:
            if raw == opt.id or raw == opt.entity_id:
                return opt

        # 2. Number or ordinal: "1", "#1", "option 1", "first", "1st", "second", "2nd"
        ordinals = {
            "first": 0, "1st": 0, "1": 0, "#1": 0, "one": 0,
            "second": 1, "2nd": 1, "2": 1, "#2": 1, "two": 1,
            "third": 2, "3rd": 2, "3": 2, "#3": 2, "three": 2,
            "fourth": 3, "4th": 3, "4": 3, "#4": 3, "four": 3,
            "fifth": 4, "5th": 4, "5": 4, "#5": 4, "five": 4,
        }
        for word, idx in ordinals.items():
            if re.search(rf"\b(?:option\s+)?{re.escape(word)}\b", lower):
                if 0 <= idx < len(options):
                    return options[idx]

        # 3. Label exact or substring match
        for opt in options:
            opt_lower = opt.label.lower()
            if opt_lower in lower or lower in opt_lower:
                return opt

        return None

    @classmethod
    def _extract_deadline_info(cls, raw: str) -> tuple[str | None, str | None]:
        """Extract raw deadline string and optional goal target."""
        # e.g., "Change the deadline to Friday.", "Change deadline of Learn Rust to next Monday"
        target = None
        target_match = re.search(r"\b(?:for|of|on|goal)\s+['\"]?([a-zA-Z0-9\s_-]+?)['\"]?\s+(?:to|until|by)\b", raw, re.IGNORECASE)
        if target_match:
            cand = target_match.group(1).strip()
            if cand.lower() not in ["the deadline", "deadline", "it", "this"]:
                target = cand

        date_part = None
        m = re.search(r"\b(?:to|until|by|for)\s+([a-zA-Z0-9\s_.,-]+)$", raw, re.IGNORECASE)
        if m:
            date_part = m.group(1).strip().strip(".!?,")
        elif "by" in raw.lower():
            m2 = re.search(r"\bby\s+(\d+\s+days?|\d+\s+weeks?)$", raw.lower())
            if m2:
                date_part = m2.group(1).strip()

        return date_part, target

    @classmethod
    def _extract_priority_info(cls, raw: str) -> tuple[str, str, str | None]:
        """Extract priority string ('CRITICAL'|'HIGH'|'MEDIUM'|'LOW'), target type, and target name."""
        lower = raw.lower()
        if "critical" in lower or "urgent" in lower:
            prio = "CRITICAL"
        elif "high" in lower:
            prio = "HIGH"
        elif "low" in lower:
            prio = "LOW"
        else:
            prio = "MEDIUM"

        target_type = "task" if "task" in lower else "goal"
        target_name = None
        m = re.search(r"\b(?:for|of|goal|task)\s+['\"]?([a-zA-Z0-9\s_-]+?)['\"]?\s+(?:to|as)\b", raw, re.IGNORECASE)
        if m:
            cand = m.group(1).strip()
            if cand.lower() not in ["priority", "it", "this"]:
                target_name = cand

        return prio, target_type, target_name

    @classmethod
    def _extract_milestone_hint(cls, raw: str) -> str | None:
        """Extract milestone title hint if mentioned."""
        m = re.search(r"\b(?:milestone)\s+['\"]?([a-zA-Z0-9\s_-]+?)['\"]?$", raw, re.IGNORECASE)
        return m.group(1).strip() if m else None

    @classmethod
    def _extract_task_hint(cls, raw: str) -> str | None:
        """Extract task title hint from completion request."""
        # e.g. "Mark 'Set up environment' as done" or "Completed task 'study fundamentals'"
        m = re.search(r"['\"]([^'\"]+)['\"]", raw)
        if m:
            return m.group(1).strip()
        m2 = re.search(r"\b(?:task|completed|finished)\s+([a-zA-Z0-9\s_-]+?)(?:\s+as\s+done|\s+done)?$", raw, re.IGNORECASE)
        if m2:
            cand = m2.group(1).strip()
            if cand.lower() not in ["the", "this", "my", "current"]:
                return cand
        return None

    @classmethod
    def _extract_capacity_hours(cls, lower: str) -> float | None:
        """Extract numeric or worded capacity hours from utterance."""
        word_to_num = {
            "one": 1.0,
            "two": 2.0,
            "three": 3.0,
            "four": 4.0,
            "five": 5.0,
            "six": 6.0,
            "seven": 7.0,
            "eight": 8.0,
            "half": 0.5,
        }

        if "half an hour" in lower or "half hour" in lower:
            return 0.5
        min_match = re.search(r"(\d+)\s*(?:minutes|mins|m)\b", lower)
        if min_match:
            return max(0.5, round(int(min_match.group(1)) / 60.0, 1))

        for word, val in word_to_num.items():
            if re.search(rf"\b{word}\s*(?:hours?|hrs?)\b", lower):
                return val

        digit_match = re.search(r"(\d+(?:\.\d+)?)\s*(?:hours?|hrs?)\b", lower)
        if digit_match:
            return float(digit_match.group(1))

        return None

    @classmethod
    def _extract_memory_fact(cls, raw: str) -> tuple[str, str]:
        """Extract memory content and infer appropriate category."""
        fact = re.sub(
            r"^(?:please\s+)?(?:remember\s+that|remember\s+i|remember\s+my|remember:|note\s+that|don\'t\s+forget\s+that)\s*",
            "",
            raw,
            flags=re.IGNORECASE,
        ).strip()

        if not fact:
            fact = raw

        lower_fact = fact.lower()
        if any(w in lower_fact for w in ["struggle", "weak", "weakness", "bad at", "hard for me", "difficulty", "trouble", "confused by"]):
            category = "Learned weakness"
        elif any(w in lower_fact for w in ["prefer", "preference", "like to", "favorite", "usually work", "morning", "evening"]):
            category = "Preference"
        else:
            category = "Relevant knowledge"

        return fact, category

    @classmethod
    def _extract_goal_info(cls, raw: str) -> tuple[str | None, int]:
        """Extract title and deadline days from goal creation utterance."""
        cleaned = re.sub(r"^(?:please\s+)?(?:create\s+a\s+goal|create\s+goal|start\s+a\s+goal|new\s+goal|set\s+a\s+goal)[:\s-]*", "", raw, flags=re.IGNORECASE).strip()
        cleaned = re.sub(r"^to\s+", "", cleaned, flags=re.IGNORECASE).strip()
        cleaned = re.sub(r"^[.!? :\"']+|[.!? :\"']+$", "", cleaned)

        days = 30
        days_match = re.search(r"\bin\s+(\d+)\s+days?\b", cleaned, flags=re.IGNORECASE)
        if days_match:
            days = int(days_match.group(1))

        weeks_match = re.search(r"\bin\s+(\d+)\s+weeks?\b", cleaned, flags=re.IGNORECASE)
        if weeks_match:
            days = int(weeks_match.group(1)) * 7

        title = cleaned if len(cleaned) >= 3 else None
        return title, days
