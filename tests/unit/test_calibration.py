"""Unit tests for the calibration math (synthetic fixtures, no Snowflake)."""

from __future__ import annotations

import pytest

from self_improvement.calibration import (
    SMALL_N_THRESHOLD,
    OutcomeRecord,
    accuracy_stat,
    build_report,
    decile_calibration,
    group_by,
    realized_auc,
    wilson_interval,
)


def _rec(
    *,
    score: float,
    predicted: int,
    actual: int,
    split: str = "test",
    fy: int = 2024,
    sector: str = "Information Technology",
    ticker: str = "AAA",
) -> OutcomeRecord:
    return OutcomeRecord(
        ticker=ticker, fiscal_year=fy, sector=sector, predicted_score=score,
        predicted_direction=predicted, actual_direction=actual, data_split=split,
    )


class TestWilsonInterval:
    """Wilson score interval behaviour."""

    def test_zero_n_returns_zero_zero(self) -> None:
        assert wilson_interval(0, 0) == (0.0, 0.0)

    def test_bounds_stay_in_unit_interval(self) -> None:
        lo, hi = wilson_interval(10, 10)  # 100% observed
        assert 0.0 <= lo <= hi <= 1.0
        assert hi == 1.0 or hi < 1.0  # upper clamped

    def test_small_n_interval_is_wide(self) -> None:
        lo_small, hi_small = wilson_interval(4, 5)
        lo_big, hi_big = wilson_interval(400, 500)
        assert (hi_small - lo_small) > (hi_big - lo_big)

    def test_midpoint_near_phat_for_large_n(self) -> None:
        lo, hi = wilson_interval(415, 500)  # 83%
        assert lo < 0.83 < hi
        assert abs((lo + hi) / 2 - 0.83) < 0.03


class TestAccuracyStat:
    """Accuracy with confidence interval and small-sample flag."""

    def test_empty_set(self) -> None:
        stat = accuracy_stat([])
        assert stat.n == 0
        assert stat.accuracy is None
        assert stat.small_sample is True

    def test_all_correct(self) -> None:
        records = [_rec(score=0.9, predicted=1, actual=1) for _ in range(40)]
        stat = accuracy_stat(records)
        assert stat.accuracy == 1.0
        assert stat.small_sample is False

    def test_mixed_accuracy(self) -> None:
        records = (
            [_rec(score=0.9, predicted=1, actual=1) for _ in range(30)]
            + [_rec(score=0.9, predicted=1, actual=0) for _ in range(10)]
        )
        stat = accuracy_stat(records)
        assert stat.accuracy == 0.75
        assert stat.ci_low < 0.75 < stat.ci_high

    def test_small_sample_flag(self) -> None:
        records = [_rec(score=0.9, predicted=1, actual=1)
                   for _ in range(SMALL_N_THRESHOLD - 1)]
        assert accuracy_stat(records).small_sample is True


class TestRealizedAuc:
    """ROC-AUC recomputation on outcome records."""

    def test_perfect_separation(self) -> None:
        records = (
            [_rec(score=0.9, predicted=1, actual=1) for _ in range(20)]
            + [_rec(score=0.1, predicted=0, actual=0) for _ in range(20)]
        )
        assert realized_auc(records) == pytest.approx(1.0)

    def test_single_class_is_undefined(self) -> None:
        records = [_rec(score=0.9, predicted=1, actual=1) for _ in range(10)]
        assert realized_auc(records) is None

    def test_random_scores_near_half(self) -> None:
        records = [
            _rec(score=(i % 7) / 7, predicted=1, actual=i % 2)
            for i in range(200)
        ]
        auc = realized_auc(records)
        assert auc is not None
        assert 0.3 < auc < 0.7


class TestDecileCalibration:
    """Score-decile binning and monotonicity surfacing."""

    def test_too_few_rows_returns_empty(self) -> None:
        records = [_rec(score=0.5, predicted=1, actual=1) for _ in range(50)]
        assert decile_calibration(records) == []

    def test_monotonic_calibration_detected(self) -> None:
        # Higher scores genuinely grow more often.
        records = []
        for i in range(200):
            score = i / 200
            actual = 1 if (i / 200) > 0.5 else 0
            records.append(_rec(score=score, predicted=int(score >= 0.5), actual=actual))
        bins = decile_calibration(records)
        assert len(bins) >= 5
        rates = [b.actual_growth_rate for b in bins]
        assert rates == sorted(rates)  # monotonically non-decreasing

    def test_flat_scores_returns_empty(self) -> None:
        records = [_rec(score=0.5, predicted=1, actual=1) for _ in range(150)]
        assert decile_calibration(records) == []

    def test_small_bins_flagged(self) -> None:
        # 120 rows over 10 wide bins -> ~12/bin -> all small.
        records = [_rec(score=i / 120, predicted=1, actual=i % 2) for i in range(120)]
        bins = decile_calibration(records)
        assert any(b.small_sample for b in bins)


class TestGroupBy:
    """Grouping by fiscal year and sector."""

    def test_group_by_fiscal_year(self) -> None:
        records = (
            [_rec(score=0.9, predicted=1, actual=1, fy=2024) for _ in range(5)]
            + [_rec(score=0.9, predicted=1, actual=0, fy=2025) for _ in range(5)]
        )
        groups = group_by(records, "fiscal_year")
        assert [g.group for g in groups] == ["2024", "2025"]
        assert groups[0].stat.accuracy == 1.0
        assert groups[1].stat.accuracy == 0.0
        assert all(g.stat.small_sample for g in groups)


class TestBuildReport:
    """End-to-end report assembly with the honesty disciplines."""

    def _records(self) -> list[OutcomeRecord]:
        # 60 test rows (2 years) + 100 in-sample rows that must be excluded.
        test = (
            [_rec(score=0.8, predicted=1, actual=1, fy=2024) for _ in range(25)]
            + [_rec(score=0.8, predicted=1, actual=0, fy=2024) for _ in range(5)]
            + [_rec(score=0.7, predicted=1, actual=1, fy=2025) for _ in range(24)]
            + [_rec(score=0.7, predicted=1, actual=0, fy=2025) for _ in range(6)]
        )
        train = [_rec(score=0.9, predicted=1, actual=1, split="train", fy=2020)
                 for _ in range(100)]
        return test + train

    def test_in_sample_excluded_from_performance(self) -> None:
        report = build_report(self._records())
        assert report.out_of_sample_n == 60
        assert report.in_sample_n == 100
        # performance accuracy reflects only the 60 test rows (49/60)
        assert report.out_of_sample.accuracy == pytest.approx(49 / 60)
        assert report.in_sample_reference.accuracy == 1.0

    def test_warnings_lead_with_sample_and_reproduction_caveat(self) -> None:
        report = build_report(self._records())
        joined = " ".join(report.warnings)
        assert "SMALL sample" in joined
        assert "NOT independent validation" in joined
        assert "EXCLUDED" in joined

    def test_single_year_flags_no_drift(self) -> None:
        one_year = [_rec(score=0.8, predicted=1, actual=1, fy=2025) for _ in range(40)]
        report = build_report(one_year)
        assert any("decay CANNOT be assessed" in w for w in report.warnings)

    def test_high_base_rate_flagged(self) -> None:
        report = build_report(self._records())  # base rate 49/60 ~ 82%
        assert any("base rate" in w.lower() for w in report.warnings)

    def test_empty_records_verdict_is_honest(self) -> None:
        report = build_report([])
        assert "nothing to conclude" in report.verdict.lower()
        assert report.out_of_sample.accuracy is None
