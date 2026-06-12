"""Unit tests for the orchestrator's traceability verifier and memo renderer."""

from __future__ import annotations

from agents.comparison_agent import ComparisonResult, FeatureDelta, FilingChange
from agents.extraction_agent import ExtractionResult, FilingClaim
from agents.orchestrator import (
    LIMITATIONS,
    MemoFinding,
    ResearchMemo,
    render_memo,
    verify_traceability,
)
from agents.signal_agent import MODEL_NATURE, SignalResult, SignalStatement


def _extraction() -> ExtractionResult:
    return ExtractionResult(
        ticker="AAPL",
        fiscal_year=2025,
        accession_number="acc-25",
        sources=["EDGAR_X.RAW.RAW_FILINGS accession acc-25"],
        claims=[
            FilingClaim(
                claim="Services drove growth",
                category="business_driver",
                source_section="mdna",
                source_quote="Net sales increased on services growth",
            )
        ],
        data_gaps=[],
    )


def _comparison() -> ComparisonResult:
    return ComparisonResult(
        ticker="AAPL",
        current_fiscal_year=2025,
        prior_fiscal_year=2024,
        current_accession="acc-25",
        prior_accession="acc-24",
        sources=["EDGAR_X.RAW.RAW_FILINGS accession acc-24"],
        feature_deltas=[
            FeatureDelta(
                feature="risk_word_total",
                prior_value=5.0,
                current_value=8.0,
                delta=3.0,
                source="EDGAR_X.INTERMEDIATE.INT_ML_FEATURES (computed by dbt, not by the LLM)",
            )
        ],
        changes=[
            FilingChange(
                change="New AI regulation risk",
                change_type="new_risk",
                source_section="risk_factors",
                current_year_evidence="uncertain AI regulation could affect results",
                prior_year_evidence=None,
            )
        ],
        summary="Risk language expanded.",
        data_gaps=[],
    )


def _signal() -> SignalResult:
    return SignalResult(
        ticker="AAPL",
        fiscal_year=2025,
        xgboost_score=0.9081,
        model_nature=MODEL_NATURE,
        sources=["XGBoost revenue-direction model"],
        interpretation="Upper-range ranking.",
        statements=[
            SignalStatement(
                statement="Momentum dominates",
                source_metric="revenue_growth_1y",
                metric_value=0.064,
            )
        ],
        caveats=["survivorship bias"],
        grounding_warnings=[],
    )


class TestVerifyTraceability:
    """Attribution must exist in the cited specialist's output."""

    def test_verbatim_attribution_passes(self) -> None:
        findings = [
            MemoFinding(
                finding="Services are the growth engine",
                source_agent="extraction",
                source_attribution="Net sales increased on services growth",
            ),
            MemoFinding(
                finding="AI regulation is a new disclosed risk",
                source_agent="comparison",
                source_attribution="uncertain AI regulation could affect results",
            ),
            MemoFinding(
                finding="The screen ranks AAPL highly on momentum",
                source_agent="signal",
                source_attribution="revenue_growth_1y",
            ),
        ]
        warnings = verify_traceability(
            findings, extraction=_extraction(), comparison=_comparison(), signal=_signal()
        )
        assert warnings == []

    def test_invented_attribution_is_flagged(self) -> None:
        findings = [
            MemoFinding(
                finding="Margins will expand next year",
                source_agent="extraction",
                source_attribution="management guided margins up 200bps",
            )
        ]
        warnings = verify_traceability(
            findings, extraction=_extraction(), comparison=_comparison(), signal=_signal()
        )
        assert len(warnings) == 1
        assert "notical" not in warnings[0]
        assert "was not found" in warnings[0]

    def test_wrong_agent_citation_is_flagged(self) -> None:
        findings = [
            MemoFinding(
                finding="Risk language expanded",
                source_agent="signal",  # evidence actually lives in comparison output
                source_attribution="uncertain AI regulation could affect results",
            )
        ]
        warnings = verify_traceability(
            findings, extraction=_extraction(), comparison=_comparison(), signal=_signal()
        )
        assert len(warnings) == 1


class TestRenderMemo:
    """The rendered markdown keeps attribution, limitations, and sources."""

    def _memo(self, warnings: list[str] | None = None) -> ResearchMemo:
        return ResearchMemo(
            ticker="AAPL",
            fiscal_year=2025,
            generated_at="2026-06-12T00:00:00+00:00",
            summary="A summary.",
            findings=[
                MemoFinding(
                    finding="Services are the growth engine",
                    source_agent="extraction",
                    source_attribution="Net sales increased on services growth",
                )
            ],
            confidence="moderate",
            confidence_rationale="One-year comparison only.",
            limitations=LIMITATIONS,
            sources=["EDGAR_X.RAW.RAW_FILINGS accession acc-25"],
            traceability_warnings=warnings or [],
            extraction=_extraction(),
            comparison=_comparison(),
            signal=_signal(),
        )

    def test_renders_attribution_and_honesty_sections(self) -> None:
        text = render_memo(self._memo())
        assert "source: extraction agent" in text
        assert "Net sales increased on services growth" in text
        assert "RANKED SCREEN" in text
        assert "excluding Financials" in text
        assert "## Sources" in text
        assert "computed by dbt, not the LLM" in text
        assert "0.9081" in text

    def test_traceability_warnings_are_visible_not_hidden(self) -> None:
        text = render_memo(self._memo(warnings=["finding cites extraction but ..."]))
        assert "Traceability warnings" in text
