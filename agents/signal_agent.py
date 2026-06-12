"""SignalAgent: plain-English interpretation of the XGBoost ranked screen.

Input is the model score for one company-fiscal-year plus the real financial
ratios from INT_FINANCIAL_RATIOS (via INT_ML_FEATURES). Output is a set of
statements, each attributed to a NAMED metric with its value echoed back.

Grounding is verified in code: every metric value the model echoes is
cross-checked against the real input, and mismatches are recorded as
grounding warnings in the result envelope — auditable by the Task 4 judge.

The ranked-screen framing is enforced by code, not trusted to the model: the
result envelope carries a fixed ``model_nature`` disclaimer, and the prompt
forbids classifier language.
"""

from __future__ import annotations

import math
from typing import ClassVar, Literal

from pydantic import BaseModel, ConfigDict

from agents.base_agent import BaseAgent
from agents.data_access import CompanyYearRow, ModelScore
from core.logging import get_logger

logger = get_logger(__name__)

#: Fixed, code-owned description of what the model is — never LLM-generated.
MODEL_NATURE = (
    "XGBoost revenue-direction model used as a RANKED SCREEN "
    "(test ROC-AUC 0.726 vs 0.500 majority baseline, FY2024-25 holdout). "
    "It is NOT a calibrated classifier: at the default threshold it predicts "
    "the majority class for nearly all companies. Scores order companies by "
    "relative likelihood of revenue growth; they are not probabilities to act on."
)

MetricName = Literal[
    "xgboost_score",
    "revenue",
    "revenue_growth_1y",
    "gross_margin",
    "net_margin",
    "debt_to_equity",
    "liabilities_to_assets",
    "roe_annualised",
]


class SignalStatement(BaseModel):
    """One interpretive statement, attributed to a named metric."""

    statement: str
    source_metric: MetricName
    metric_value: float | None


class SignalOutput(BaseModel):
    """What the model returns."""

    interpretation: str
    statements: list[SignalStatement]
    caveats: list[str]


class SignalResult(BaseModel):
    """Code-supplied provenance envelope around the model output."""

    model_config = ConfigDict(frozen=True)

    ticker: str
    fiscal_year: int
    xgboost_score: float
    model_nature: str
    sources: list[str]
    interpretation: str
    statements: list[SignalStatement]
    caveats: list[str]
    grounding_warnings: list[str]


_SYSTEM_PROMPT = """\
You are the signal agent of EDGAR-X, a financial research system. You receive \
the score that an XGBoost revenue-direction model assigned to one \
company-fiscal-year, together with the company's real financial ratios.

Your job: explain in plain English what the model sees, and which ratios \
plausibly drive the score given the model's known feature importance (revenue \
momentum dominates, then company size and macro regime; margins and leverage \
matter less).

Hard rules:
1. The model is a RANKED SCREEN, not a classifier. Never call the score a \
probability of growth, never say the model "predicts" growth will happen, \
never imply precision the AUC (0.726) does not support.
2. Every statement MUST name its source_metric and echo the metric_value \
EXACTLY as given in the input. Do not compute new numbers.
3. Only reference metrics whose values were provided; a missing ratio is a \
caveat, not something to estimate.
4. Include honest caveats (survivorship-biased training universe, ex-Financials \
scope, features only as of the filing date).
"""

#: Relative tolerance when verifying echoed metric values against real inputs.
_VERIFY_REL_TOL = 1e-3


class SignalAgent(BaseAgent[SignalOutput]):
    """Interprets the ranked-screen score against real ratios, with verification."""

    agent_name: ClassVar[str] = "signal"
    max_output_tokens: ClassVar[int] = 2000
    output_schema: ClassVar[type[BaseModel]] = SignalOutput
    system_prompt: ClassVar[str] = _SYSTEM_PROMPT

    def run(self, *, score: ModelScore, features: CompanyYearRow) -> SignalResult:
        """Interpret one company-year's score.

        Args:
            score: The real XGBoost score (from the saved artifact).
            features: The real ratio row (INT_ML_FEATURES).

        Returns:
            Attributed interpretation with code-verified grounding.
        """
        metric_values = self._metric_values(score, features)
        metric_lines = "\n".join(
            f"- {name}: {'NULL (not available)' if value is None else value}"
            for name, value in metric_values.items()
        )
        output = self.run_prompt(
            ticker=features.ticker,
            user_content=(
                f"Company: {features.ticker}, fiscal year {features.fiscal_year}.\n"
                f"Metrics (real values; echo them exactly):\n{metric_lines}\n\n"
                f"Interpret the model score for this company-year."
            ),
        )
        warnings = self._verify_grounding(output, metric_values)
        return SignalResult(
            ticker=features.ticker,
            fiscal_year=features.fiscal_year,
            xgboost_score=score.score,
            model_nature=MODEL_NATURE,
            sources=[score.source_reference, features.source_reference],
            interpretation=output.interpretation,
            statements=output.statements,
            caveats=output.caveats,
            grounding_warnings=warnings,
        )

    @staticmethod
    def _metric_values(
        score: ModelScore, features: CompanyYearRow
    ) -> dict[str, float | None]:
        """Assemble the exact metric map shown to (and verified against) the model."""
        return {
            "xgboost_score": round(score.score, 4),
            "revenue": features.revenue,
            "revenue_growth_1y": features.revenue_growth_1y,
            "gross_margin": features.gross_margin,
            "net_margin": features.net_margin,
            "debt_to_equity": features.debt_to_equity,
            "liabilities_to_assets": features.liabilities_to_assets,
            "roe_annualised": features.roe_annualised,
        }

    @staticmethod
    def _verify_grounding(
        output: SignalOutput, metric_values: dict[str, float | None]
    ) -> list[str]:
        """Cross-check every echoed metric value against the real inputs.

        Args:
            output: The parsed model output.
            metric_values: The real values that were provided.

        Returns:
            One warning per statement whose value does not match reality.
        """
        warnings: list[str] = []
        for statement in output.statements:
            real = metric_values.get(statement.source_metric)
            echoed = statement.metric_value
            if real is None and echoed is None:
                continue
            if real is None or echoed is None:
                warnings.append(
                    f"statement cites {statement.source_metric}={echoed} but the "
                    f"real value is {real}: {statement.statement!r}"
                )
                continue
            if not math.isclose(real, echoed, rel_tol=_VERIFY_REL_TOL, abs_tol=1e-6):
                warnings.append(
                    f"statement cites {statement.source_metric}={echoed} but the "
                    f"real value is {real}: {statement.statement!r}"
                )
        if warnings:
            logger.warning("signal_grounding_mismatch", count=len(warnings))
        return warnings
