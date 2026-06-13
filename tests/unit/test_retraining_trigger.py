"""Unit tests for the retraining trigger decision logic (synthetic reports)."""

from __future__ import annotations

from datetime import date

from self_improvement.calibration import (
    AccuracyStat,
    CalibrationReport,
    GroupStat,
)
from self_improvement.retraining_trigger import (
    RetrainDecision,
    TrainingState,
    evaluate_trigger,
    maybe_retrain,
)

BASELINE = TrainingState(
    trained_at=date(2026, 6, 11),
    trained_through_fiscal_year=2023,
    evaluated_through_fiscal_year=2025,
    baseline_auc=0.726,
    baseline_accuracy=0.830,
    model_artifact="xgboost_revenue_direction.json",
)


def _stat(n: int, accuracy: float) -> AccuracyStat:
    return AccuracyStat(n=n, accuracy=accuracy, ci_low=accuracy - 0.05,
                        ci_high=accuracy + 0.05, small_sample=n < 30)


def _report(
    *,
    realized_auc: float | None,
    oos_n: int,
    by_year: list[tuple[int, int, float]],
) -> CalibrationReport:
    """Build a minimal calibration report. by_year = (fiscal_year, n, accuracy)."""
    return CalibrationReport(
        generated_at="2026-06-13T00:00:00+00:00",
        reported_test_auc=0.726,
        reported_test_accuracy=0.830,
        majority_baseline_accuracy=0.830,
        total_scored=oos_n,
        out_of_sample_n=oos_n,
        in_sample_n=5787,
        out_of_sample_years=[y for y, _, _ in by_year],
        out_of_sample_base_rate=0.83,
        out_of_sample=_stat(oos_n, 0.83),
        realized_auc=realized_auc,
        in_sample_reference=_stat(5787, 0.813),
        deciles=[],
        by_fiscal_year=[GroupStat(group=str(y), stat=_stat(n, a)) for y, n, a in by_year],
        by_sector=[],
        warnings=[],
        verdict="synthetic",
    )


class TestEvaluateTrigger:
    """The four required decision cases, plus reasoning checks."""

    def test_stable_does_not_fire(self) -> None:
        # Same FY2024-25 held-out set, AUC at baseline, no fresh years.
        report = _report(
            realized_auc=0.726, oos_n=447,
            by_year=[(2024, 414, 0.824), (2025, 33, 0.909)],
        )
        decision = evaluate_trigger(report, BASELINE)
        assert decision.retrain_needed is False
        assert decision.fresh_out_of_sample_rows == 0
        assert any("within tolerance" in r for r in decision.reasons)
        assert any("nothing fresh" in r.lower() for r in decision.reasons)

    def test_decay_breach_fires(self) -> None:
        # Large sample, realized AUC well below baseline -> decay.
        report = _report(
            realized_auc=0.60, oos_n=447,
            by_year=[(2024, 414, 0.70), (2025, 33, 0.70)],
        )
        decision = evaluate_trigger(report, BASELINE)
        assert decision.retrain_needed is True
        assert any(r.startswith("DECAY") for r in decision.reasons)

    def test_new_fiscal_year_of_data_fires(self) -> None:
        # A fresh year (2026) beyond the eval window, with enough rows.
        report = _report(
            realized_auc=0.72, oos_n=507,
            by_year=[(2024, 414, 0.824), (2025, 33, 0.909), (2026, 60, 0.80)],
        )
        decision = evaluate_trigger(report, BASELINE)
        assert decision.retrain_needed is True
        assert decision.fresh_out_of_sample_rows == 60
        assert decision.fresh_fiscal_years == [2026]
        assert any(r.startswith("NEW DATA") for r in decision.reasons)

    def test_insufficient_fresh_data_does_not_fire(self) -> None:
        # A new year exists but with too few rows to trust.
        report = _report(
            realized_auc=0.72, oos_n=460,
            by_year=[(2024, 414, 0.824), (2025, 33, 0.909), (2026, 13, 0.77)],
        )
        decision = evaluate_trigger(report, BASELINE)
        assert decision.retrain_needed is False
        assert decision.fresh_out_of_sample_rows == 13
        assert any("below the 30 required" in r for r in decision.reasons)

    def test_decay_not_assessable_on_small_sample(self) -> None:
        # Low AUC but tiny sample -> decay rule must NOT fire (gated).
        report = _report(
            realized_auc=0.55, oos_n=40,
            by_year=[(2025, 40, 0.60)],
        )
        decision = evaluate_trigger(report, BASELINE)
        assert decision.retrain_needed is False
        assert any("not assessable" in r for r in decision.reasons)

    def test_decay_and_new_data_can_both_fire(self) -> None:
        report = _report(
            realized_auc=0.60, oos_n=550,
            by_year=[(2024, 414, 0.70), (2025, 76, 0.70), (2026, 60, 0.62)],
        )
        decision = evaluate_trigger(report, BASELINE)
        assert decision.retrain_needed is True
        assert any(r.startswith("DECAY") for r in decision.reasons)
        assert any(r.startswith("NEW DATA") for r in decision.reasons)


class TestMaybeRetrain:
    """Execution hook stays scaffolded — never auto-runs."""

    def _fire(self, needed: bool) -> RetrainDecision:
        return RetrainDecision(
            decided_at="2026-06-13T00:00:00+00:00",
            retrain_needed=needed,
            reasons=["x"],
            fresh_out_of_sample_rows=0,
            fresh_fiscal_years=[],
            realized_auc=0.726,
            baseline_auc=0.726,
            retrain_command="python -m ml.revenue_predictor.train",
        )

    def test_dry_run_default_does_not_execute(self) -> None:
        assert maybe_retrain(self._fire(True)) is False  # dry_run defaults True

    def test_no_retrain_does_not_execute(self) -> None:
        assert maybe_retrain(self._fire(False), dry_run=False) is False
