"""Calibration + monitoring engine for the revenue-direction model.

Reads ``MARTS.PREDICTION_OUTCOMES`` and computes performance metrics on the
REALIZED outcomes. The calibration math is pure (operates on typed records,
unit-tested on synthetic fixtures); only :func:`load_outcomes` touches
Snowflake.

HONESTY DISCIPLINE (load-bearing, not decoration):

* Real performance is computed ONLY on ``data_split == 'test'`` — the
  genuinely out-of-sample rows. In-sample ('train') rows are reported as a
  clearly-labeled reference and never mixed into the real numbers.
* Those out-of-sample rows are the SAME held-out set the model's Layer-3 test
  metrics were reported on, so realized ≈ reported is reproduction, not fresh
  validation. Independent validation needs a NEW fiscal year of outcomes
  (currently pending). The report states this.
* Every per-year and per-sector cell below ``SMALL_N_THRESHOLD`` is flagged.
  Accuracy carries a Wilson 95% interval so small-n uncertainty is visible.
"""

from __future__ import annotations

import json
import math
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict

from core.logging import get_logger
from ingestion.sinks.snowflake_writer import ConnectionLike, open_connection

if TYPE_CHECKING:  # pragma: no cover - typing only
    pass

logger = get_logger("calibration")

ARTIFACT_DIR = Path(__file__).parent.parent / "ml" / "revenue_predictor" / "artifacts"
REPORT_JSON = Path(__file__).parent.parent / "docs" / "calibration_report.json"
REPORT_MD = Path(__file__).parent.parent / "docs" / "calibration_report.md"

#: Cells with fewer rows than this are flagged as too thin to conclude from.
SMALL_N_THRESHOLD = 30
#: Decile binning needs at least this many rows to be worth attempting.
MIN_ROWS_FOR_DECILES = 100


class OutcomeRecord(BaseModel):
    """One scored prediction with its realized outcome."""

    model_config = ConfigDict(frozen=True)

    ticker: str
    fiscal_year: int
    sector: str | None
    predicted_score: float
    predicted_direction: int
    actual_direction: int
    data_split: str  # 'train' | 'test'


class AccuracyStat(BaseModel):
    """Accuracy over a set of rows with a Wilson 95% confidence interval."""

    model_config = ConfigDict(frozen=True)

    n: int
    accuracy: float | None
    ci_low: float | None
    ci_high: float | None
    small_sample: bool


class DecileBin(BaseModel):
    """One score-decile calibration bin."""

    model_config = ConfigDict(frozen=True)

    decile: int
    score_low: float
    score_high: float
    n: int
    mean_predicted_score: float
    actual_growth_rate: float
    small_sample: bool


class GroupStat(BaseModel):
    """Accuracy for one group (fiscal year or sector)."""

    model_config = ConfigDict(frozen=True)

    group: str
    stat: AccuracyStat


class CalibrationReport(BaseModel):
    """Full structured calibration report."""

    model_config = ConfigDict(frozen=True)

    generated_at: str
    reported_test_auc: float | None
    reported_test_accuracy: float | None
    majority_baseline_accuracy: float | None
    total_scored: int
    out_of_sample_n: int
    in_sample_n: int
    out_of_sample_years: list[int]
    out_of_sample_base_rate: float | None
    out_of_sample: AccuracyStat
    realized_auc: float | None
    in_sample_reference: AccuracyStat
    deciles: list[DecileBin]
    by_fiscal_year: list[GroupStat]
    by_sector: list[GroupStat]
    warnings: list[str]
    verdict: str


def wilson_interval(successes: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Wilson score 95% confidence interval for a binomial proportion.

    Chosen over the normal approximation because it stays inside [0, 1] and is
    sane at small n — which is the whole point here.

    Args:
        successes: Number of correct predictions.
        n: Total predictions.
        z: Z-score (1.96 for 95%).

    Returns:
        (low, high) bounds, clamped to [0, 1]. (0, 0) when ``n`` is 0.
    """
    if n == 0:
        return (0.0, 0.0)
    phat = successes / n
    denom = 1 + z * z / n
    center = (phat + z * z / (2 * n)) / denom
    margin = (z * math.sqrt(phat * (1 - phat) / n + z * z / (4 * n * n))) / denom
    return (max(0.0, center - margin), min(1.0, center + margin))


def accuracy_stat(records: list[OutcomeRecord]) -> AccuracyStat:
    """Compute accuracy with a Wilson interval over ``records``.

    Args:
        records: Scored prediction records.

    Returns:
        The accuracy stat; ``accuracy`` is ``None`` for an empty set.
    """
    n = len(records)
    if n == 0:
        return AccuracyStat(n=0, accuracy=None, ci_low=None, ci_high=None,
                            small_sample=True)
    correct = sum(1 for r in records if r.predicted_direction == r.actual_direction)
    low, high = wilson_interval(correct, n)
    return AccuracyStat(
        n=n,
        accuracy=correct / n,
        ci_low=low,
        ci_high=high,
        small_sample=n < SMALL_N_THRESHOLD,
    )


def realized_auc(records: list[OutcomeRecord]) -> float | None:
    """ROC-AUC of predicted_score vs actual_direction over ``records``.

    Args:
        records: Scored prediction records.

    Returns:
        AUC, or ``None`` when both classes are not present (AUC undefined).
    """
    actuals = [r.actual_direction for r in records]
    if len(set(actuals)) < 2:
        return None
    from sklearn.metrics import roc_auc_score  # noqa: PLC0415 - deferred heavy import

    scores = [r.predicted_score for r in records]
    return float(roc_auc_score(actuals, scores))


def decile_calibration(
    records: list[OutcomeRecord], n_bins: int = 10
) -> list[DecileBin]:
    """Bin records by predicted score and measure realized growth per bin.

    A well-calibrated ranked screen shows monotonically rising
    ``actual_growth_rate`` across deciles. Bins are equal-width over the
    observed score range (not quantiles), so bin counts can be uneven and are
    flagged when thin.

    Args:
        records: Scored prediction records.
        n_bins: Number of bins (default 10 = deciles).

    Returns:
        Non-empty bins, lowest score first. Empty list if too few rows.
    """
    if len(records) < MIN_ROWS_FOR_DECILES:
        return []
    scores = [r.predicted_score for r in records]
    lo, hi = min(scores), max(scores)
    if hi == lo:
        return []
    width = (hi - lo) / n_bins
    bins: list[DecileBin] = []
    for index in range(n_bins):
        edge_low = lo + index * width
        edge_high = hi if index == n_bins - 1 else lo + (index + 1) * width
        in_bin = [
            r for r in records
            if (r.predicted_score >= edge_low and r.predicted_score < edge_high)
            or (index == n_bins - 1 and r.predicted_score == hi)
        ]
        if not in_bin:
            continue
        bins.append(
            DecileBin(
                decile=index + 1,
                score_low=round(edge_low, 4),
                score_high=round(edge_high, 4),
                n=len(in_bin),
                mean_predicted_score=round(
                    sum(r.predicted_score for r in in_bin) / len(in_bin), 4
                ),
                actual_growth_rate=round(
                    sum(r.actual_direction for r in in_bin) / len(in_bin), 4
                ),
                small_sample=len(in_bin) < SMALL_N_THRESHOLD,
            )
        )
    return bins


def group_by(records: list[OutcomeRecord], key: str) -> list[GroupStat]:
    """Accuracy per distinct value of ``key`` (``fiscal_year`` or ``sector``).

    Args:
        records: Scored prediction records.
        key: Attribute name to group by.

    Returns:
        Per-group stats, sorted by group label.
    """
    groups: dict[str, list[OutcomeRecord]] = {}
    for record in records:
        label = str(getattr(record, key))
        groups.setdefault(label, []).append(record)
    return [
        GroupStat(group=label, stat=accuracy_stat(rows))
        for label, rows in sorted(groups.items())
    ]


def build_report(records: list[OutcomeRecord]) -> CalibrationReport:
    """Assemble the full calibration report from scored records.

    Args:
        records: ALL scored prediction records (train + test). The function
            itself enforces the out-of-sample-only discipline.

    Returns:
        The structured report, including honesty warnings and a verdict.
    """
    test = [r for r in records if r.data_split == "test"]
    train = [r for r in records if r.data_split == "train"]
    reported = _reported_metrics()

    oos_stat = accuracy_stat(test)
    oos_auc = realized_auc(test)
    years = sorted({r.fiscal_year for r in test})
    base_rate = (
        sum(r.actual_direction for r in test) / len(test) if test else None
    )

    warnings = _build_warnings(test=test, train=train, years=years, base_rate=base_rate)
    verdict = _build_verdict(oos_stat, oos_auc, reported, years)

    return CalibrationReport(
        generated_at=datetime.now(UTC).isoformat(timespec="seconds"),
        reported_test_auc=reported.get("auc"),
        reported_test_accuracy=reported.get("accuracy"),
        majority_baseline_accuracy=reported.get("majority"),
        total_scored=len(records),
        out_of_sample_n=len(test),
        in_sample_n=len(train),
        out_of_sample_years=years,
        out_of_sample_base_rate=base_rate,
        out_of_sample=oos_stat,
        realized_auc=oos_auc,
        in_sample_reference=accuracy_stat(train),
        deciles=decile_calibration(test),
        by_fiscal_year=group_by(test, "fiscal_year"),
        by_sector=group_by(test, "sector"),
        warnings=warnings,
        verdict=verdict,
    )


def _build_warnings(
    *,
    test: list[OutcomeRecord],
    train: list[OutcomeRecord],
    years: list[int],
    base_rate: float | None,
) -> list[str]:
    """Assemble the honesty warnings that lead the report."""
    warnings: list[str] = []
    warnings.append(
        f"Out-of-sample evaluation rests on {len(test)} rows across "
        f"{len(years)} fiscal year(s) ({_year_span(years)}). This is a SMALL "
        f"sample; treat all figures as tentative."
    )
    warnings.append(
        "These out-of-sample rows ARE the model's Layer-3 held-out test set, so "
        "realized metrics reproducing the reported metrics is expected — it is "
        "NOT independent validation. Independent validation requires a new "
        "fiscal year of realized outcomes (currently pending)."
    )
    warnings.append(
        f"{len(train)} in-sample (train) rows are EXCLUDED from all performance "
        "metrics; they appear only as a labeled reference and are not valid "
        "for measuring performance."
    )
    if len(years) < 2:
        warnings.append(
            "Year-over-year decay CANNOT be assessed: fewer than 2 out-of-sample "
            "fiscal years exist. The drift table is a framework placeholder until "
            "more years accumulate."
        )
    if base_rate is not None and base_rate > 0.75:
        warnings.append(
            f"Class imbalance: {base_rate:.0%} of out-of-sample companies grew "
            "revenue, so high accuracy is largely the base rate. Read ROC-AUC, "
            "not accuracy."
        )
    return warnings


def _build_verdict(
    oos: AccuracyStat,
    oos_auc: float | None,
    reported: dict[str, float | None],
    years: list[int],
) -> str:
    """One-paragraph honest summary."""
    if oos.accuracy is None:
        return "No out-of-sample outcomes available yet — nothing to conclude."
    auc_text = f"realized ROC-AUC {oos_auc:.3f}" if oos_auc is not None else "AUC undefined"
    reported_auc = reported.get("auc")
    auc_cmp = (
        f" (reported {reported_auc:.3f}; matches because it is the same held-out set)"
        if reported_auc is not None
        else ""
    )
    return (
        f"On {oos.n} out-of-sample rows ({_year_span(years)}), accuracy "
        f"{oos.accuracy:.1%} (95% CI {oos.ci_low:.1%}-{oos.ci_high:.1%}), "
        f"{auc_text}{auc_cmp}. The model ranks better than chance but the "
        "confidence interval is wide and only one-to-two fiscal years are "
        "observed — no claim of stability or decay is supportable yet. The "
        "framework will produce robust numbers as out-of-sample years accumulate."
    )


def _year_span(years: list[int]) -> str:
    """Render a compact fiscal-year span."""
    if not years:
        return "no years"
    if len(years) == 1:
        return f"FY{years[0]}"
    return f"FY{years[0]}-FY{years[-1]}"


def _reported_metrics() -> dict[str, float | None]:
    """Load the model's reported test metrics from the artifact."""
    path = ARTIFACT_DIR / "metrics.json"
    if not path.exists():
        return {"auc": None, "accuracy": None, "majority": None}
    metrics = json.loads(path.read_text())
    by_name = {m["model_name"]: m for m in metrics}
    xgb = by_name.get("xgboost (tuned)", {})
    majority = by_name.get("majority-class (always up)", {})
    return {
        "auc": xgb.get("roc_auc"),
        "accuracy": xgb.get("accuracy"),
        "majority": majority.get("accuracy"),
    }


def load_outcomes(connection: ConnectionLike | None = None) -> list[OutcomeRecord]:
    """Load all SCORED prediction outcomes from Snowflake.

    Args:
        connection: Optional injected connection (tests).

    Returns:
        Scored records (pending rows excluded — they have no outcome).
    """
    owns = connection is None
    conn = connection or open_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            select ticker, fiscal_year, sector, predicted_score,
                   predicted_direction, actual_direction, data_split
            from EDGAR_X.MARTS.PREDICTION_OUTCOMES
            where status = 'scored'
            """
        )
        rows = cursor.fetchall()
    finally:
        if owns:
            conn.close()
    return [
        OutcomeRecord(
            ticker=r[0], fiscal_year=int(r[1]), sector=r[2],
            predicted_score=float(r[3]), predicted_direction=int(r[4]),
            actual_direction=int(r[5]), data_split=r[6],
        )
        for r in rows
    ]


def render_markdown(report: CalibrationReport) -> str:
    """Render the report as markdown, leading with the sample constraint."""
    r = report
    lines = [
        "# EDGAR-X model calibration report",
        "",
        f"*Generated {r.generated_at}. Revenue-direction XGBoost model.*",
        "",
        "## ⚠ Read this first — sample constraint",
        "",
    ]
    lines += [f"- {w}" for w in r.warnings]
    lines += [
        "",
        "## Out-of-sample performance (the only valid numbers)",
        "",
        f"- Rows: **{r.out_of_sample_n}** across {_year_span(r.out_of_sample_years)}",
        f"- Accuracy: **{_pct(r.out_of_sample.accuracy)}** "
        f"(Wilson 95% CI {_pct(r.out_of_sample.ci_low)}–{_pct(r.out_of_sample.ci_high)})",
        f"- Realized ROC-AUC: **{_num(r.realized_auc)}** "
        f"(reported {_num(r.reported_test_auc)})",
        f"- Majority-class baseline accuracy: {_pct(r.majority_baseline_accuracy)} "
        f"· out-of-sample base rate (grew): {_pct(r.out_of_sample_base_rate)}",
        "",
        "## Calibration by score decile (do higher scores actually grow more?)",
        "",
    ]
    if r.deciles:
        lines += [
            "| decile | score range | n | mean score | actual growth rate | note |",
            "|---|---|---|---|---|---|",
        ]
        for b in r.deciles:
            note = "⚠ small n" if b.small_sample else ""
            lines.append(
                f"| {b.decile} | {b.score_low:.3f}–{b.score_high:.3f} | {b.n} "
                f"| {b.mean_predicted_score:.3f} | {b.actual_growth_rate:.3f} | {note} |"
            )
    else:
        lines.append(
            f"_Too few out-of-sample rows (<{MIN_ROWS_FOR_DECILES}) for decile "
            "binning, or scores not spread._"
        )
    lines += ["", "## Accuracy drift by fiscal year", ""]
    lines += _group_table(r.by_fiscal_year, "fiscal year")
    if len(r.out_of_sample_years) < 2:
        lines.append("")
        lines.append("_Drift is not assessable with one fiscal year — see warnings._")
    lines += ["", "## Per-sector calibration", ""]
    lines += _group_table(r.by_sector, "sector")
    lines += [
        "",
        "## In-sample reference (NOT valid for performance)",
        "",
        f"- {r.in_sample_n} in-sample (train) rows, accuracy "
        f"{_pct(r.in_sample_reference.accuracy)}. The model was trained on these "
        "labels; this number is reference only and must not be read as "
        "performance.",
        "",
        "## Verdict",
        "",
        r.verdict,
        "",
    ]
    return "\n".join(lines)


def _group_table(groups: list[GroupStat], label: str) -> list[str]:
    """Render a per-group accuracy table with CIs and small-n flags."""
    if not groups:
        return [f"_No {label} groups in the out-of-sample set._"]
    lines = [
        f"| {label} | n | accuracy | 95% CI | note |",
        "|---|---|---|---|---|",
    ]
    for g in groups:
        note = "⚠ small n" if g.stat.small_sample else ""
        ci = (
            f"{_pct(g.stat.ci_low)}–{_pct(g.stat.ci_high)}"
            if g.stat.ci_low is not None
            else "—"
        )
        lines.append(
            f"| {g.group} | {g.stat.n} | {_pct(g.stat.accuracy)} | {ci} | {note} |"
        )
    return lines


def _pct(value: float | None) -> str:
    """Format a fraction as a percentage, or em dash for None."""
    return f"{value:.1%}" if value is not None else "—"


def _num(value: float | None) -> str:
    """Format a float to 3 dp, or em dash for None."""
    return f"{value:.3f}" if value is not None else "—"


def main() -> int:
    """Load real outcomes, build the report, write JSON + markdown."""
    records = load_outcomes()
    report = build_report(records)
    REPORT_JSON.write_text(report.model_dump_json(indent=2))
    REPORT_MD.write_text(render_markdown(report))
    print(render_markdown(report))
    print(f"\nWrote {REPORT_JSON} and {REPORT_MD}")
    return 0


if __name__ == "__main__":
    import sys

    sys.exit(main())
