# Refreshing the dashboard snapshot

The dashboard serves a **static snapshot** of annual 10-K data. When new
filings land and the warehouse is rebuilt, refresh the snapshot with one local
command, then commit — Community Cloud redeploys automatically on push.

## Prerequisites (local only — never needed by the deployed app)

- `.env` with `SNOWFLAKE_*` key-pair credentials.
- The marts rebuilt with the new filings, and predictions/calibration current:
  ```bash
  set -a; source .env; set +a

  # 1. Rebuild transforms with the new filings (prod / Snowflake)
  cd transforms/dbt && dbt build --target prod --profiles-dir . && cd ../..

  # 2. Re-score predictions and rebuild the outcome + calibration artifacts
  python -m self_improvement.score_predictions
  cd transforms/dbt && dbt build --target prod --profiles-dir . \
      --select prediction_outcomes && cd ../..
  python -m self_improvement.calibration
  ```

## The refresh command

```bash
set -a; source .env; set +a
python scripts/export_snapshot.py
```

This cleanly overwrites every file under `dashboard/data/`
(`predictions.parquet`, `company_meta.json`, `calibration.json`, and the
`memos/`) and prints a summary + total size.

## Publish

```bash
git add dashboard/data
git commit -m "Refresh dashboard snapshot"
git push origin main
```

Community Cloud detects the push and redeploys within a minute. No secrets, no
manual steps on the Cloud side.

## Cadence

Because the source is annual filings, refreshing once per filing season (or
whenever you re-run the universe backfill) is the right cadence — a static
snapshot is appropriate here, not a limitation.
