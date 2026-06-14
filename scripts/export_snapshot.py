"""Export a STATIC data snapshot for the Streamlit dashboard.

Run LOCALLY with Snowflake credentials. Writes pre-computed static files into
``dashboard/data/`` which are COMMITTED to the repo. The deployed dashboard
reads only these files — it never touches Snowflake, the Anthropic API, or any
secret at runtime.

This is the refresh path: when new 10-K filings land and the marts are
rebuilt, re-run this one command and commit the updated snapshot. Because the
underlying data is annual filings, a periodic snapshot is the right cadence.

Usage::

    set -a; source .env; set +a
    python scripts/export_snapshot.py
"""

from __future__ import annotations

import json
import re
import shutil
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from core.logging import configure_logging, get_logger
from ingestion.sinks.snowflake_writer import ConnectionLike, open_connection

if TYPE_CHECKING:  # pragma: no cover - typing only
    pass

configure_logging()
logger = get_logger("export_snapshot")

REPO = Path(__file__).parent.parent
DATA_DIR = REPO / "dashboard" / "data"
MEMO_SRC = REPO / "docs" / "sample_memos"
CALIBRATION_SRC = REPO / "docs" / "calibration_report.json"

#: The five companies with generated memos + judge reports (Layer 4).
MEMO_TICKERS = ("AAPL", "MSFT", "NVDA", "JNJ", "CAT")

_SCORE_RE = re.compile(
    r"\|\s*(factual_grounding|internal_consistency|honesty|specificity)"
    r"\s*\|\s*(\d+)/5\s*\|"
)
_VERDICT_RE = re.compile(r"## Verdict\s*\n+(.+?)(?:\n##|\Z)", re.DOTALL)


def export_predictions(connection: ConnectionLike) -> tuple[int, Path]:
    """Write predictions.parquet: every model prediction + realized outcome.

    Args:
        connection: Open Snowflake connection.

    Returns:
        (row count, output path).
    """
    cursor = connection.cursor()
    cursor.execute(
        """
        select p.ticker, c.company_name, p.sector, p.fiscal_year,
               p.predicted_score as score, p.predicted_direction,
               p.actual_direction, p.correct, p.status, p.data_split
        from EDGAR_X.MARTS.PREDICTION_OUTCOMES p
        left join EDGAR_X.MARTS.COMPANY_PROFILE c on p.ticker = c.ticker
        order by p.ticker, p.fiscal_year
        """
    )
    frame = cursor.fetch_pandas_all()
    frame.columns = [c.lower() for c in frame.columns]
    path = DATA_DIR / "predictions.parquet"
    frame.to_parquet(path, index=False)
    return len(frame), path


def export_company_meta(connection: ConnectionLike) -> tuple[int, Path]:
    """Write company_meta.json: latest key ratios per company.

    Ratios are taken from the company's most recent fiscal year in
    INT_ML_FEATURES so all four come from one consistent period.

    Args:
        connection: Open Snowflake connection.

    Returns:
        (company count, output path).
    """
    cursor = connection.cursor()
    cursor.execute(
        """
        with latest as (
            select ticker, sector, net_margin, debt_to_equity, roe_annualised,
                   revenue_growth_1y, fiscal_year
            from EDGAR_X.INTERMEDIATE.INT_ML_FEATURES
            qualify row_number() over (
                partition by ticker order by fiscal_year desc
            ) = 1
        )
        select l.ticker, coalesce(c.company_name, l.ticker) as company_name,
               l.sector, l.fiscal_year, l.net_margin, l.debt_to_equity,
               l.roe_annualised, l.revenue_growth_1y
        from latest l
        left join EDGAR_X.STAGING.STG_COMPANIES c on l.ticker = c.ticker
        order by l.ticker
        """
    )
    cols = ["ticker", "company_name", "sector", "fiscal_year", "net_margin",
            "debt_to_equity", "roe_annualised", "revenue_growth_1y"]
    meta = {
        row[0]: dict(zip(cols, [_clean(v) for v in row], strict=True))
        for row in cursor.fetchall()
    }
    path = DATA_DIR / "company_meta.json"
    path.write_text(json.dumps(meta, indent=1))
    return len(meta), path


def export_calibration() -> Path:
    """Copy the calibration report JSON into the snapshot.

    Returns:
        Output path.

    Raises:
        FileNotFoundError: If the calibration report has not been generated.
    """
    if not CALIBRATION_SRC.exists():
        raise FileNotFoundError(
            f"{CALIBRATION_SRC} missing — run `python -m self_improvement.calibration`"
        )
    path = DATA_DIR / "calibration.json"
    shutil.copyfile(CALIBRATION_SRC, path)
    return path


def export_memos() -> tuple[int, Path]:
    """Copy memo markdown and write structured judge-score JSON per company.

    Judge scores and verdict are parsed from each ``{TICKER}_judge_report.md``
    (the authoritative Layer-4 judge output), so the snapshot is self-contained.

    Returns:
        (memo count, memos directory).
    """
    memo_dir = DATA_DIR / "memos"
    memo_dir.mkdir(parents=True, exist_ok=True)
    written = 0
    for ticker in MEMO_TICKERS:
        memo_md = MEMO_SRC / f"{ticker}.md"
        judge_md = MEMO_SRC / f"{ticker}_judge_report.md"
        if not memo_md.exists() or not judge_md.exists():
            logger.warning("memo_missing", ticker=ticker)
            continue
        shutil.copyfile(memo_md, memo_dir / f"{ticker}.md")
        report = judge_md.read_text()
        scores = {dim: int(val) for dim, val in _SCORE_RE.findall(report)}
        verdict_match = _VERDICT_RE.search(report)
        (memo_dir / f"{ticker}_judge.json").write_text(
            json.dumps(
                {
                    "ticker": ticker,
                    "scores": scores,
                    "verdict": verdict_match.group(1).strip() if verdict_match else "",
                    "judge_model": "claude-opus-4-8",
                },
                indent=1,
            )
        )
        written += 1
    return written, memo_dir


def _clean(value: object) -> object:
    """Round floats for compact JSON; pass through everything else."""
    if isinstance(value, float):
        return round(value, 4)
    return value


def _dir_size_bytes(path: Path) -> int:
    """Total size of all files under ``path``."""
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file())


def main() -> int:
    """Export the full snapshot and print a summary + total size."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = open_connection()
    try:
        n_pred, pred_path = export_predictions(conn)
        n_meta, meta_path = export_company_meta(conn)
    finally:
        conn.close()
    calib_path = export_calibration()
    n_memos, memo_dir = export_memos()

    print("\nSnapshot written to dashboard/data/:")
    print(f"  predictions.parquet   {n_pred:>6} rows   "
          f"{pred_path.stat().st_size / 1024:>7.1f} KB")
    print(f"  company_meta.json     {n_meta:>6} cos    "
          f"{meta_path.stat().st_size / 1024:>7.1f} KB")
    print(f"  calibration.json             -    "
          f"{calib_path.stat().st_size / 1024:>7.1f} KB")
    print(f"  memos/                {n_memos:>6} memos  "
          f"{_dir_size_bytes(memo_dir) / 1024:>7.1f} KB")
    print(f"\nTotal snapshot size: {_dir_size_bytes(DATA_DIR) / 1024:.1f} KB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
