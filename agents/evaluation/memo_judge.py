"""LLM-as-judge for EDGAR-X research memos (claude-opus-4-8).

The judge receives the rendered memo PLUS the primary sources — the real
filing text of both years and the real metric values — so grounding is
verified against source data, not against the memo's own assertions. It is
NOT told what defects to expect; finding them is its job.

Scores four dimensions 1-5 with written justification and cited evidence:
factual grounding, internal consistency, honesty, and specificity (is this
memo about THIS company's filing, or generic large-cap filler?).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field

from agents.base_agent import BaseAgent, cached_text_block
from agents.data_access import CompanyYearRow, FilingText, ModelScore
from core.logging import get_logger

logger = get_logger(__name__)

Dimension = Literal[
    "factual_grounding", "internal_consistency", "honesty", "specificity"
]


class DimensionScore(BaseModel):
    """One rubric dimension: score, justification, and cited evidence."""

    dimension: Dimension
    score: int = Field(ge=1, le=5)
    justification: str
    evidence: list[str]


class JudgeOutput(BaseModel):
    """What the judge model returns."""

    scores: list[DimensionScore]
    overall_verdict: str
    defects: list[str]


class JudgeResult(BaseModel):
    """Code-supplied envelope around the judge output."""

    model_config = ConfigDict(frozen=True)

    ticker: str
    fiscal_year: int
    judged_at: str
    judge_model: str
    sources_provided: list[str]
    scores: list[DimensionScore]
    overall_verdict: str
    defects: list[str]


_SYSTEM_PROMPT = """\
You are the evaluation judge of EDGAR-X. You receive a generated research \
memo AND its primary sources: the verbatim 10-K section text for the current \
and prior fiscal year, and the real metric values (model score and financial \
ratios). Your job is adversarial verification, not summarisation.

Score each dimension 1-5 (5 = excellent):

1. factual_grounding — Does every claim trace to the provided sources? \
Check the memo's quoted excerpts VERBATIM against the filing text; flag any \
quote that is altered, stitched together from separate passages, or absent. \
Check every cited metric value against the real values. Check that each \
attribution faithfully reproduces its source rather than reformatting it.
2. internal_consistency — Does the memo contradict itself or the model \
score? Does the stated confidence level match the evidence presented?
3. honesty — Does it respect its stated limitations (ranked screen not \
classifier, ex-Financials universe, filing-date-only information) and avoid \
overclaiming anywhere, including in passing phrasing?
4. specificity — Is the memo specific to THIS company's actual filing and \
numbers, or generic financial language that could describe any large-cap? \
5 = every key point is company-specific and grounded in this filing; \
1 = generic filler. You MUST cite specific memo lines as evidence either way.

Output discipline (your response must fit within 1,400 tokens):
- justification: at most 60 words per dimension
- evidence: at most 2 short quotes per dimension
- defects: every concrete defect you found, one line each, most serious first
- overall_verdict: at most 60 words
Be strict: an unverifiable claim is a defect even if plausible. Do not award \
5 on factual_grounding if ANY quote or attribution fails verbatim check.
"""


class MemoJudge(BaseAgent[JudgeOutput]):
    """The Opus 4.8 judge call."""

    agent_name: ClassVar[str] = "judge"
    model: ClassVar[str] = "claude-opus-4-8"
    max_output_tokens: ClassVar[int] = 1500
    output_schema: ClassVar[type[BaseModel]] = JudgeOutput
    system_prompt: ClassVar[str] = _SYSTEM_PROMPT

    def judge(
        self,
        *,
        memo_markdown: str,
        current_filing: FilingText,
        prior_filing: FilingText | None,
        features: CompanyYearRow,
        score: ModelScore,
    ) -> JudgeResult:
        """Score one memo against its primary sources.

        Args:
            memo_markdown: The rendered memo under evaluation.
            current_filing: Real FY N filing text (primary source).
            prior_filing: Real FY N-1 filing text, if available.
            features: Real metric values for FY N.
            score: The real model score.

        Returns:
            Scores, justifications, defects — wrapped with provenance.
        """
        metric_lines = "\n".join(
            f"- {name}: {value}"
            for name, value in {
                "xgboost_score": round(score.score, 4),
                "revenue": features.revenue,
                "revenue_growth_1y": features.revenue_growth_1y,
                "gross_margin": features.gross_margin,
                "net_margin": features.net_margin,
                "debt_to_equity": features.debt_to_equity,
                "liabilities_to_assets": features.liabilities_to_assets,
                "roe_annualised": features.roe_annualised,
            }.items()
        )
        prior_block = (
            _render_source_filing(prior_filing)
            if prior_filing is not None
            else "[PRIOR-YEAR FILING: NOT AVAILABLE]"
        )
        output = self.run_prompt(
            ticker=features.ticker,
            user_content=[
                cached_text_block(_render_source_filing(current_filing)),
                cached_text_block(prior_block),
                {
                    "type": "text",
                    "text": (
                        f"[REAL METRIC VALUES]\n{metric_lines}\n\n"
                        f"[MEMO UNDER EVALUATION]\n{memo_markdown}\n\n"
                        f"Evaluate the memo against the sources above."
                    ),
                },
            ],
        )
        sources = [current_filing.source_reference, features.source_reference,
                   score.source_reference]
        if prior_filing is not None:
            sources.insert(1, prior_filing.source_reference)
        return JudgeResult(
            ticker=features.ticker,
            fiscal_year=features.fiscal_year,
            judged_at=datetime.now(UTC).isoformat(timespec="seconds"),
            judge_model=self.model,
            sources_provided=sources,
            scores=output.scores,
            overall_verdict=output.overall_verdict,
            defects=output.defects,
        )


def _render_source_filing(filing: FilingText) -> str:
    """Render one source filing with year markers for the judge."""
    return (
        f"[SOURCE FILING FY{filing.fiscal_year} "
        f"({filing.accession_number}) SECTION mdna]\n"
        f"{filing.mdna_text or 'MISSING'}\n\n"
        f"[SOURCE FILING FY{filing.fiscal_year} "
        f"({filing.accession_number}) SECTION risk_factors]\n"
        f"{filing.risk_factors_text or 'MISSING'}"
    )


def render_judge_report(result: JudgeResult, *, cost_usd: float) -> str:
    """Render the judge result as markdown.

    Args:
        result: The judge result.
        cost_usd: Actual judge call cost.

    Returns:
        Markdown report.
    """
    lines = [
        f"# Judge report — {result.ticker} FY{result.fiscal_year} memo",
        "",
        f"*Judged {result.judged_at} by {result.judge_model}. "
        f"Cost: ${cost_usd:.4f}.*",
        "",
        "| dimension | score |",
        "|---|---|",
    ]
    for item in result.scores:
        lines.append(f"| {item.dimension} | {item.score}/5 |")
    lines += ["", "## Justifications", ""]
    for item in result.scores:
        lines += [f"### {item.dimension} — {item.score}/5", "", item.justification, ""]
        lines += [f"- evidence: “{quote}”" for quote in item.evidence]
        lines += [""]
    lines += ["## Defects found", ""]
    lines += [f"- {defect}" for defect in result.defects] or ["- none"]
    lines += ["", "## Verdict", "", result.overall_verdict, "",
              "## Sources provided to the judge", ""]
    lines += [f"- {source}" for source in result.sources_provided]
    lines += [""]
    return "\n".join(lines)
