import math
import re
from datetime import UTC, datetime


class RelevanceScorer:
    """Calculates relevance scores for context items against a query or task objective."""

    @staticmethod
    def tokenize(text: str) -> list[str]:
        """Simple alphanumeric tokenizer with stopword reduction."""
        return list(re.findall(r"\b\w{2,}\b", text.lower()))

    @classmethod
    def compute_lexical_similarity(cls, query: str, content: str) -> float:
        """Compute term overlap similarity and exact phrase bonus."""
        if not query or not content:
            return 0.0

        query_norm = query.lower().strip()
        content_norm = content.lower().strip()

        # Exact match bonus
        if query_norm in content_norm:
            phrase_bonus = 0.35
        else:
            phrase_bonus = 0.0

        query_tokens = set(cls.tokenize(query_norm))
        content_tokens = set(cls.tokenize(content_norm))

        if not query_tokens:
            return 0.0

        overlap = len(query_tokens.intersection(content_tokens))
        token_sim = overlap / len(query_tokens)

        # Content word count normalization (diminishing return on length)
        return min(1.0, 0.65 * token_sim + phrase_bonus)

    @staticmethod
    def compute_recency_bonus(timestamp: datetime | None, half_life_days: float = 7.0) -> float:
        """Compute an exponential decay recency bonus [0.0, 1.0]."""
        if not timestamp:
            return 0.5  # Neutral bonus for non-temporal items

        now = datetime.now(UTC)
        if timestamp.tzinfo is None:
            ts = timestamp.replace(tzinfo=UTC)
        else:
            ts = timestamp.astimezone(UTC)

        age_seconds = max(0.0, (now - ts).total_seconds())
        age_days = age_seconds / 86400.0

        # Exponential decay: 2^(-age_days / half_life_days)
        decay = math.pow(2.0, -age_days / max(1.0, half_life_days))
        return min(1.0, max(0.0, decay))

    @classmethod
    def score_item(
        cls,
        item_content: str,
        query: str | None,
        base_relevance: float = 1.0,
        timestamp: datetime | None = None,
        is_high_priority_source: bool = False,
    ) -> float:
        """Compute composite relevance score in [0.0, 1.0].

        High priority sources (Current Task, Goal, Constraints) maintain high base score
        by default, while conversational/historical items are modulated by query match & recency.
        """
        # If no query is provided, rely on base_relevance
        if not query or not query.strip():
            return max(0.0, min(1.0, base_relevance))

        if is_high_priority_source:
            # High priority sources always stay relevant (minimum 0.85)
            lexical = cls.compute_lexical_similarity(query, item_content)
            return min(1.0, max(0.85, 0.85 * base_relevance + 0.15 * lexical))

        lexical = cls.compute_lexical_similarity(query, item_content)
        recency = cls.compute_recency_bonus(timestamp)

        # 50% base/semantic, 40% lexical/query overlap, 10% recency
        score = 0.50 * base_relevance + 0.40 * lexical + 0.10 * recency
        return round(min(1.0, max(0.0, score)), 4)
