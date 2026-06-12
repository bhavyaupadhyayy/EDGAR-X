"""Unit tests for the revenue-predictor feature engineering (no Snowflake)."""

from __future__ import annotations

import pandas as pd
import pytest

from ml.revenue_predictor.feature_engineering import (
    LANGUAGE_FEATURES,
    NUMERIC_FEATURES,
    encode_features,
    feature_groups,
    summarise,
    time_split,
)


@pytest.fixture()
def frame() -> pd.DataFrame:
    rows = []
    for year in (2020, 2021, 2022, 2023, 2024, 2025):
        rows.append(
            {
                "ml_row_id": f"AAA|{year}",
                "ticker": "AAA",
                "fiscal_year": year,
                "sector": "Information Technology",
                "label": 1 if year % 2 == 0 else 0,
                "revenue": 1e9 + year,
                "revenue_growth_1y": 0.05,
                "net_margin": 0.2,
                "risk_word_total": None if year < 2022 else 4,
                "fed_funds_rate": 4.3,
            }
        )
    rows.append(
        {
            "ml_row_id": "BBB|2024",
            "ticker": "BBB",
            "fiscal_year": 2024,
            "sector": "Energy",
            "label": 0,
            "revenue": 5e8,
            "revenue_growth_1y": None,
            "net_margin": -0.1,
            "risk_word_total": 7,
            "fed_funds_rate": 4.3,
        }
    )
    return pd.DataFrame(rows)


class TestTimeSplit:
    """Strict fiscal-year separation."""

    def test_train_years_strictly_precede_test_years(self, frame: pd.DataFrame) -> None:
        train, test = time_split(frame, test_years=(2024, 2025))
        assert sorted(train["fiscal_year"].unique()) == [2020, 2021, 2022, 2023]
        assert sorted(test["fiscal_year"].unique()) == [2024, 2025]
        assert train["fiscal_year"].max() < test["fiscal_year"].min()

    def test_no_row_overlap(self, frame: pd.DataFrame) -> None:
        train, test = time_split(frame, test_years=(2024, 2025))
        assert set(train["ml_row_id"]).isdisjoint(set(test["ml_row_id"]))
        assert len(train) + len(test) == len(frame)


class TestEncodeFeatures:
    """Encoding and NULL behaviour."""

    def test_sector_one_hot_and_numeric_columns(self, frame: pd.DataFrame) -> None:
        matrix, labels = encode_features(frame)
        assert "sector_Information Technology" in matrix.columns
        assert "sector_Energy" in matrix.columns
        assert set(NUMERIC_FEATURES) <= set(matrix.columns)
        assert labels.tolist() == frame["label"].tolist()

    def test_nans_preserved_not_imputed(self, frame: pd.DataFrame) -> None:
        matrix, _ = encode_features(frame)
        # risk_word_total is NULL for 2020/2021 rows and must stay NaN.
        assert matrix["risk_word_total"].isna().sum() == 2
        # Columns absent from the frame entirely surface as NaN, not 0.
        assert matrix["gross_margin"].isna().all()

    def test_all_columns_float(self, frame: pd.DataFrame) -> None:
        matrix, _ = encode_features(frame)
        assert all(dtype.kind == "f" for dtype in matrix.dtypes)


class TestReporting:
    """Summaries and feature grouping."""

    def test_summarise(self, frame: pd.DataFrame) -> None:
        summary = summarise("train", frame)
        assert summary.rows == 7
        assert summary.companies == 2
        assert summary.fiscal_year_min == 2020
        assert summary.fiscal_year_max == 2025
        assert 0 < summary.positive_rate < 1

    def test_feature_groups_partition_all_columns(self, frame: pd.DataFrame) -> None:
        matrix, _ = encode_features(frame)
        groups = feature_groups(list(matrix.columns))
        flattened = [c for cols in groups.values() for c in cols]
        assert sorted(flattened) == sorted(matrix.columns)
        assert set(groups["language"]) <= set(LANGUAGE_FEATURES)
        assert groups["macro"] == ["fed_funds_rate", "yield_curve_spread",
                                   "unemployment_rate", "cpi_yoy"]