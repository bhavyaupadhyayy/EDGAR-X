"""Typed Snowflake readers for the agent layer.

Agents never query Snowflake directly — they consume these typed records, so
unit tests inject data objects and the provenance of every field is explicit:

* :class:`FilingText` — ``EDGAR_X.RAW.RAW_FILINGS`` (mdna_text, risk_factors_text)
* :class:`CompanyYearRow` — ``EDGAR_X.INTERMEDIATE.INT_ML_FEATURES`` (ratios,
  filing-language features, the fiscal-year ↔ accession mapping)
* :class:`ModelScore` — the saved XGBoost artifact scored on the company-year's
  real feature row
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict

from core.logging import get_logger
from ingestion.sinks.snowflake_writer import ConnectionLike, open_connection

if TYPE_CHECKING:  # pragma: no cover - typing only
    pass

logger = get_logger(__name__)

ARTIFACT_DIR = Path(__file__).parent.parent / "ml" / "revenue_predictor" / "artifacts"


class FilingText(BaseModel):
    """10-K section text for one company-fiscal-year (source: RAW_FILINGS)."""

    model_config = ConfigDict(frozen=True)

    ticker: str
    fiscal_year: int
    accession_number: str
    filing_date: date
    mdna_text: str | None
    risk_factors_text: str | None

    @property
    def source_reference(self) -> str:
        """Human-readable provenance string for memos and the judge."""
        return (
            f"EDGAR_X.RAW.RAW_FILINGS accession {self.accession_number} "
            f"(10-K filed {self.filing_date}, fields mdna_text / risk_factors_text)"
        )


class CompanyYearRow(BaseModel):
    """One INT_ML_FEATURES row: ratios + filing-language features."""

    model_config = ConfigDict(frozen=True)

    ticker: str
    fiscal_year: int
    accession_number: str | None
    revenue: float | None
    revenue_growth_1y: float | None
    gross_margin: float | None
    net_margin: float | None
    debt_to_equity: float | None
    liabilities_to_assets: float | None
    roe_annualised: float | None
    litigation_mentions: float | None
    impairment_mentions: float | None
    decline_mentions: float | None
    uncertain_mentions: float | None
    recession_mentions: float | None
    risk_word_total: float | None
    risk_words_per_1000: float | None

    @property
    def source_reference(self) -> str:
        """Human-readable provenance string for memos and the judge."""
        return (
            f"EDGAR_X.INTERMEDIATE.INT_ML_FEATURES "
            f"(ticker={self.ticker}, fiscal_year={self.fiscal_year})"
        )


class ModelScore(BaseModel):
    """The XGBoost ranked-screen score for one company-fiscal-year."""

    model_config = ConfigDict(frozen=True)

    ticker: str
    fiscal_year: int
    score: float
    artifact: str

    @property
    def source_reference(self) -> str:
        """Human-readable provenance string for memos and the judge."""
        return (
            f"XGBoost revenue-direction model ({self.artifact}) scored on the "
            f"FY{self.fiscal_year} feature row from EDGAR_X.INTERMEDIATE.INT_ML_FEATURES"
        )


def load_company_year(
    ticker: str, fiscal_year: int, connection: ConnectionLike | None = None
) -> CompanyYearRow | None:
    """Load the INT_ML_FEATURES row for one company-fiscal-year.

    Args:
        ticker: Company ticker.
        fiscal_year: Fiscal year (FY N).
        connection: Optional injected connection (tests).

    Returns:
        The row, or ``None`` if the company-year is not in the feature base.
    """
    owns = connection is None
    conn = connection or open_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            select ticker, fiscal_year, accession_number, revenue, revenue_growth_1y,
                   gross_margin, net_margin, debt_to_equity, liabilities_to_assets,
                   roe_annualised, litigation_mentions, impairment_mentions,
                   decline_mentions, uncertain_mentions, recession_mentions,
                   risk_word_total, risk_words_per_1000
            from EDGAR_X.INTERMEDIATE.INT_ML_FEATURES
            where ticker = %s and fiscal_year = %s
            """,
            (ticker.upper(), fiscal_year),
        )
        row = cursor.fetchone()
    finally:
        if owns:
            conn.close()
    if row is None:
        return None
    fields = list(CompanyYearRow.model_fields)
    return CompanyYearRow(**dict(zip(fields, row, strict=True)))


def load_filing_text(
    ticker: str, fiscal_year: int, connection: ConnectionLike | None = None
) -> FilingText | None:
    """Load the 10-K section text covering one company-fiscal-year.

    The fiscal-year ↔ filing mapping comes from INT_ML_FEATURES (the first
    10-K filed within 180 days after period end); the text from RAW_FILINGS.

    Args:
        ticker: Company ticker.
        fiscal_year: Fiscal year the 10-K covers.
        connection: Optional injected connection (tests).

    Returns:
        The filing text, or ``None`` when no filing was matched to that year
        (e.g. years older than the 10-year filing lookback).
    """
    owns = connection is None
    conn = connection or open_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            select f.ticker, m.fiscal_year, f.accession_number, f.filing_date,
                   f.mdna_text, f.risk_factors_text
            from EDGAR_X.INTERMEDIATE.INT_ML_FEATURES m
            join EDGAR_X.RAW.RAW_FILINGS f on m.accession_number = f.accession_number
            where m.ticker = %s and m.fiscal_year = %s
            """,
            (ticker.upper(), fiscal_year),
        )
        row = cursor.fetchone()
    finally:
        if owns:
            conn.close()
    if row is None:
        return None
    fields = list(FilingText.model_fields)
    return FilingText(**dict(zip(fields, row, strict=True)))


def load_model_score(
    ticker: str, fiscal_year: int, connection: ConnectionLike | None = None
) -> ModelScore | None:
    """Score one company-fiscal-year with the saved XGBoost artifact.

    Loads the real feature row from INT_ML_FEATURES, encodes it exactly as
    training did (saved feature-column order, NaN preserved), and runs the
    persisted model. No data is invented: if the row or the artifact is
    missing, the answer is ``None``.

    Args:
        ticker: Company ticker.
        fiscal_year: Fiscal year to score.
        connection: Optional injected connection (tests).

    Returns:
        The score, or ``None`` if the feature row or artifact is unavailable.
    """
    model_path = ARTIFACT_DIR / "xgboost_revenue_direction.json"
    columns_path = ARTIFACT_DIR / "feature_columns.json"
    if not model_path.exists() or not columns_path.exists():
        logger.warning("model_artifact_missing", path=str(model_path))
        return None

    owns = connection is None
    conn = connection or open_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "select * from EDGAR_X.INTERMEDIATE.INT_ML_FEATURES "
            "where ticker = %s and fiscal_year = %s",
            (ticker.upper(), fiscal_year),
        )
        frame = cursor.fetch_pandas_all()
    finally:
        if owns:
            conn.close()
    if frame.empty:
        return None
    frame.columns = [c.lower() for c in frame.columns]

    from xgboost import XGBClassifier  # noqa: PLC0415 - deferred heavy import

    from ml.revenue_predictor.feature_engineering import encode_features  # noqa: PLC0415

    matrix, _labels = encode_features(frame)
    feature_columns = json.loads(columns_path.read_text())
    matrix = matrix.reindex(columns=feature_columns, fill_value=0.0)

    model = XGBClassifier()
    model.load_model(model_path)
    score = float(model.predict_proba(matrix)[0, 1])
    return ModelScore(
        ticker=ticker.upper(),
        fiscal_year=fiscal_year,
        score=score,
        artifact=model_path.name,
    )
