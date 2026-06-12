"""Unit tests for the three specialist agents (API and Snowflake fully mocked)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from agents.comparison_agent import ComparisonAgent, ComparisonOutput, FilingChange
from agents.cost_tracker import CostTracker
from agents.data_access import (
    CompanyYearRow,
    FilingText,
    ModelScore,
    load_company_year,
    load_filing_text,
    load_model_score,
)
from agents.extraction_agent import ExtractionAgent, ExtractionClaims, FilingClaim
from agents.signal_agent import MODEL_NATURE, SignalAgent, SignalOutput, SignalStatement


@dataclass
class FakeUsage:
    input_tokens: int = 1000
    output_tokens: int = 500
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0


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


def _filing(
    fiscal_year: int = 2025,
    mdna: str | None = "Net sales increased on services growth.",
    risk: str | None = "Litigation risk remains substantial.",
) -> FilingText:
    return FilingText(
        ticker="AAPL",
        fiscal_year=fiscal_year,
        accession_number=f"0000320193-{fiscal_year % 100}-000099",
        filing_date=date(fiscal_year, 11, 1),
        mdna_text=mdna,
        risk_factors_text=risk,
    )


def _features(fiscal_year: int = 2025, risk_word_total: float = 5.0) -> CompanyYearRow:
    return CompanyYearRow(
        ticker="AAPL",
        fiscal_year=fiscal_year,
        accession_number=f"0000320193-{fiscal_year % 100}-000099",
        revenue=416_161_000_000.0,
        revenue_growth_1y=0.064,
        gross_margin=0.469,
        net_margin=0.269,
        debt_to_equity=1.23,
        liabilities_to_assets=0.78,
        roe_annualised=1.52,
        litigation_mentions=2.0,
        impairment_mentions=1.0,
        decline_mentions=1.0,
        uncertain_mentions=1.0,
        recession_mentions=0.0,
        risk_word_total=risk_word_total,
        risk_words_per_1000=12.5,
    )


def _tracker(tmp_path: Path) -> CostTracker:
    return CostTracker(log_path=tmp_path / "log.jsonl", spend_cap_usd=5.0)


class TestExtractionAgent:
    """Attribution envelope and degradation without text."""

    def _claims(self) -> ExtractionClaims:
        return ExtractionClaims(
            claims=[
                FilingClaim(
                    claim="Services drove revenue growth",
                    category="business_driver",
                    source_section="mdna",
                    source_quote="Net sales increased on services growth.",
                )
            ],
            data_gaps=[],
        )

    def test_envelope_carries_code_supplied_provenance(self, tmp_path: Path) -> None:
        agent = ExtractionAgent(
            client=FakeAnthropicClient(FakeResponse(parsed_output=self._claims())),  # type: ignore[arg-type]
            tracker=_tracker(tmp_path),
        )
        result = agent.run(_filing())
        assert result.ticker == "AAPL"
        assert result.accession_number == "0000320193-25-000099"
        assert "RAW_FILINGS" in result.sources[0]
        assert result.claims[0].source_section == "mdna"
        assert result.claims[0].source_quote

    def test_filing_text_is_cached_and_section_tagged(self, tmp_path: Path) -> None:
        client = FakeAnthropicClient(FakeResponse(parsed_output=self._claims()))
        agent = ExtractionAgent(client=client, tracker=_tracker(tmp_path))  # type: ignore[arg-type]
        agent.run(_filing())
        content = client.messages.parse_calls[0]["messages"][0]["content"]
        assert content[0]["cache_control"] == {"type": "ephemeral"}
        assert "[SECTION mdna" in content[0]["text"]
        assert "[SECTION risk_factors" in content[0]["text"]

    def test_partial_text_records_gap_but_still_runs(self, tmp_path: Path) -> None:
        client = FakeAnthropicClient(FakeResponse(parsed_output=self._claims()))
        agent = ExtractionAgent(client=client, tracker=_tracker(tmp_path))  # type: ignore[arg-type]
        result = agent.run(_filing(mdna=None))
        assert any("mdna_text missing" in gap for gap in result.data_gaps)
        assert len(client.messages.parse_calls) == 1
        assert ": MISSING" in client.messages.parse_calls[0]["messages"][0]["content"][0]["text"]

    def test_no_text_at_all_makes_no_api_call(self, tmp_path: Path) -> None:
        client = FakeAnthropicClient(FakeResponse(parsed_output=self._claims()))
        agent = ExtractionAgent(client=client, tracker=_tracker(tmp_path))  # type: ignore[arg-type]
        result = agent.run(_filing(mdna=None, risk=None))
        assert client.messages.parse_calls == []
        assert result.claims == []
        assert any("no extraction performed" in gap for gap in result.data_gaps)


class TestComparisonAgent:
    """Code-computed deltas, per-year attribution, missing-year degradation."""

    def _output(self) -> ComparisonOutput:
        return ComparisonOutput(
            changes=[
                FilingChange(
                    change="New AI-regulation risk added",
                    change_type="new_risk",
                    source_section="risk_factors",
                    current_year_evidence="uncertain AI regulation could affect results",
                    prior_year_evidence=None,
                )
            ],
            summary="Risk language expanded.",
            data_gaps=[],
        )

    def test_deltas_computed_in_code_with_attribution(self, tmp_path: Path) -> None:
        client = FakeAnthropicClient(FakeResponse(parsed_output=self._output()))
        agent = ComparisonAgent(client=client, tracker=_tracker(tmp_path))  # type: ignore[arg-type]
        result = agent.run(
            current_filing=_filing(2025),
            prior_filing=_filing(2024),
            current_features=_features(2025, risk_word_total=8.0),
            prior_features=_features(2024, risk_word_total=5.0),
        )
        delta = next(d for d in result.feature_deltas if d.feature == "risk_word_total")
        assert delta.prior_value == 5.0
        assert delta.current_value == 8.0
        assert delta.delta == 3.0
        assert "INT_ML_FEATURES" in delta.source
        assert "not by the LLM" in delta.source

    def test_both_filings_cached_with_year_markers(self, tmp_path: Path) -> None:
        client = FakeAnthropicClient(FakeResponse(parsed_output=self._output()))
        agent = ComparisonAgent(client=client, tracker=_tracker(tmp_path))  # type: ignore[arg-type]
        agent.run(
            current_filing=_filing(2025),
            prior_filing=_filing(2024),
            current_features=_features(2025),
            prior_features=_features(2024),
        )
        content = client.messages.parse_calls[0]["messages"][0]["content"]
        assert "[FILING FY2024 SECTION mdna" in content[0]["text"]
        assert "[FILING FY2025 SECTION mdna" in content[1]["text"]
        assert content[0]["cache_control"] == {"type": "ephemeral"}
        assert content[1]["cache_control"] == {"type": "ephemeral"}

    def test_missing_prior_filing_makes_no_api_call(self, tmp_path: Path) -> None:
        client = FakeAnthropicClient(FakeResponse(parsed_output=self._output()))
        agent = ComparisonAgent(client=client, tracker=_tracker(tmp_path))  # type: ignore[arg-type]
        result = agent.run(
            current_filing=_filing(2025),
            prior_filing=None,
            current_features=_features(2025),
            prior_features=None,
        )
        assert client.messages.parse_calls == []
        assert result.changes == []
        assert "prior-year filing text unavailable" in result.data_gaps
        # numeric deltas still attributed, with prior side null
        assert all(d.prior_value is None for d in result.feature_deltas)

    def test_envelope_ties_each_year_to_its_accession(self, tmp_path: Path) -> None:
        client = FakeAnthropicClient(FakeResponse(parsed_output=self._output()))
        agent = ComparisonAgent(client=client, tracker=_tracker(tmp_path))  # type: ignore[arg-type]
        result = agent.run(
            current_filing=_filing(2025),
            prior_filing=_filing(2024),
            current_features=_features(2025),
            prior_features=_features(2024),
        )
        assert result.current_accession == "0000320193-25-000099"
        assert result.prior_accession == "0000320193-24-000099"
        assert result.changes[0].prior_year_evidence is None  # absence is evidence


class TestSignalAgent:
    """Metric attribution, code-enforced framing, and grounding verification."""

    def _output(self, echoed_growth: float | None = 0.064) -> SignalOutput:
        return SignalOutput(
            interpretation="The screen ranks AAPL in the upper range.",
            statements=[
                SignalStatement(
                    statement="Revenue momentum is the dominant driver",
                    source_metric="revenue_growth_1y",
                    metric_value=echoed_growth,
                ),
                SignalStatement(
                    statement="Score places the company high in the ranking",
                    source_metric="xgboost_score",
                    metric_value=0.8123,
                ),
            ],
            caveats=["survivorship-biased universe"],
        )

    def _score(self) -> ModelScore:
        return ModelScore(
            ticker="AAPL",
            fiscal_year=2025,
            score=0.8123,
            artifact="xgboost_revenue_direction.json",
        )

    def test_envelope_enforces_ranked_screen_framing(self, tmp_path: Path) -> None:
        client = FakeAnthropicClient(FakeResponse(parsed_output=self._output()))
        agent = SignalAgent(client=client, tracker=_tracker(tmp_path))  # type: ignore[arg-type]
        result = agent.run(score=self._score(), features=_features())
        assert result.model_nature == MODEL_NATURE
        assert "RANKED SCREEN" in result.model_nature
        assert result.xgboost_score == 0.8123
        assert any("XGBoost" in s for s in result.sources)
        assert any("INT_ML_FEATURES" in s for s in result.sources)

    def test_matching_metric_values_produce_no_warnings(self, tmp_path: Path) -> None:
        client = FakeAnthropicClient(FakeResponse(parsed_output=self._output()))
        agent = SignalAgent(client=client, tracker=_tracker(tmp_path))  # type: ignore[arg-type]
        result = agent.run(score=self._score(), features=_features())
        assert result.grounding_warnings == []

    def test_fabricated_metric_value_is_flagged(self, tmp_path: Path) -> None:
        client = FakeAnthropicClient(
            FakeResponse(parsed_output=self._output(echoed_growth=0.25))
        )
        agent = SignalAgent(client=client, tracker=_tracker(tmp_path))  # type: ignore[arg-type]
        result = agent.run(score=self._score(), features=_features())
        assert len(result.grounding_warnings) == 1
        assert "revenue_growth_1y=0.25" in result.grounding_warnings[0]
        assert "real value is 0.064" in result.grounding_warnings[0]

    def test_value_invented_for_missing_metric_is_flagged(self, tmp_path: Path) -> None:
        features = _features().model_copy(update={"net_margin": None})
        output = SignalOutput(
            interpretation="x",
            statements=[
                SignalStatement(
                    statement="Margins look strong",
                    source_metric="net_margin",
                    metric_value=0.30,
                )
            ],
            caveats=[],
        )
        client = FakeAnthropicClient(FakeResponse(parsed_output=output))
        agent = SignalAgent(client=client, tracker=_tracker(tmp_path))  # type: ignore[arg-type]
        result = agent.run(score=self._score(), features=features)
        assert len(result.grounding_warnings) == 1
        assert "real value is None" in result.grounding_warnings[0]

    def test_metric_values_rendered_in_prompt(self, tmp_path: Path) -> None:
        client = FakeAnthropicClient(FakeResponse(parsed_output=self._output()))
        agent = SignalAgent(client=client, tracker=_tracker(tmp_path))  # type: ignore[arg-type]
        agent.run(score=self._score(), features=_features())
        prompt_text = client.messages.parse_calls[0]["messages"][0]["content"]
        assert "xgboost_score: 0.8123" in prompt_text
        assert "revenue_growth_1y: 0.064" in prompt_text


@dataclass
class FakeCursor:
    rows: list[tuple[Any, ...]] = field(default_factory=list)
    executed: list[tuple[str, tuple[Any, ...]]] = field(default_factory=list)

    def execute(self, sql: str, params: tuple[Any, ...] | None = None) -> FakeCursor:
        self.executed.append((sql, params or ()))
        return self

    def fetchone(self) -> tuple[Any, ...] | None:
        return self.rows[0] if self.rows else None


@dataclass
class FakeConnection:
    cursor_obj: FakeCursor = field(default_factory=FakeCursor)
    closed: bool = False

    def cursor(self) -> FakeCursor:
        return self.cursor_obj

    def close(self) -> None:
        self.closed = True


class TestDataAccess:
    """Typed loaders against a fake connection."""

    def test_load_company_year_maps_row(self) -> None:
        row = ("AAPL", 2025, "acc-1", 1.0, 0.06, 0.4, 0.2, 1.2, 0.7, 1.5,
               2.0, 1.0, 1.0, 1.0, 0.0, 5.0, 12.5)
        conn = FakeConnection(FakeCursor(rows=[row]))
        record = load_company_year("aapl", 2025, connection=conn)
        assert record is not None
        assert record.ticker == "AAPL"
        assert record.risk_word_total == 5.0
        assert conn.cursor_obj.executed[0][1] == ("AAPL", 2025)
        assert conn.closed is False  # injected connection is caller-owned

    def test_load_company_year_missing_returns_none(self) -> None:
        assert load_company_year("AAPL", 1999, connection=FakeConnection()) is None

    def test_load_filing_text_maps_row(self) -> None:
        row = ("AAPL", 2025, "acc-1", date(2025, 11, 1), "mdna...", "risks...")
        conn = FakeConnection(FakeCursor(rows=[row]))
        record = load_filing_text("AAPL", 2025, connection=conn)
        assert record is not None
        assert record.accession_number == "acc-1"
        assert "RAW_FILINGS" in record.source_reference

    def test_load_model_score_without_artifact_returns_none(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        import agents.data_access as data_access

        monkeypatch.setattr(data_access, "ARTIFACT_DIR", tmp_path)
        assert load_model_score("AAPL", 2025, connection=FakeConnection()) is None
