"""Unit tests for the memo judge (Anthropic API fully mocked)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from agents.cost_tracker import CostTracker
from agents.data_access import CompanyYearRow, FilingText, ModelScore
from agents.evaluation.memo_judge import (
    DimensionScore,
    JudgeOutput,
    MemoJudge,
    render_judge_report,
)


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


def _judge_output() -> JudgeOutput:
    return JudgeOutput(
        scores=[
            DimensionScore(
                dimension="factual_grounding",
                score=4,
                justification="Quotes mostly verbatim; one stitched quote.",
                evidence=["A significant majority... in addition"],
            ),
            DimensionScore(
                dimension="internal_consistency", score=5,
                justification="No contradictions.", evidence=[],
            ),
            DimensionScore(
                dimension="honesty", score=5,
                justification="Ranked-screen framing respected.", evidence=[],
            ),
            DimensionScore(
                dimension="specificity", score=5,
                justification="Tariff and State Aid details are Apple-specific.",
                evidence=["a $10.7 billion year-over-year decrease"],
            ),
        ],
        overall_verdict="Strong memo with minor quoting defects.",
        defects=["comparison quote stitched with ellipsis"],
    )


def _filing(year: int) -> FilingText:
    return FilingText(
        ticker="AAPL",
        fiscal_year=year,
        accession_number=f"acc-{year}",
        filing_date=date(year, 11, 1),
        mdna_text="mdna body",
        risk_factors_text="risk body",
    )


def _features() -> CompanyYearRow:
    return CompanyYearRow(
        ticker="AAPL", fiscal_year=2025, accession_number="acc-2025",
        revenue=1.0, revenue_growth_1y=0.06, gross_margin=0.4, net_margin=0.2,
        debt_to_equity=1.2, liabilities_to_assets=0.7, roe_annualised=1.5,
        litigation_mentions=1.0, impairment_mentions=1.0, decline_mentions=1.0,
        uncertain_mentions=1.0, recession_mentions=0.0, risk_word_total=4.0,
        risk_words_per_1000=10.0,
    )


class TestMemoJudge:
    """Judge request assembly and envelope (no real API calls)."""

    def _judge(self, tmp_path: Path) -> tuple[MemoJudge, FakeAnthropicClient]:
        client = FakeAnthropicClient(FakeResponse(parsed_output=_judge_output()))
        tracker = CostTracker(log_path=tmp_path / "log.jsonl", spend_cap_usd=5.0)
        return MemoJudge(client=client, tracker=tracker), client  # type: ignore[arg-type]

    def test_uses_opus_and_judge_cap(self, tmp_path: Path) -> None:
        judge, client = self._judge(tmp_path)
        judge.judge(
            memo_markdown="# memo",
            current_filing=_filing(2025),
            prior_filing=_filing(2024),
            features=_features(),
            score=ModelScore(ticker="AAPL", fiscal_year=2025, score=0.9081,
                             artifact="m.json"),
        )
        call = client.messages.parse_calls[0]
        assert call["model"] == "claude-opus-4-8"
        assert call["max_tokens"] == 1500

    def test_primary_sources_attached_and_cached(self, tmp_path: Path) -> None:
        judge, client = self._judge(tmp_path)
        result = judge.judge(
            memo_markdown="# memo body here",
            current_filing=_filing(2025),
            prior_filing=_filing(2024),
            features=_features(),
            score=ModelScore(ticker="AAPL", fiscal_year=2025, score=0.9081,
                             artifact="m.json"),
        )
        content = client.messages.parse_calls[0]["messages"][0]["content"]
        assert "[SOURCE FILING FY2025" in content[0]["text"]
        assert content[0]["cache_control"] == {"type": "ephemeral"}
        assert "[SOURCE FILING FY2024" in content[1]["text"]
        assert "[REAL METRIC VALUES]" in content[2]["text"]
        assert "[MEMO UNDER EVALUATION]" in content[2]["text"]
        assert len(result.sources_provided) == 4

    def test_score_bounds_enforced_by_schema(self) -> None:
        with pytest.raises(ValueError):
            DimensionScore(
                dimension="honesty", score=6, justification="x", evidence=[]
            )

    def test_report_renders_scores_and_defects(self, tmp_path: Path) -> None:
        judge, _client = self._judge(tmp_path)
        result = judge.judge(
            memo_markdown="# memo",
            current_filing=_filing(2025),
            prior_filing=None,
            features=_features(),
            score=ModelScore(ticker="AAPL", fiscal_year=2025, score=0.9081,
                             artifact="m.json"),
        )
        report = render_judge_report(result, cost_usd=0.1234)
        assert "| factual_grounding | 4/5 |" in report
        assert "stitched with ellipsis" in report
        assert "$0.1234" in report
        assert "claude-opus-4-8" in report
