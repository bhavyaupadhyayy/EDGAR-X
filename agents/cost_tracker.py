"""LLM API cost tracking with a hard per-run spend ceiling.

Every API call is recorded to a local JSONL file with full token accounting
(including prompt-cache reads and writes, which bill at different rates) and
added to a running session total. Before any call, :meth:`CostTracker.check_budget`
must pass — if the projected total would exceed ``AGENT_SPEND_CAP_USD``, the
run aborts rather than continuing to spend.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import ClassVar

from pydantic import BaseModel, ConfigDict

from core.config import get_settings
from core.logging import get_logger

logger = get_logger(__name__)

DEFAULT_LOG_PATH = Path(__file__).parent / "cost_log.jsonl"

#: USD per million tokens. Cache reads bill at ~0.1x the input rate and cache
#: writes (5-minute TTL) at 1.25x — see the Anthropic prompt-caching docs.
CACHE_READ_MULTIPLIER = 0.1
CACHE_WRITE_MULTIPLIER = 1.25


class ModelPricing(BaseModel):
    """Per-million-token pricing for one model."""

    model_config = ConfigDict(frozen=True)

    input_usd_per_mtok: float
    output_usd_per_mtok: float


#: Verified against the Anthropic model catalog (cached 2026-05).
MODEL_PRICING: dict[str, ModelPricing] = {
    "claude-fable-5": ModelPricing(input_usd_per_mtok=10.0, output_usd_per_mtok=50.0),
    "claude-opus-4-8": ModelPricing(input_usd_per_mtok=5.0, output_usd_per_mtok=25.0),
}


class SpendCapExceededError(RuntimeError):
    """Raised when a call would push the session total past the spend cap."""


class CostRecord(BaseModel):
    """One logged API call."""

    model_config = ConfigDict(frozen=True)

    timestamp: str
    model: str
    agent_name: str
    ticker: str | None
    input_tokens: int
    output_tokens: int
    cache_creation_input_tokens: int
    cache_read_input_tokens: int
    cost_usd: float


def compute_cost(
    model: str,
    *,
    input_tokens: int,
    output_tokens: int,
    cache_creation_input_tokens: int = 0,
    cache_read_input_tokens: int = 0,
) -> float:
    """Compute the USD cost of one API call.

    ``input_tokens`` is the UNCACHED portion as reported by the API; cached
    reads and cache writes are billed at their own multipliers of the input
    rate.

    Args:
        model: Model id; must be present in :data:`MODEL_PRICING`.
        input_tokens: Uncached input tokens.
        output_tokens: Output tokens.
        cache_creation_input_tokens: Tokens written to the prompt cache.
        cache_read_input_tokens: Tokens served from the prompt cache.

    Returns:
        The call cost in USD.

    Raises:
        KeyError: If the model has no configured pricing — refusing to guess
            prices is part of cost control.
    """
    if model not in MODEL_PRICING:
        raise KeyError(f"no pricing configured for model {model!r}")
    pricing = MODEL_PRICING[model]
    input_rate = pricing.input_usd_per_mtok / 1_000_000
    output_rate = pricing.output_usd_per_mtok / 1_000_000
    return (
        input_tokens * input_rate
        + cache_creation_input_tokens * input_rate * CACHE_WRITE_MULTIPLIER
        + cache_read_input_tokens * input_rate * CACHE_READ_MULTIPLIER
        + output_tokens * output_rate
    )


def estimate_max_cost(model: str, *, input_tokens: int, max_output_tokens: int) -> float:
    """Worst-case cost estimate for a call (all input uncached, output at cap).

    Args:
        model: Model id.
        input_tokens: Estimated input tokens.
        max_output_tokens: The output token cap for the call.

    Returns:
        Upper-bound USD cost, used for pre-call budget checks.
    """
    return compute_cost(model, input_tokens=input_tokens, output_tokens=max_output_tokens)


class CostTracker:
    """Session-scoped spend ledger with a hard cap.

    Appends one JSON line per API call to ``log_path`` and prints the running
    session total after each call.
    """

    _SESSION_FIELDS: ClassVar[tuple[str, ...]] = ("model", "agent_name", "ticker")

    def __init__(
        self,
        *,
        log_path: Path = DEFAULT_LOG_PATH,
        spend_cap_usd: float | None = None,
    ) -> None:
        """Initialise the tracker.

        Args:
            log_path: JSONL file appended to on every call.
            spend_cap_usd: Hard session ceiling; falls back to the
                ``AGENT_SPEND_CAP_USD`` env var (default 5.00).
        """
        self._log_path = log_path
        self.spend_cap_usd = (
            spend_cap_usd
            if spend_cap_usd is not None
            else get_settings().agent_spend_cap_usd
        )
        self.session_total_usd = 0.0
        self.calls = 0
        self.records: list[CostRecord] = []

    def check_budget(self, projected_cost_usd: float) -> None:
        """Abort if a projected call would exceed the spend cap.

        Args:
            projected_cost_usd: Worst-case cost of the upcoming call.

        Raises:
            SpendCapExceededError: If session total + projection exceeds the cap.
        """
        projected_total = self.session_total_usd + projected_cost_usd
        if projected_total > self.spend_cap_usd:
            raise SpendCapExceededError(
                f"aborting: projected session spend ${projected_total:.4f} would exceed "
                f"the cap of ${self.spend_cap_usd:.2f} "
                f"(spent so far: ${self.session_total_usd:.4f}, "
                f"next call worst case: ${projected_cost_usd:.4f})"
            )

    def record(
        self,
        *,
        model: str,
        agent_name: str,
        ticker: str | None,
        input_tokens: int,
        output_tokens: int,
        cache_creation_input_tokens: int = 0,
        cache_read_input_tokens: int = 0,
    ) -> CostRecord:
        """Log one completed API call and update the session total.

        Args:
            model: Model id used.
            agent_name: Logical agent making the call.
            ticker: Company the call concerned, if any.
            input_tokens: Uncached input tokens from the response usage.
            output_tokens: Output tokens from the response usage.
            cache_creation_input_tokens: Cache-write tokens from usage.
            cache_read_input_tokens: Cache-read tokens from usage.

        Returns:
            The persisted record.
        """
        cost = compute_cost(
            model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_creation_input_tokens=cache_creation_input_tokens,
            cache_read_input_tokens=cache_read_input_tokens,
        )
        record = CostRecord(
            timestamp=datetime.now(UTC).isoformat(),
            model=model,
            agent_name=agent_name,
            ticker=ticker,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_creation_input_tokens=cache_creation_input_tokens,
            cache_read_input_tokens=cache_read_input_tokens,
            cost_usd=round(cost, 6),
        )
        self.session_total_usd += cost
        self.calls += 1
        self.records.append(record)
        self._log_path.parent.mkdir(parents=True, exist_ok=True)
        with self._log_path.open("a", encoding="utf-8") as handle:
            handle.write(record.model_dump_json() + "\n")
        logger.info(
            "api_call_cost",
            agent=agent_name,
            model=model,
            ticker=ticker,
            cost_usd=round(cost, 6),
            session_total_usd=round(self.session_total_usd, 6),
        )
        print(
            f"[cost] {agent_name} ({model}) ${cost:.4f} | "
            f"session total ${self.session_total_usd:.4f} / cap ${self.spend_cap_usd:.2f}"
        )
        return record
