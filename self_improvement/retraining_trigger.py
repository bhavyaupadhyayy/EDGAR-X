"""Retraining trigger: WORKING decision logic, SCAFFOLDED execution.

The decision logic (:func:`evaluate_trigger`) is real and unit-tested. It
reads the Task-2 calibration report plus a stored training-baseline state and
fires ``retrain_needed=True`` when EITHER:

* DECAY — realized out-of-sample ROC-AUC has dropped more than
  ``AUC_DECAY_THRESHOLD`` below the baseline the model was trained at, measured
  on a large-enough sample (``MIN_ROWS_FOR_DECAY``); or
* NEW DATA — a new fiscal year of out-of-sample outcomes (beyond the year the
  model was last evaluated through) has materialized with at least
  ``MIN_FRESH_ROWS`` realized rows.

Both rules are sample-size-gated so they never fire on noise. With the current
data (only the original FY2024-25 held-out set scored, FY2026 still pending),
the honest decision is "do not retrain" — and the trigger says exactly why.

EXECUTION IS SCAFFOLDED. :func:`maybe_retrain` defaults to ``dry_run=True`` and
only PRINTS the retrain command — it never launches training. Scheduled,
gated execution is wired in Layer 7 via the Airflow DAG
(``ingestion/airflow/dags/retraining_dag.py``); that is the only place a real
retrain should ever be kicked off.
"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import UTC, date, datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from core.logging import get_logger
from self_improvement.calibration import CalibrationReport

logger = get_logger("retraining_trigger")

ARTIFACT_DIR = Path(__file__).parent.parent / "ml" / "revenue_predictor" / "artifacts"
STATE_PATH = Path(__file__).parent / "training_state.json"
REPORT_JSON = Path(__file__).parent.parent / "docs" / "calibration_report.json"

#: The command Layer 7 would run to retrain. Emitted, never auto-executed here.
RETRAIN_COMMAND = (
    "python -m self_improvement.score_predictions "
    "&& python -m ml.revenue_predictor.train"
)

#: Decision thresholds. Gating keeps the trigger from firing on small-sample noise.
AUC_DECAY_THRESHOLD = 0.05
MIN_ROWS_FOR_DECAY = 100
MIN_FRESH_ROWS = 30


class TrainingState(BaseModel):
    """What the currently-deployed model was trained and evaluated on.

    Layer 7's Airflow DAG updates this after each successful retrain; today it
    reflects the real Layer-3 training run.
    """

    model_config = ConfigDict(frozen=True)

    trained_at: date
    trained_through_fiscal_year: int
    evaluated_through_fiscal_year: int
    baseline_auc: float
    baseline_accuracy: float
    model_artifact: str


class RetrainDecision(BaseModel):
    """The trigger's decision and its full reasoning."""

    model_config = ConfigDict(frozen=True)

    decided_at: str
    retrain_needed: bool
    reasons: list[str]
    fresh_out_of_sample_rows: int
    fresh_fiscal_years: list[int]
    realized_auc: float | None
    baseline_auc: float
    retrain_command: str


def _fresh_year_rows(
    report: CalibrationReport, evaluated_through: int
) -> tuple[list[int], int]:
    """Return fiscal years (and total rows) scored BEYOND the eval window.

    Args:
        report: The calibration report.
        evaluated_through: Last fiscal year the model was evaluated through.

    Returns:
        (sorted fresh fiscal years, total fresh out-of-sample rows).
    """
    fresh_years: list[int] = []
    total = 0
    for group in report.by_fiscal_year:
        year = int(group.group)
        if year > evaluated_through:
            fresh_years.append(year)
            total += group.stat.n
    return sorted(fresh_years), total


def evaluate_trigger(
    report: CalibrationReport, state: TrainingState
) -> RetrainDecision:
    """Decide whether a retrain is warranted. Pure and deterministic.

    Args:
        report: The Task-2 calibration report.
        state: The deployed model's training baseline.

    Returns:
        The decision with explicit reasons (firing or not-firing).
    """
    fresh_years, fresh_rows = _fresh_year_rows(report, state.evaluated_through_fiscal_year)
    reasons: list[str] = []
    fired = False

    # Rule 1 — DECAY (sample-size gated so noise cannot trip it).
    if (
        report.realized_auc is not None
        and report.out_of_sample_n >= MIN_ROWS_FOR_DECAY
        and report.realized_auc < state.baseline_auc - AUC_DECAY_THRESHOLD
    ):
        fired = True
        reasons.append(
            f"DECAY: realized out-of-sample ROC-AUC {report.realized_auc:.3f} is "
            f">{AUC_DECAY_THRESHOLD:.2f} below the training baseline "
            f"{state.baseline_auc:.3f} over {report.out_of_sample_n} rows."
        )

    # Rule 2 — NEW DATA (a new fiscal year of realized outcomes, gated on n).
    if fresh_rows >= MIN_FRESH_ROWS:
        fired = True
        reasons.append(
            f"NEW DATA: {fresh_rows} out-of-sample rows in fiscal year(s) "
            f"{fresh_years} have materialized beyond the model's evaluation "
            f"window (through FY{state.evaluated_through_fiscal_year}). Retrain "
            f"to incorporate the new ground truth."
        )

    # Honest "not firing" explanations.
    if not fired:
        if fresh_rows == 0:
            reasons.append(
                f"NO RETRAIN: no out-of-sample fiscal year beyond "
                f"FY{state.evaluated_through_fiscal_year} has materialized yet "
                f"(FY{state.evaluated_through_fiscal_year + 1} outcomes pending). "
                f"There is nothing fresh to retrain for."
            )
        elif fresh_rows < MIN_FRESH_ROWS:
            reasons.append(
                f"NO RETRAIN: only {fresh_rows} fresh out-of-sample row(s) in "
                f"{fresh_years} — below the {MIN_FRESH_ROWS} required to justify "
                f"a retrain. Will reassess as outcomes accumulate."
            )
        if report.realized_auc is not None:
            if report.out_of_sample_n < MIN_ROWS_FOR_DECAY:
                reasons.append(
                    f"Decay not assessable: only {report.out_of_sample_n} "
                    f"out-of-sample rows (<{MIN_ROWS_FOR_DECAY})."
                )
            else:
                reasons.append(
                    f"Performance within tolerance: realized AUC "
                    f"{report.realized_auc:.3f} vs baseline {state.baseline_auc:.3f}."
                )

    return RetrainDecision(
        decided_at=datetime.now(UTC).isoformat(timespec="seconds"),
        retrain_needed=fired,
        reasons=reasons,
        fresh_out_of_sample_rows=fresh_rows,
        fresh_fiscal_years=fresh_years,
        realized_auc=report.realized_auc,
        baseline_auc=state.baseline_auc,
        retrain_command=RETRAIN_COMMAND,
    )


def default_training_state() -> TrainingState:
    """Build the baseline state from the real Layer-3 training run.

    Reads reported metrics from the model artifact; the fiscal-year split is
    the documented Layer-3 split (train <= 2023, held out FY2024-2025).
    """
    metrics_path = ARTIFACT_DIR / "metrics.json"
    auc, accuracy = 0.726, 0.830
    if metrics_path.exists():
        by_name = {m["model_name"]: m for m in json.loads(metrics_path.read_text())}
        xgb = by_name.get("xgboost (tuned)", {})
        auc = xgb.get("roc_auc", auc)
        accuracy = xgb.get("accuracy", accuracy)
    return TrainingState(
        trained_at=date(2026, 6, 11),
        trained_through_fiscal_year=2023,
        evaluated_through_fiscal_year=2025,
        baseline_auc=auc,
        baseline_accuracy=accuracy,
        model_artifact="xgboost_revenue_direction.json",
    )


def load_training_state() -> TrainingState:
    """Load the training-baseline state, creating it from artifacts if absent."""
    if STATE_PATH.exists():
        return TrainingState.model_validate_json(STATE_PATH.read_text())
    state = default_training_state()
    STATE_PATH.write_text(state.model_dump_json(indent=2))
    return state


def load_calibration_report() -> CalibrationReport:
    """Load the Task-2 calibration report JSON.

    Raises:
        FileNotFoundError: If the report has not been generated yet.
    """
    if not REPORT_JSON.exists():
        raise FileNotFoundError(
            f"{REPORT_JSON} not found — run `python -m self_improvement.calibration`"
        )
    return CalibrationReport.model_validate_json(REPORT_JSON.read_text())


def maybe_retrain(decision: RetrainDecision, *, dry_run: bool = True) -> bool:
    """Execution hook — SCAFFOLDED. Defaults to dry-run; never auto-retrains.

    In ``dry_run`` mode (the default, and the only mode that should run outside
    Layer 7) this only emits the command. Real execution is the
    responsibility of the Layer-7 Airflow DAG, which owns scheduling, artifact
    promotion, and rollback. The non-dry-run branch is intentionally guarded
    and present only so the wiring is visible.

    Args:
        decision: The trigger decision.
        dry_run: When True (default) print the command and do nothing.

    Returns:
        True if a retrain was actually launched (only possible when
        ``dry_run=False``), else False.
    """
    if not decision.retrain_needed:
        print("Trigger decision: NO RETRAIN. Nothing to execute.")
        return False
    if dry_run:
        print(
            "Trigger decision: RETRAIN NEEDED (dry-run — not executing).\n"
            f"  Layer 7 (Airflow) would run:\n    {decision.retrain_command}"
        )
        return False
    # --- Real execution path. Reached only with an explicit dry_run=False, ---
    # --- which in production is invoked solely by the Layer-7 Airflow DAG.  ---
    logger.warning("retrain_executing", command=decision.retrain_command)
    subprocess.run(decision.retrain_command, shell=True, check=True)  # noqa: S602
    return True


def render_decision(decision: RetrainDecision) -> str:
    """Render the decision as a short readable block."""
    head = "RETRAIN NEEDED" if decision.retrain_needed else "NO RETRAIN"
    lines = [
        f"Retraining trigger decision: {head}",
        f"  decided_at: {decision.decided_at}",
        f"  fresh out-of-sample rows: {decision.fresh_out_of_sample_rows} "
        f"(fiscal years {decision.fresh_fiscal_years or 'none'})",
        f"  realized AUC: {decision.realized_auc} vs baseline {decision.baseline_auc}",
        "  reasons:",
    ]
    lines += [f"    - {r}" for r in decision.reasons]
    lines.append(f"  retrain command (Layer 7): {decision.retrain_command}")
    return "\n".join(lines)


def main() -> int:
    """Load the real report + state, decide, and emit (dry-run)."""
    report = load_calibration_report()
    state = load_training_state()
    decision = evaluate_trigger(report, state)
    print(render_decision(decision))
    print()
    maybe_retrain(decision, dry_run=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
