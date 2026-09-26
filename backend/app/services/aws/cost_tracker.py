import logging
import threading
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger("lifethread.aws.cost_tracker")

# Standard Bedrock pricing per 1,000,000 tokens (USD)
# Updated based on AWS Bedrock published rates
MODEL_PRICING: dict[str, dict[str, float]] = {
    # Anthropic Claude 3.5 Sonnet: $3.00 / 1M input, $15.00 / 1M output
    "anthropic.claude-3-5-sonnet": {
        "input_per_m": 3.00,
        "output_per_m": 15.00,
    },
    # Anthropic Claude 3 Haiku: $0.25 / 1M input, $1.25 / 1M output
    "anthropic.claude-3-haiku": {
        "input_per_m": 0.25,
        "output_per_m": 1.25,
    },
    # Anthropic Claude 3 Opus: $15.00 / 1M input, $75.00 / 1M output
    "anthropic.claude-3-opus": {
        "input_per_m": 15.00,
        "output_per_m": 75.00,
    },
    # Amazon Titan Text Premier: $0.50 / 1M input, $1.50 / 1M output
    "amazon.titan-text": {
        "input_per_m": 0.50,
        "output_per_m": 1.50,
    },
    # Amazon Titan Embeddings v2: $0.02 / 1M input
    "amazon.titan-embed": {
        "input_per_m": 0.02,
        "output_per_m": 0.0,
    },
    # Meta Llama 3 70B: $0.72 / 1M input, $0.72 / 1M output
    "meta.llama3": {
        "input_per_m": 0.72,
        "output_per_m": 0.72,
    },
}

DEFAULT_FALLBACK_PRICING = {"input_per_m": 1.00, "output_per_m": 3.00}


class ModelUsageRecord(BaseModel):
    """Token and cost usage record for a single model invocation."""

    model_config = ConfigDict(from_attributes=True)

    model_id: str
    input_tokens: int
    output_tokens: int
    total_tokens: int
    estimated_cost_usd: float
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))


class CostMetricsSummary(BaseModel):
    """Aggregate token and cost consumption metrics for AWS AI services."""

    model_config = ConfigDict(from_attributes=True)

    total_requests: int
    total_input_tokens: int
    total_output_tokens: int
    total_tokens: int
    total_cost_usd: float
    by_model: dict[str, dict[str, Any]]
    last_invocation_at: datetime | None = None


class BedrockCostTracker:
    """Thread-safe cost and token accounting engine for Bedrock invocations."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._records: list[ModelUsageRecord] = []
        self._by_model: dict[str, dict[str, Any]] = {}
        self._total_requests: int = 0
        self._total_input_tokens: int = 0
        self._total_output_tokens: int = 0
        self._total_cost_usd: float = 0.0
        self._last_invocation: datetime | None = None

    @classmethod
    def calculate_cost(
        cls,
        model_id: str,
        input_tokens: int,
        output_tokens: int,
    ) -> float:
        """Calculate the estimated USD cost for a given model invocation."""
        pricing = DEFAULT_FALLBACK_PRICING
        for prefix, rates in MODEL_PRICING.items():
            if prefix in model_id.lower():
                pricing = rates
                break

        input_cost = (input_tokens / 1_000_000.0) * pricing["input_per_m"]
        output_cost = (output_tokens / 1_000_000.0) * pricing["output_per_m"]
        return round(input_cost + output_cost, 6)

    def record_invocation(
        self,
        model_id: str,
        input_tokens: int,
        output_tokens: int,
    ) -> ModelUsageRecord:
        """Record an invocation and update running metrics."""
        cost = self.calculate_cost(model_id, input_tokens, output_tokens)
        record = ModelUsageRecord(
            model_id=model_id,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=input_tokens + output_tokens,
            estimated_cost_usd=cost,
            timestamp=datetime.now(UTC),
        )

        with self._lock:
            self._records.append(record)
            self._total_requests += 1
            self._total_input_tokens += input_tokens
            self._total_output_tokens += output_tokens
            self._total_cost_usd = round(self._total_cost_usd + cost, 6)
            self._last_invocation = record.timestamp

            if model_id not in self._by_model:
                self._by_model[model_id] = {
                    "requests": 0,
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "total_tokens": 0,
                    "cost_usd": 0.0,
                }
            bm = self._by_model[model_id]
            bm["requests"] += 1
            bm["input_tokens"] += input_tokens
            bm["output_tokens"] += output_tokens
            bm["total_tokens"] += input_tokens + output_tokens
            bm["cost_usd"] = round(bm["cost_usd"] + cost, 6)

        logger.debug(
            "AWS Bedrock Invocation Recorded: model=%s in=%d out=%d cost=$%.6f",
            model_id,
            input_tokens,
            output_tokens,
            cost,
        )
        return record

    def get_summary(self) -> CostMetricsSummary:
        """Return a snapshot summary of current cost and token metrics."""
        with self._lock:
            return CostMetricsSummary(
                total_requests=self._total_requests,
                total_input_tokens=self._total_input_tokens,
                total_output_tokens=self._total_output_tokens,
                total_tokens=self._total_input_tokens + self._total_output_tokens,
                total_cost_usd=round(self._total_cost_usd, 6),
                by_model=dict(self._by_model),
                last_invocation_at=self._last_invocation,
            )

    def reset(self) -> None:
        """Reset all in-memory usage metrics (useful for testing)."""
        with self._lock:
            self._records.clear()
            self._by_model.clear()
            self._total_requests = 0
            self._total_input_tokens = 0
            self._total_output_tokens = 0
            self._total_cost_usd = 0.0
            self._last_invocation = None


# Singleton instance
cost_tracker = BedrockCostTracker()
