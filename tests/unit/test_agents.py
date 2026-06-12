"""Unit tests for the cost tracker and base agent (Anthropic API fully mocked)."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, ClassVar

import pytest
from pydantic import BaseModel

from agents.base_agent import AgentOutputError, BaseAgent, cached_text_block
from agents.cost_tracker import (
    CostTracker,
    SpendCapExceededError,
    compute_cost,
    estimate_max_cost,
)


class TestComputeCost:
    """Pricing arithmetic, including cache rates."""

    def test_fable5_basic_call(self) -> None:
        # 100K in @ $10/M + 10K out @ $50/M = $1.00 + $0.50
        cost = compute_cost("claude-fable-5", input_tokens=100_000, output_tokens=10_000)
        assert cost == pytest.approx(1.50)

    def test_opus48_is_half_price(self) -> None:
        cost = compute_cost("claude-opus-4-8", input_tokens=100_000, output_tokens=10_000)
        assert cost == pytest.approx(0.75)

    def test_cache_read_bills_at_tenth_of_input(self) -> None:
        cost = compute_cost(
            "claude-fable-5",
            input_tokens=0,
            output_tokens=0,
            cache_read_input_tokens=1_000_000,
        )
        assert cost == pytest.approx(1.0)  # 10% of $10/M

    def test_cache_write_bills_at_125_percent(self) -> None:
        cost = compute_cost(
            "claude-fable-5",
            input_tokens=0,
            output_tokens=0,
            cache_creation_input_tokens=1_000_000,
        )
        assert cost == pytest.approx(12.5)

    def test_unknown_model_refuses_to_guess(self) -> None:
        with pytest.raises(KeyError, match="no pricing configured"):
            compute_cost("claude-mystery-9", input_tokens=1, output_tokens=1)

    def test_estimate_max_cost_assumes_output_at_cap(self) -> None:
        estimate = estimate_max_cost(
            "claude-fable-5", input_tokens=10_000, max_output_tokens=4_000
        )
        assert estimate == pytest.approx(0.10 + 0.20)


class TestCostTracker:
    """Ledger behaviour and the hard cap."""

    def test_record_appends_jsonl_and_accumulates(self, tmp_path: Path) -> None:
        tracker = CostTracker(log_path=tmp_path / "log.jsonl", spend_cap_usd=5.0)
        tracker.record(
            model="claude-fable-5",
            agent_name="extraction",
            ticker="AAPL",
            input_tokens=50_000,
            output_tokens=2_000,
        )
        tracker.record(
            model="claude-opus-4-8",
            agent_name="judge",
            ticker="AAPL",
            input_tokens=10_000,
            output_tokens=1_000,
        )
        lines = (tmp_path / "log.jsonl").read_text().strip().splitlines()
        assert len(lines) == 2
        first = json.loads(lines[0])
        assert first["agent_name"] == "extraction"
        assert first["ticker"] == "AAPL"
        assert first["cost_usd"] == pytest.approx(0.5 + 0.1)
        assert tracker.calls == 2
        assert tracker.session_total_usd == pytest.approx(0.6 + 0.05 + 0.025)

    def test_check_budget_aborts_over_cap(self, tmp_path: Path) -> None:
        tracker = CostTracker(log_path=tmp_path / "log.jsonl", spend_cap_usd=1.0)
        tracker.record(
            model="claude-fable-5",
            agent_name="extraction",
            ticker="AAPL",
            input_tokens=80_000,
            output_tokens=0,
        )  # $0.80 spent
        tracker.check_budget(0.10)  # fine: 0.90 < 1.00
        with pytest.raises(SpendCapExceededError, match="exceed the cap"):
            tracker.check_budget(0.30)  # 1.10 > 1.00

    def test_cap_read_from_env(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from core.config import get_settings

        monkeypatch.setenv("AGENT_SPEND_CAP_USD", "2.5")
        get_settings.cache_clear()
        tracker = CostTracker(log_path=tmp_path / "log.jsonl")
        assert tracker.spend_cap_usd == 2.5


class FakeUsage:
    """Duck-typed usage block."""

    def __init__(self) -> None:
        self.input_tokens = 1_000
        self.output_tokens = 500
        self.cache_creation_input_tokens = 2_000
        self.cache_read_input_tokens = 8_000


@dataclass
class FakeResponse:
    parsed_output: Any
    usage: FakeUsage = field(default_factory=FakeUsage)
    stop_reason: str = "end_turn"


class FakeMessages:
    def __init__(self, response: FakeResponse) -> None:
        self._response = response
        self.parse_calls: list[dict[str, Any]] = []

    def parse(self, **kwargs: Any) -> FakeResponse:
        self.parse_calls.append(kwargs)
        return self._response


class FakeAnthropicClient:
    def __init__(self, response: FakeResponse) -> None:
        self.messages = FakeMessages(response)


class ClaimList(BaseModel):
    claims: list[str]


class DemoAgent(BaseAgent[ClaimList]):
    agent_name: ClassVar[str] = "demo"
    max_output_tokens: ClassVar[int] = 4_000
    output_schema: ClassVar[type[BaseModel]] = ClaimList
    system_prompt: ClassVar[str] = "You are a test agent. Extract claims."


class TestBaseAgent:
    """Request construction, cost flow, and parsing — no real API calls."""

    def _agent(self, tmp_path: Path, response: FakeResponse, cap: float = 5.0) -> DemoAgent:
        tracker = CostTracker(log_path=tmp_path / "log.jsonl", spend_cap_usd=cap)
        return DemoAgent(client=FakeAnthropicClient(response), tracker=tracker)  # type: ignore[arg-type]

    def test_returns_parsed_output_and_records_cost(self, tmp_path: Path) -> None:
        expected = ClaimList(claims=["revenue grew"])
        agent = self._agent(tmp_path, FakeResponse(parsed_output=expected))
        result = agent.run_prompt(ticker="AAPL", user_content="some filing text")
        assert result == expected
        assert agent.tracker.calls == 1
        # exact usage from the (fake) API, including cache tokens, was billed
        assert agent.tracker.session_total_usd == pytest.approx(
            compute_cost(
                "claude-fable-5",
                input_tokens=1_000,
                output_tokens=500,
                cache_creation_input_tokens=2_000,
                cache_read_input_tokens=8_000,
            )
        )

    def test_request_shape(self, tmp_path: Path) -> None:
        agent = self._agent(tmp_path, FakeResponse(parsed_output=ClaimList(claims=[])))
        agent.run_prompt(ticker="AAPL", user_content="text")
        call = agent._client.messages.parse_calls[0]  # type: ignore[attr-defined]
        assert call["model"] == "claude-fable-5"
        assert call["max_tokens"] == 4_000
        assert call["output_format"] is ClaimList
        # system prompt carries the prompt-cache breakpoint
        assert call["system"][0]["cache_control"] == {"type": "ephemeral"}
        # no thinking param unless opted in (explicit disabled 400s on Fable 5)
        assert "thinking" not in call
        # no sampling params (removed on Fable 5)
        assert "temperature" not in call and "top_p" not in call

    def test_spend_cap_blocks_before_calling_api(self, tmp_path: Path) -> None:
        agent = self._agent(
            tmp_path, FakeResponse(parsed_output=ClaimList(claims=[])), cap=0.01
        )
        with pytest.raises(SpendCapExceededError):
            agent.run_prompt(ticker="AAPL", user_content="x" * 400_000)
        # the API client was never invoked
        assert agent._client.messages.parse_calls == []  # type: ignore[attr-defined]
        assert agent.tracker.calls == 0

    def test_unparseable_response_raises(self, tmp_path: Path) -> None:
        agent = self._agent(tmp_path, FakeResponse(parsed_output=None))
        with pytest.raises(AgentOutputError, match="did not parse"):
            agent.run_prompt(ticker="AAPL", user_content="text")

    def test_truncated_json_records_estimated_cost(self, tmp_path: Path) -> None:
        import pydantic

        class RaisingMessages:
            def parse(self, **kwargs: Any) -> None:
                raise pydantic.ValidationError.from_exception_data("ClaimList", [])

        class RaisingClient:
            messages = RaisingMessages()

        tracker = CostTracker(log_path=tmp_path / "log.jsonl", spend_cap_usd=5.0)
        agent = DemoAgent(client=RaisingClient(), tracker=tracker)  # type: ignore[arg-type]
        with pytest.raises(AgentOutputError, match="truncated"):
            agent.run_prompt(ticker="AAPL", user_content="text")
        # the billed-but-unusable call still hit the ledger, conservatively
        assert tracker.calls == 1
        assert tracker.records[0].agent_name == "demo(unparseable)"
        assert tracker.records[0].output_tokens == DemoAgent.max_output_tokens

    def test_cached_text_block_helper(self) -> None:
        block = cached_text_block("big filing text")
        assert block == {
            "type": "text",
            "text": "big filing text",
            "cache_control": {"type": "ephemeral"},
        }

    def test_content_block_token_estimate(self, tmp_path: Path) -> None:
        agent = self._agent(tmp_path, FakeResponse(parsed_output=ClaimList(claims=[])))
        blocks = [cached_text_block("a" * 8_000), {"type": "text", "text": "b" * 2_000}]
        estimate = agent._estimate_input_tokens(blocks)
        assert estimate == int((10_000 + len(DemoAgent.system_prompt)) / 4)
