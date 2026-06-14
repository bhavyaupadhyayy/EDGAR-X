"""EDGAR-X dashboard — reads ONLY a static snapshot, zero live dependencies.

This deployed app has NO dependency on Snowflake, the Anthropic API, the
network, or any secret. It imports only streamlit / pandas / plotly and reads
the committed files under ``dashboard/data/`` (exported offline by
``scripts/export_snapshot.py``). There is no database client, no API client,
and no credential anywhere in this module — verify by inspection: the only
imports are the standard library plus the three rendering libraries above.

The data is a periodic snapshot of annual 10-K filings; that cadence is
appropriate, not a compromise.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

DATA_DIR = Path(__file__).parent / "data"
MEMO_DIR = DATA_DIR / "memos"
ACCENT = "#7AA2F7"
MUTED = "#8B949E"

#: The five companies with generated memos (Layer-4 demo).
MEMO_TICKERS = {"AAPL", "MSFT", "NVDA", "JNJ", "CAT"}

st.set_page_config(page_title="EDGAR-X", page_icon="📊", layout="wide")


# --------------------------------------------------------------------------- #
# Snapshot loaders (cached; pure file reads — no network).
# --------------------------------------------------------------------------- #
@st.cache_data
def load_predictions() -> pd.DataFrame:
    """Load the predictions snapshot."""
    return pd.read_parquet(DATA_DIR / "predictions.parquet")


@st.cache_data
def load_company_meta() -> dict[str, dict]:
    """Load per-company latest ratios."""
    return json.loads((DATA_DIR / "company_meta.json").read_text())


@st.cache_data
def load_calibration() -> dict:
    """Load the calibration report."""
    return json.loads((DATA_DIR / "calibration.json").read_text())


@st.cache_data
def load_memo(ticker: str) -> tuple[str | None, dict | None]:
    """Load a company's memo markdown + judge scores, if present."""
    memo_path = MEMO_DIR / f"{ticker}.md"
    judge_path = MEMO_DIR / f"{ticker}_judge.json"
    if not memo_path.exists():
        return None, None
    judge = json.loads(judge_path.read_text()) if judge_path.exists() else None
    return memo_path.read_text(), judge


# --------------------------------------------------------------------------- #
# Shared UI helpers.
# --------------------------------------------------------------------------- #
def global_caveats() -> None:
    """Render the always-available honesty caveats."""
    with st.sidebar.expander("⚠ Read me — what this is and isn't", expanded=False):
        st.markdown(
            "- **Ranked screen, not a classifier.** Scores order companies by "
            "relative likelihood of next-year revenue growth (test ROC-AUC "
            "0.726). They are not calibrated probabilities to act on.\n"
            "- **Universe excludes Financials** (~70 companies): bank/insurer "
            "revenue isn't comparable under the XBRL concepts used.\n"
            "- **Memos demoed on 5 companies** only (AAPL, MSFT, NVDA, JNJ, CAT).\n"
            "- **Calibration is preliminary** — one small out-of-sample window "
            "(447 rows, FY2024–25).\n"
            "- **Static snapshot** of annual filings, refreshed periodically. "
            "No live database or API."
        )


def direction_badge(direction: float | None) -> str:
    """Render a revenue-direction value as a labeled arrow."""
    if direction is None or pd.isna(direction):
        return "—"
    return "📈 Up" if int(direction) == 1 else "📉 Down / flat"


# --------------------------------------------------------------------------- #
# Page: Company Explorer.
# --------------------------------------------------------------------------- #
def page_company_explorer(preds: pd.DataFrame, meta: dict[str, dict]) -> None:
    """Per-company score, ratios, and memo (or honest no-memo note)."""
    st.header("Company explorer")
    st.caption(
        "Pick a company to see the model's latest revenue-direction score, its "
        "key ratios, and — for the five demo companies — the AI-generated "
        "research memo with its independent judge scores."
    )

    options = (
        preds[["ticker", "company_name"]]
        .drop_duplicates()
        .sort_values("ticker")
    )
    labels = {
        row.ticker: f"{row.ticker} — {row.company_name or 'name n/a'}"
        for row in options.itertuples()
    }
    ticker = st.selectbox(
        f"Company ({len(labels)} in snapshot)",
        options=list(labels),
        format_func=lambda t: labels[t],
    )

    rows = preds[preds["ticker"] == ticker].sort_values("fiscal_year")
    latest = rows.iloc[-1]
    is_pending = latest["status"] == "pending"

    col1, col2, col3 = st.columns(3)
    col1.metric(f"FY{int(latest['fiscal_year'])} score", f"{latest['score']:.4f}")
    col2.metric("Predicted direction", direction_badge(latest["predicted_direction"]))
    if is_pending:
        col3.metric("Outcome", "Not yet known")
    else:
        correct = bool(latest["correct"])
        col3.metric(
            "Actual / correct?",
            f"{direction_badge(latest['actual_direction'])} · "
            f"{'✓' if correct else '✗'}",
        )

    if is_pending:
        st.warning(
            f"**Prediction made; next-year outcome not yet known.** This is the "
            f"model's score for FY{int(latest['fiscal_year'])} — the FY"
            f"{int(latest['fiscal_year']) + 1} revenue needed to confirm it has "
            "not been filed yet. Do not read this as a confirmed result."
        )

    company = meta.get(ticker)
    if company:
        st.subheader("Latest key ratios")
        rc = st.columns(4)
        rc[0].metric("Revenue growth (1y)", _pct(company.get("revenue_growth_1y")))
        rc[1].metric("Net margin", _pct(company.get("net_margin")))
        rc[2].metric("Debt / equity", _num(company.get("debt_to_equity")))
        rc[3].metric("ROE (annualised)", _num(company.get("roe_annualised")))
        st.caption(
            f"Ratios from FY{company.get('fiscal_year', '—')}. Sector: "
            f"{company.get('sector', '—')}."
        )

    st.subheader("Prediction history")
    history = rows[
        ["fiscal_year", "score", "predicted_direction", "actual_direction",
         "correct", "status", "data_split"]
    ].copy()
    history["predicted_direction"] = history["predicted_direction"].map(
        lambda v: "Up" if int(v) == 1 else "Down"
    )
    history["actual_direction"] = history["actual_direction"].map(
        lambda v: "—" if pd.isna(v) else ("Up" if int(v) == 1 else "Down")
    )
    history["correct"] = history["correct"].map(
        lambda v: "—" if pd.isna(v) else ("✓" if v else "✗")
    )
    st.dataframe(
        history.rename(
            columns={
                "fiscal_year": "FY", "score": "score",
                "predicted_direction": "predicted", "actual_direction": "actual",
                "correct": "correct", "status": "status", "data_split": "split",
            }
        ),
        hide_index=True,
        width="stretch",
    )
    st.caption(
        "`split` = train (in-sample, the model trained on this label) vs test "
        "(out-of-sample) vs pending (no outcome yet). Only out-of-sample rows "
        "reflect real performance."
    )

    st.subheader("Research memo")
    if ticker in MEMO_TICKERS:
        memo_md, judge = load_memo(ticker)
        if judge:
            jc = st.columns(4)
            for i, dim in enumerate(
                ["factual_grounding", "internal_consistency", "honesty", "specificity"]
            ):
                jc[i].metric(
                    dim.replace("_", " "), f"{judge['scores'].get(dim, '—')}/5"
                )
            st.caption(
                f"Independent judge ({judge.get('judge_model')}): "
                f"{judge.get('verdict')}"
            )
        if memo_md:
            with st.expander("Full memo", expanded=False):
                st.markdown(memo_md)
    else:
        st.info(
            "No memo generated for this company. The agent pipeline was demoed "
            "on 5 companies (AAPL, MSFT, NVDA, JNJ, CAT); memos for the full "
            "universe are future work, not a current claim."
        )


# --------------------------------------------------------------------------- #
# Page: Calibration.
# --------------------------------------------------------------------------- #
def page_calibration(calib: dict) -> None:
    """Out-of-sample calibration — the hero decile chart + honest caveats."""
    st.header("Model calibration")

    oos = calib["out_of_sample"]
    years = calib["out_of_sample_years"]
    span = f"FY{years[0]}–FY{years[-1]}" if years else "n/a"
    st.warning(
        f"**Read this first.** All performance numbers below come ONLY from the "
        f"{calib['out_of_sample_n']} genuinely out-of-sample rows ({span}). "
        "This is a small window — figures are preliminary. The "
        f"{calib['in_sample_n']} in-sample rows are EXCLUDED from every headline "
        "metric; they appear only as a clearly-labeled reference."
    )

    st.subheader("Do higher scores actually grow more often?")
    st.caption(
        "Out-of-sample companies binned by predicted score. A working ranked "
        "screen shows actual growth rate rising with the score. Bars with small "
        "n are faded — don't over-read them."
    )
    _render_decile_chart(calib["deciles"])

    st.subheader("Out-of-sample performance")
    mc = st.columns(4)
    mc[0].metric(
        "Accuracy",
        _pct(oos["accuracy"]),
        help=f"Wilson 95% CI {_pct(oos['ci_low'])}–{_pct(oos['ci_high'])}",
    )
    mc[1].metric("Realized ROC-AUC", _num(calib["realized_auc"]))
    mc[2].metric("Reported AUC", _num(calib["reported_test_auc"]))
    mc[3].metric("Base rate (grew)", _pct(calib["out_of_sample_base_rate"]))
    st.caption(
        f"Accuracy ≈ the {_pct(calib['out_of_sample_base_rate'])} base rate, so "
        "read AUC, not accuracy. Realized AUC matches reported AUC because these "
        "are the model's own held-out rows — this is reproduction, not fresh "
        "independent validation (that needs a new fiscal year, pending)."
    )

    cga, cgb = st.columns(2)
    with cga:
        st.subheader("By fiscal year")
        st.caption("Two years only — drift is not yet assessable.")
        st.dataframe(_group_frame(calib["by_fiscal_year"]), hide_index=True,
                     width="stretch")
    with cgb:
        st.subheader("By sector")
        st.caption("Many sectors have small n (flagged) — treat as indicative only.")
        st.dataframe(_group_frame(calib["by_sector"]), hide_index=True,
                     width="stretch")

    ref = calib["in_sample_reference"]
    st.subheader("In-sample reference — NOT valid for performance")
    st.error(
        f"{ref['n']} in-sample (train) rows, accuracy {_pct(ref['accuracy'])}. "
        "The model was trained on these labels; this number is shown only so it "
        "is not silently omitted. It must NOT be read as performance."
    )

    with st.expander("All calibration caveats (verbatim from the report)"):
        for w in calib["warnings"]:
            st.markdown(f"- {w}")
    st.caption(f"Verdict: {calib['verdict']}")


def _render_decile_chart(deciles: list[dict]) -> None:
    """Plot actual growth rate per score decile, fading small-n bars."""
    if not deciles:
        st.info("Too few out-of-sample rows for decile binning.")
        return
    x = [f"D{d['decile']} ({d['score_low']:.2f}-{d['score_high']:.2f})" for d in deciles]
    growth = [d["actual_growth_rate"] for d in deciles]
    colors = [
        f"rgba(122,162,247,{0.35 if d['small_sample'] else 1.0})" for d in deciles
    ]
    fig = go.Figure()
    fig.add_trace(
        go.Bar(
            x=x, y=growth, marker_color=colors,
            text=[f"n={d['n']}" for d in deciles], textposition="outside",
            name="actual growth rate",
        )
    )
    fig.add_trace(
        go.Scatter(
            x=x, y=[d["mean_predicted_score"] for d in deciles],
            mode="lines+markers", line={"color": MUTED, "dash": "dot"},
            name="mean predicted score",
        )
    )
    fig.update_layout(
        template="plotly_dark", height=420,
        yaxis={"title": "rate", "range": [0, 1.1]},
        xaxis={"title": "score decile (faded = small n)"},
        legend={"orientation": "h", "y": 1.12},
        margin={"t": 40, "b": 40},
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
    )
    st.plotly_chart(fig, width="stretch")


# --------------------------------------------------------------------------- #
# Page: Sector Overview.
# --------------------------------------------------------------------------- #
def page_sector_overview(preds: pd.DataFrame) -> None:
    """Aggregate score / direction distribution by GICS sector."""
    st.header("Sector overview")
    st.caption(
        "Score and predicted-direction distribution across the universe, by "
        "GICS sector. Scores cover all company-years; out-of-sample accuracy is "
        "shown separately where enough outcomes exist."
    )

    by_sector = (
        preds.groupby("sector")
        .agg(
            companies=("ticker", "nunique"),
            predictions=("score", "size"),
            mean_score=("score", "mean"),
            pct_up=("predicted_direction", "mean"),
        )
        .reset_index()
        .sort_values("mean_score", ascending=False)
    )
    test = preds[preds["data_split"] == "test"]
    acc = (
        test.assign(ok=test["correct"].astype("float"))
        .groupby("sector")
        .agg(oos_n=("ok", "size"), oos_accuracy=("ok", "mean"))
        .reset_index()
    )
    merged = by_sector.merge(acc, on="sector", how="left")

    fig = go.Figure(
        go.Bar(
            x=merged["sector"], y=merged["mean_score"], marker_color=ACCENT,
            text=[f"{v:.2f}" for v in merged["mean_score"]], textposition="outside",
        )
    )
    fig.update_layout(
        template="plotly_dark", height=420,
        yaxis={"title": "mean score", "range": [0, 1]},
        margin={"t": 30, "b": 90}, paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
    )
    st.plotly_chart(fig, width="stretch")

    display = merged.copy()
    display["mean_score"] = display["mean_score"].map(lambda v: f"{v:.3f}")
    display["pct_up"] = display["pct_up"].map(_pct)
    display["oos_accuracy"] = display["oos_accuracy"].map(
        lambda v: "—" if pd.isna(v) else _pct(v)
    )
    display["oos_n"] = display["oos_n"].map(lambda v: "—" if pd.isna(v) else int(v))
    st.dataframe(
        display.rename(
            columns={
                "sector": "sector", "companies": "companies",
                "predictions": "predictions", "mean_score": "mean score",
                "pct_up": "% predicted up", "oos_n": "OOS rows",
                "oos_accuracy": "OOS accuracy",
            }
        ),
        hide_index=True,
        width="stretch",
    )
    st.caption(
        "'% predicted up' and 'mean score' span all company-years; 'OOS "
        "accuracy' is out-of-sample only and thin per sector — indicative, not "
        "conclusive. Financials are absent by design."
    )


# --------------------------------------------------------------------------- #
# Formatting + group helpers.
# --------------------------------------------------------------------------- #
def _pct(value: float | None) -> str:
    """Format a fraction as a percentage, em dash for None/NaN."""
    return f"{value:.1%}" if value is not None and not pd.isna(value) else "—"


def _num(value: float | None) -> str:
    """Format a float to 3 dp, em dash for None/NaN."""
    return f"{value:.3f}" if value is not None and not pd.isna(value) else "—"


def _group_frame(groups: list[dict]) -> pd.DataFrame:
    """Turn a calibration GroupStat list into a display frame with CIs + flags."""
    rows = []
    for g in groups:
        s = g["stat"]
        rows.append(
            {
                "group": g["group"],
                "n": s["n"],
                "accuracy": _pct(s["accuracy"]),
                "95% CI": f"{_pct(s['ci_low'])}–{_pct(s['ci_high'])}",
                "note": "⚠ small n" if s["small_sample"] else "",
            }
        )
    return pd.DataFrame(rows)


def main() -> None:
    """Sidebar nav + page dispatch."""
    st.sidebar.title("EDGAR-X")
    st.sidebar.caption("Autonomous financial-filing intelligence — demo dashboard")
    page = st.sidebar.radio(
        "Page", ["Company explorer", "Calibration", "Sector overview"]
    )
    global_caveats()
    st.sidebar.caption("Static snapshot · no live database or API")

    preds = load_predictions()
    if page == "Company explorer":
        page_company_explorer(preds, load_company_meta())
    elif page == "Calibration":
        page_calibration(load_calibration())
    else:
        page_sector_overview(preds)


main()
