"""Abstract base for all EDGAR-X LLM agents.

Centralises everything every agent must do identically:

* call Claude via the Anthropic SDK with ``timeout=300`` and SDK-native
  exponential-backoff retries (the SDK retries 429/5xx itself; we configure
  ``max_retries`` rather than reimplementing the loop),
* enforce the per-run spend cap BEFORE each call via :class:`CostTracker`,
* log token usage and cost AFTER each call,
* use prompt caching: the system prompt carries a cache breakpoint, and
  large reused context (filing text) can be marked cacheable by callers —
  note Fable 5's minimum cacheable prefix is ~2,048 tokens, so caching pays
  on filing-sized content, not on short prompts,
* parse the response into the subclass's Pydantic output schema via
  ``client.messages.parse`` (structured outputs).

Model notes (Fable 5): adaptive thinking only; sampling parameters are not
supported; an explicit ``thinking: disabled`` is rejected — the ``thinking``
parameter is simply omitted unless a subclass opts into adaptive thinking.
"""

from __future__ import annotations

from abc import ABC
from typing import TYPE_CHECKING, Any, ClassVar, Generic, TypeVar

import pydantic
from pydantic import BaseModel

from agents.cost_tracker import CostTracker, estimate_max_cost
from core.config import get_settings
from core.logging import get_logger

if TYPE_CHECKING:  # pragma: no cover - heavy import, typing only
    import anthropic

logger = get_logger(__name__)

#: Crude local token estimate used ONLY for pre-call budget projection
#: (≈4 chars/token; the post-call record uses exact usage from the API).
CHARS_PER_TOKEN_ESTIMATE = 4.0

REQUEST_TIMEOUT_SECONDS = 300.0
MAX_RETRIES = 4

OutputT = TypeVar("OutputT", bound=BaseModel)


class AgentOutputError(RuntimeError):
    """Raised when the model response cannot be parsed into the output schema."""


def _default_client() -> anthropic.Anthropic:
    """Build the real Anthropic client (deferred heavy import).

    Credentials come from ``ANTHROPIC_API_KEY`` in the environment — never
    hardcoded. Timeout and retry policy are fixed project-wide here.
    """
    import anthropic  # noqa: PLC0415 - deferred: heavy optional import

    return anthropic.Anthropic(timeout=REQUEST_TIMEOUT_SECONDS, max_retries=MAX_RETRIES)


def cached_text_block(text: str) -> dict[str, Any]:
    """Wrap large reused text (e.g. filing sections) as a cacheable block.

    Args:
        text: The block text.

    Returns:
        A text content block with an ephemeral cache breakpoint.
    """
    return {"type": "text", "text": text, "cache_control": {"type": "ephemeral"}}


class BaseAgent(ABC, Generic[OutputT]):
    """Shared call/cost/parse machinery for every EDGAR-X agent.

    Subclasses declare:

    * ``agent_name`` — logical name used in cost logs,
    * ``model`` — model id (defaults to Fable 5),
    * ``max_output_tokens`` — hard output cap for this agent,
    * ``output_schema`` — the Pydantic model responses are parsed into,
    * ``system_prompt`` — the agent's system prompt (kept byte-stable so the
      prompt cache prefix holds).
    """

    agent_name: ClassVar[str]
    model: ClassVar[str] = "claude-fable-5"
    max_output_tokens: ClassVar[int]
    output_schema: ClassVar[type[BaseModel]]
    system_prompt: ClassVar[str]
    #: Opt-in adaptive thinking (omit the param otherwise — required on Fable 5).
    use_adaptive_thinking: ClassVar[bool] = False

    def __init__(
        self,
        *,
        client: anthropic.Anthropic | None = None,
        tracker: CostTracker | None = None,
    ) -> None:
        """Initialise the agent.

        Args:
            client: Optional injected Anthropic client (tests use a fake).
            tracker: Cost tracker shared across agents in one run; a fresh
                one (with the env-configured cap) is created when omitted.
        """
        if not get_settings().anthropic_api_key and client is None:
            logger.warning("anthropic_api_key_missing", hint="set ANTHROPIC_API_KEY in .env")
        self._client = client or _default_client()
        self.tracker = tracker or CostTracker()

    def run_prompt(
        self,
        *,
        ticker: str | None,
        user_content: str | list[dict[str, Any]],
    ) -> OutputT:
        """Make one budgeted, logged, schema-parsed model call.

        Args:
            ticker: Company the call concerns (for cost attribution).
            user_content: The user turn — a plain string, or a list of
                content blocks (use :func:`cached_text_block` for large
                reused context such as filing text).

        Returns:
            The response parsed into ``output_schema``.

        Raises:
            SpendCapExceededError: If the projected cost would breach the cap.
            AgentOutputError: If the response fails schema parsing.
        """
        projected = estimate_max_cost(
            self.model,
            input_tokens=self._estimate_input_tokens(user_content),
            max_output_tokens=self.max_output_tokens,
        )
        self.tracker.check_budget(projected)

        request: dict[str, Any] = {
            "model": self.model,
            "max_tokens": self.max_output_tokens,
            "system": [
                {
                    "type": "text",
                    "text": self.system_prompt,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            "messages": [{"role": "user", "content": user_content}],
            "output_format": self.output_schema,
        }
        if self.use_adaptive_thinking:
            request["thinking"] = {"type": "adaptive"}

        try:
            response = self._client.messages.parse(**request)
        except pydantic.ValidationError as exc:
            # The API answered (and billed us) but the JSON didn't validate —
            # typically output truncated at max_tokens. Record a conservative
            # cost estimate so the spend ledger never under-counts.
            self.tracker.record(
                model=self.model,
                agent_name=f"{self.agent_name}(unparseable)",
                ticker=ticker,
                input_tokens=self._estimate_input_tokens(user_content),
                output_tokens=self.max_output_tokens,
            )
            raise AgentOutputError(
                f"{self.agent_name}: response was not valid "
                f"{self.output_schema.__name__} JSON — likely truncated at the "
                f"{self.max_output_tokens}-token output cap "
                f"(cost recorded as a conservative estimate)"
            ) from exc

        usage = response.usage
        self.tracker.record(
            model=self.model,
            agent_name=self.agent_name,
            ticker=ticker,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            cache_creation_input_tokens=getattr(usage, "cache_creation_input_tokens", 0) or 0,
            cache_read_input_tokens=getattr(usage, "cache_read_input_tokens", 0) or 0,
        )

        parsed = response.parsed_output
        if parsed is None:
            raise AgentOutputError(
                f"{self.agent_name}: response did not parse into "
                f"{self.output_schema.__name__} (stop_reason={response.stop_reason})"
            )
        return parsed  # type: ignore[return-value]

    def _estimate_input_tokens(self, user_content: str | list[dict[str, Any]]) -> int:
        """Locally estimate input tokens for the pre-call budget projection."""
        if isinstance(user_content, str):
            content_chars = len(user_content)
        else:
            content_chars = sum(len(block.get("text", "")) for block in user_content)
        total_chars = content_chars + len(self.system_prompt)
        return int(total_chars / CHARS_PER_TOKEN_ESTIMATE)
