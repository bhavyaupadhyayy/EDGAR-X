"""Feature engineering for the revenue-direction predictor.

Pulls ``MARTS.ML_TRAINING_SET`` from Snowflake, one-hot encodes the GICS
sector, and prepares a numeric feature matrix. NULL handling is explicit and
model-specific: XGBoost receives NaN natively (missing-aware splits), while
the logistic-regression baseline gets median imputation inside its pipeline.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel

from core.logging import get_logger
from ingestion.sinks.snowflake_writer import ConnectionLike, open_connection

if TYPE_CHECKING:  # pragma: no cover - heavy import, typing only
    import pandas as pd

logger = get_logger(__name__)

#: Numeric feature columns pulled from the training set (lowercase).
NUMERIC_FEATURES: tuple[str, ...] = (
    "revenue",
    "revenue_growth_1y",
    "gross_margin",
    "net_margin",
    "debt_to_equity",
    "liabilities_to_assets",
    "roe_annualised",
    "mdna_word_count",
    "litigation_mentions",
    "impairment_mentions",
    "decline_mentions",
    "uncertain_mentions",
    "recession_mentions",
    "risk_word_total",
    "risk_words_per_1000",
    "fed_funds_rate",
    "yield_curve_spread",
    "unemployment_rate",
    "cpi_yoy",
)

#: Subset of features derived from 10-K filing text (56% row coverage).
LANGUAGE_FEATURES: tuple[str, ...] = (
    "mdna_word_count",
    "litigation_mentions",
    "impairment_mentions",
    "decline_mentions",
    "uncertain_mentions",
    "recession_mentions",
    "risk_word_total",
    "risk_words_per_1000",
)

SECTOR_PREFIX = "sector_"
LABEL_COLUMN = "label"
YEAR_COLUMN = "fiscal_year"


class DatasetSummary(BaseModel):
    """Shape and balance of one dataset slice."""

    name: str
    rows: int
    companies: int
    fiscal_year_min: int
    fiscal_year_max: int
    positive_rate: float


def load_training_set(connection: ConnectionLike | None = None) -> pd.DataFrame:
    """Load the full labelable training set from Snowflake.

    Args:
        connection: Optional injected connection (tests). A key-pair-auth
            connection is opened (and closed) when omitted.

    Returns:
        The training set with lowercase column names.
    """
    owns = connection is None
    conn = connection or open_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("select * from MARTS.ML_TRAINING_SET")
        frame = cursor.fetch_pandas_all()
    finally:
        if owns:
            conn.close()
    frame.columns = [column.lower() for column in frame.columns]
    logger.info("training_set_loaded", rows=len(frame))
    return frame


def encode_features(frame: pd.DataFrame) -> tuple[pd.DataFrame, pd.Series]:
    """Build the model feature matrix and label vector.

    GICS sector is one-hot encoded; numeric features are coerced to float
    with NaN preserved (XGBoost consumes them natively; baselines impute in
    their own pipelines).

    Args:
        frame: Rows from the training (or inference) set.

    Returns:
        Tuple of (feature matrix, label series). For inference frames the
        label series contains NaN.
    """
    import pandas as pd  # noqa: PLC0415 - deferred heavy import

    features = frame.reindex(columns=list(NUMERIC_FEATURES)).astype("float64")
    sector_dummies = pd.get_dummies(
        frame["sector"], prefix=SECTOR_PREFIX.rstrip("_")
    ).astype("float64")
    matrix = pd.concat([features, sector_dummies], axis=1)
    labels = pd.to_numeric(frame.get(LABEL_COLUMN), errors="coerce")
    return matrix, labels


def time_split(
    frame: pd.DataFrame, *, test_years: tuple[int, ...] = (2024, 2025)
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Split rows by fiscal year: strictly earlier years train, given years test.

    The same company may appear on both sides — that is the realistic
    deployment setting for panel data — but every training row's fiscal year
    strictly precedes every test year, and no test-year information is used
    for fitting or tuning.

    Args:
        frame: The full training set.
        test_years: Fiscal years reserved for the held-out test set.

    Returns:
        Tuple of (train frame, test frame).
    """
    is_test = frame[YEAR_COLUMN].isin(test_years)
    is_train = frame[YEAR_COLUMN] < min(test_years)
    return frame[is_train].copy(), frame[is_test].copy()


def summarise(name: str, frame: pd.DataFrame) -> DatasetSummary:
    """Summarise one dataset slice.

    Args:
        name: Slice name for reporting (``train`` / ``test``).
        frame: The slice.

    Returns:
        Row counts, year span, and positive rate.
    """
    return DatasetSummary(
        name=name,
        rows=len(frame),
        companies=frame["ticker"].nunique(),
        fiscal_year_min=int(frame[YEAR_COLUMN].min()),
        fiscal_year_max=int(frame[YEAR_COLUMN].max()),
        positive_rate=float(frame[LABEL_COLUMN].mean()),
    )


def feature_groups(columns: list[str]) -> dict[str, list[str]]:
    """Group feature columns for importance reporting.

    Args:
        columns: Feature-matrix column names.

    Returns:
        Mapping of group name to its columns.
    """
    groups: dict[str, list[str]] = {"language": [], "sector": [], "fundamental": [], "macro": []}
    macro = {"fed_funds_rate", "yield_curve_spread", "unemployment_rate", "cpi_yoy"}
    for column in columns:
        if column in LANGUAGE_FEATURES:
            groups["language"].append(column)
        elif column.startswith(SECTOR_PREFIX):
            groups["sector"].append(column)
        elif column in macro:
            groups["macro"].append(column)
        else:
            groups["fundamental"].append(column)
    return groups
