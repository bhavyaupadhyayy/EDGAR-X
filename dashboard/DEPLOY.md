# Deploying the EDGAR-X dashboard (Streamlit Community Cloud, free)

The dashboard reads a **committed static snapshot** (`dashboard/data/`). It has
**no** runtime dependency on Snowflake, the Anthropic API, the network, or any
secret — so it runs free and permanently on Streamlit Community Cloud, even
after the Snowflake trial expires.

## One-time deploy

1. Push this repo to GitHub (already at `github.com/bhavyaupadhyayy/EDGAR-X`).
2. Go to <https://share.streamlit.io> and sign in with GitHub.
3. **New app → Deploy a public app from GitHub**, then set:
   - **Repository**: `bhavyaupadhyayy/EDGAR-X`
   - **Branch**: `main`
   - **Main file path**: `dashboard/app.py`
4. **Do NOT add any secrets.** The app needs none. Leave the *Secrets* box empty.
5. Click **Deploy**. Community Cloud installs from the root `requirements.txt`
   (four packages — streamlit, pandas, pyarrow, plotly) and builds in ~1–2 min.

That's it. The app boots against the snapshot and stays up for free.

## Why no secrets / no live connections

- `dashboard/app.py` imports only `streamlit`, `pandas`, `plotly`, and the
  standard library. There is no `snowflake-connector`, no `anthropic`, no
  network client, and no environment-variable / secret read anywhere in it.
- All data comes from the files under `dashboard/data/` committed to the repo.
- Verify yourself:
  ```bash
  grep -rE "snowflake|anthropic|requests|httpx|os.environ|getenv" dashboard/app.py
  # → no matches
  ```

## Dependency file note

Community Cloud prefers a root `requirements.txt` over `pyproject.toml`. The
root `requirements.txt` here is intentionally the **minimal dashboard set** so
the Cloud build is fast and never tries to install the project's heavy
ingestion/ML stack. `pyproject.toml` remains the source of truth for local
development of the full project.

## Updating the deployed data

The data reflects annual 10-K filings, so it changes ~yearly. To refresh the
snapshot when new filings land, see [REFRESH.md](REFRESH.md) — it's a single
local command followed by a commit; Community Cloud redeploys automatically on
push.
