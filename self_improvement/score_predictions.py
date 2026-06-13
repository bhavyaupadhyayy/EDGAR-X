"""Materialize XGBoost predictions into Snowflake for outcome tracking.

dbt cannot run XGBoost, so the model's score for every company-fiscal-year is
computed here (Python) and written to ``EDGAR_X.RAW.RAW_MODEL_PREDICTIONS``.
This is a DERIVED artifact, not ingested data — it lives in the RAW schema
only so the dbt ``source('raw', ...)`` pattern stays uniform. The
``prediction_outcomes`` mart then joins these scores against the realized
outcomes already encoded (leakage-disciplined) as ``label`` in
``int_ml_features``.

Run after each retrain / outcome refresh::

    set -a; source .env; set +a
    python -m self_improvement.score_predictions
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from core.logging import configure_logging, get_logger
from ingestion.sinks.snowflake_writer import ConnectionLike, open_connection

if TYPE_CHECKING:  # pragma: no cover - typing only
    pass

configure_logging()
logger = get_logger("score_predictions")

ARTIFACT_DIR = Path(__file__).parent.parent / "ml" / "revenue_predictor" / "artifacts"
PREDICTIONS_TABLE = "RAW_MODEL_PREDICTIONS"
DECISION_THRESHOLD = 0.5

#: DDL is the source of truth for the predictions landing table contract.
PREDICTIONS_DDL = f"""
create table if not exists EDGAR_X.RAW.{PREDICTIONS_TABLE} (
    ticker VARCHAR,
    fiscal_year NUMBER(38,0),
    predicted_score FLOAT,
    predicted_direction NUMBER(38,0),
    model_artifact VARCHAR,
    scored_at TIMESTAMP_TZ
)
"""


def score_all(connection: ConnectionLike | None = None) -> int:
    """Score every INT_ML_FEATURES row and replace RAW_MODEL_PREDICTIONS.

    Args:
        connection: Optional injected connection (tests). A key-pair-auth
            connection is opened and closed when omitted.

    Returns:
        The number of prediction rows written.

    Raises:
        FileNotFoundError: If the model artifact or feature columns are absent.
    """
    model_path = ARTIFACT_DIR / "xgboost_revenue_direction.json"
    columns_path = ARTIFACT_DIR / "feature_columns.json"
    if not model_path.exists() or not columns_path.exists():
        raise FileNotFoundError(f"model artifact missing under {ARTIFACT_DIR}")

    import pandas as pd  # noqa: PLC0415 - deferred heavy import
    from snowflake.connector.pandas_tools import write_pandas  # noqa: PLC0415
    from xgboost import XGBClassifier  # noqa: PLC0415

    from ml.revenue_predictor.feature_engineering import encode_features  # noqa: PLC0415

    owns = connection is None
    conn = connection or open_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "select ticker, fiscal_year, sector, " +  # noqa: S608 - static columns
            ", ".join(_feature_source_columns()) +
            " from EDGAR_X.INTERMEDIATE.INT_ML_FEATURES"
        )
        frame = cursor.fetch_pandas_all()
        frame.columns = [c.lower() for c in frame.columns]

        matrix, _labels = encode_features(frame)
        feature_columns = json.loads(columns_path.read_text())
        matrix = matrix.reindex(columns=feature_columns, fill_value=0.0)

        model = XGBClassifier()
        model.load_model(model_path)
        scores = model.predict_proba(matrix)[:, 1]

        scored_at = datetime.now(UTC)
        predictions = pd.DataFrame(
            {
                "TICKER": frame["ticker"],
                "FISCAL_YEAR": frame["fiscal_year"].astype(int),
                "PREDICTED_SCORE": scores.astype(float),
                "PREDICTED_DIRECTION": (scores >= DECISION_THRESHOLD).astype(int),
                "MODEL_ARTIFACT": model_path.name,
                "SCORED_AT": scored_at,
            }
        )

        cursor.execute(PREDICTIONS_DDL)
        cursor.execute(f"truncate table if exists EDGAR_X.RAW.{PREDICTIONS_TABLE}")
        success, _chunks, nrows, _out = write_pandas(
            conn,
            predictions,
            table_name=PREDICTIONS_TABLE,
            database="EDGAR_X",
            schema="RAW",
            quote_identifiers=False,
            auto_create_table=False,
            use_logical_type=True,
        )
        if not success:
            raise RuntimeError("write_pandas reported failure writing predictions")
    finally:
        if owns:
            conn.close()

    logger.info("predictions_materialized", rows=int(nrows), artifact=model_path.name)
    return int(nrows)


def _feature_source_columns() -> list[str]:
    """Return the INT_ML_FEATURES columns the encoder reads."""
    from ml.revenue_predictor.feature_engineering import (  # noqa: PLC0415
        LABEL_COLUMN,
        NUMERIC_FEATURES,
    )

    # sector is selected separately for one-hot encoding; label not needed here.
    return [*NUMERIC_FEATURES, LABEL_COLUMN]


def main() -> int:
    """Score all company-years and print the row count."""
    rows = score_all()
    print(f"Wrote {rows} predictions to EDGAR_X.RAW.{PREDICTIONS_TABLE}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
