"""ComparisonAgent: year-over-year diff of two real 10-K filings.

Input is the current and prior year's filing text plus the NUMERIC language
features of both (computed by dbt, not by the model). Output is a list of
changes, each tied to a section and to per-year verbatim evidence. The
numeric feature deltas are computed in code and attributed to
INT_ML_FEATURES; the model only interprets them. If the prior-year filing is
unavailable, the agent declares the gap and makes NO API call.
"""

from __future__ import annotations

from typing import ClassVar, Literal

from pydantic import BaseModel, ConfigDict

from agents.base_agent import BaseAgent, cached_text_block
from agents.data_access import CompanyYearRow, FilingText
from core.logging import get_logger

logger = get_logger(__name__)

_LANGUAGE_FEATURES = (
    "litigation_mentions",
    "impairment_mentions",
    "decline_mentions",
    "uncertain_mentions",
    "recession_mentions",
    "risk_word_total",
    "risk_words_per_1000",
)


class FeatureDelta(BaseModel):
    """A numeric language-feature change, computed in code (not by the LLM)."""

    model_config = ConfigDict(frozen=True)

    feature: str
    prior_value: float | None
    current_value: float | None
    delta: float | None
    source: str


class FilingChange(BaseModel):
    """One year-over-year change, attributed to section and per-year evidence."""

    change: str
    change_type: Literal[
        "new_risk", "dropped_risk", "tone_shift", "language_drift", "new_driver"
    ]
    source_section: Literal["mdna", "risk_factors"]
    current_year_evidence: str | None
    prior_year_evidence: str | None


class ComparisonOutput(BaseModel):
    """What the model returns."""

    changes: list[FilingChange]
    summary: str
    data_gaps: list[str]


class ComparisonResult(BaseModel):
    """Code-supplied provenance envelope around the model output."""

    model_config = ConfigDict(frozen=True)

    ticker: str
    current_fiscal_year: int
    prior_fiscal_year: int
    current_accession: str | None
    prior_accession: str | None
    sources: list[str]
    feature_deltas: list[FeatureDelta]
    changes: list[FilingChange]
    summary: str
    data_gaps: list[str]


_SYSTEM_PROMPT = """\
You are the comparison agent of EDGAR-X, a financial research system. You \
receive the MD&A and risk-factors text of the SAME company's 10-K for two \
consecutive fiscal years, marked [FILING FY<year> SECTION <name>], plus \
numeric language-feature deltas computed by the data pipeline.

Identify what actually changed between the filings:
- new_risk: a risk present this year, absent last year
- dropped_risk: a risk present last year, absent this year
- tone_shift: same topic, materially different tone or emphasis
- language_drift: wording changes the numeric deltas point to
- new_driver: a business driver newly introduced this year

Hard rules:
1. Every change MUST be grounded in the provided text of the correct year.
2. current_year_evidence / prior_year_evidence MUST be short verbatim \
excerpts (under 200 characters) from that year's filing; use null when the \
point is that the language is ABSENT in that year.
3. Interpret the numeric deltas, never contradict them; they were computed \
from the real filings.
4. If a section is marked MISSING, record that in data_gaps; never invent.
5. Report the 4-6 MOST material changes only. Be terse: every evidence \
excerpt under 120 characters, each change description one sentence, the \
summary under 60 words. Your entire JSON response must fit comfortably \
within 3,000 tokens — truncated output is discarded and wastes the call. \
This applies regardless of how long the filings are.
"""


class ComparisonAgent(BaseAgent[ComparisonOutput]):
    """Diffs two consecutive 10-Ks with per-year attributed evidence."""

    agent_name: ClassVar[str] = "comparison"
    max_output_tokens: ClassVar[int] = 4000
    output_schema: ClassVar[type[BaseModel]] = ComparisonOutput
    system_prompt: ClassVar[str] = _SYSTEM_PROMPT

    def run(
        self,
        *,
        current_filing: FilingText | None,
        prior_filing: FilingText | None,
        current_features: CompanyYearRow | None,
        prior_features: CompanyYearRow | None,
    ) -> ComparisonResult:
        """Compare this year's filing with last year's.

        Args:
            current_filing: FY N filing text (RAW_FILINGS), if available.
            prior_filing: FY N-1 filing text, if available.
            current_features: FY N language features (INT_ML_FEATURES).
            prior_features: FY N-1 language features.

        Returns:
            The attributed diff. When either filing is unavailable the result
            carries an explicit data gap and NO API call is made.
        """
        deltas = _compute_deltas(prior_features, current_features)
        sources = [
            ref
            for item in (current_filing, prior_filing, current_features, prior_features)
            if item is not None
            for ref in [item.source_reference]
        ]

        if current_filing is None or prior_filing is None:
            missing = []
            if current_filing is None:
                missing.append("current-year filing text unavailable")
            if prior_filing is None:
                missing.append("prior-year filing text unavailable")
            logger.warning("comparison_skipped", missing=missing)
            return ComparisonResult(
                ticker=(current_filing or prior_filing).ticker  # type: ignore[union-attr]
                if (current_filing or prior_filing)
                else (current_features.ticker if current_features else "UNKNOWN"),
                current_fiscal_year=current_filing.fiscal_year
                if current_filing
                else (current_features.fiscal_year if current_features else 0),
                prior_fiscal_year=prior_filing.fiscal_year
                if prior_filing
                else (prior_features.fiscal_year if prior_features else 0),
                current_accession=current_filing.accession_number if current_filing else None,
                prior_accession=prior_filing.accession_number if prior_filing else None,
                sources=sources,
                feature_deltas=deltas,
                changes=[],
                summary="No comparison performed: filing text missing for one year.",
                data_gaps=missing + ["no comparison performed"],
            )

        delta_lines = "\n".join(
            f"- {d.feature}: {d.prior_value} -> {d.current_value} (delta {d.delta})"
            for d in deltas
        )
        output = self.run_prompt(
            ticker=current_filing.ticker,
            user_content=[
                cached_text_block(_render_filing(prior_filing)),
                cached_text_block(_render_filing(current_filing)),
                {
                    "type": "text",
                    "text": (
                        f"Numeric language-feature deltas "
                        f"(FY{prior_filing.fiscal_year} -> FY{current_filing.fiscal_year}, "
                        f"computed by the pipeline from these filings):\n{delta_lines}\n\n"
                        f"Compare the two {current_filing.ticker} filings."
                    ),
                },
            ],
        )
        return ComparisonResult(
            ticker=current_filing.ticker,
            current_fiscal_year=current_filing.fiscal_year,
            prior_fiscal_year=prior_filing.fiscal_year,
            current_accession=current_filing.accession_number,
            prior_accession=prior_filing.accession_number,
            sources=sources,
            feature_deltas=deltas,
            changes=output.changes,
            summary=output.summary,
            data_gaps=output.data_gaps,
        )


def _compute_deltas(
    prior: CompanyYearRow | None, current: CompanyYearRow | None
) -> list[FeatureDelta]:
    """Compute numeric language-feature deltas in code, with attribution."""
    deltas: list[FeatureDelta] = []
    for feature in _LANGUAGE_FEATURES:
        prior_value = getattr(prior, feature, None) if prior else None
        current_value = getattr(current, feature, None) if current else None
        delta = (
            round(current_value - prior_value, 4)
            if prior_value is not None and current_value is not None
            else None
        )
        deltas.append(
            FeatureDelta(
                feature=feature,
                prior_value=prior_value,
                current_value=current_value,
                delta=delta,
                source="EDGAR_X.INTERMEDIATE.INT_ML_FEATURES (computed by dbt, not by the LLM)",
            )
        )
    return deltas


def _render_filing(filing: FilingText) -> str:
    """Render one filing's sections with year-scoped attribution markers."""
    mdna = filing.mdna_text or "MISSING"
    risk = filing.risk_factors_text or "MISSING"
    year = filing.fiscal_year
    return (
        f"[FILING FY{year} SECTION mdna ({filing.accession_number})"
        f"{' : MISSING' if not filing.mdna_text else ''}]\n{mdna}\n\n"
        f"[FILING FY{year} SECTION risk_factors ({filing.accession_number})"
        f"{' : MISSING' if not filing.risk_factors_text else ''}]\n{risk}"
    )
