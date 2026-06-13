"""Generate the Layer-4 demo memo set: full pipeline + judge per company.

Modes::

    python scripts/generate_demo_memos.py --project   # cost projection only
    python scripts/generate_demo_memos.py --run       # spend money

The batch shares ONE cost tracker with an explicit cap; a projected or actual
breach aborts the batch. Per-company data errors are recorded and skipped —
weak or failed memos are reported, not hidden.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from pydantic import BaseModel

from agents.cost_tracker import CostTracker, estimate_max_cost
from agents.data_access import (
    load_company_year,
    load_filing_text,
    load_model_score,
)
from agents.evaluation.memo_judge import MemoJudge, render_judge_report
from agents.orchestrator import generate_memo
from core.logging import configure_logging, get_logger
from ingestion.sinks.snowflake_writer import ConnectionLike, open_connection

configure_logging()
logger = get_logger("demo_memos")

MEMO_DIR = Path(__file__).parent.parent / "docs" / "sample_memos"
BATCH_SPEND_CAP_USD = 20.0

#: Candidate companies: recognizable, non-Financial, sector variety.
CANDIDATES: tuple[str, ...] = (
    "MSFT",   # Information Technology
    "NVDA",   # Information Technology (semis)
    "AMZN",   # Consumer Discretionary
    "GOOG",   # Communication Services (Alphabet filings staged under GOOG)
    "JNJ",    # Health Care
    "CAT",    # Industrials
    "PG",     # Consumer Staples
    "COP",    # Energy (XOM/CVX incorporate MD&A by reference -> text stubs)
    "LIN",    # Materials
)

#: AAPL was generated and judged in Tasks 3-4; included in the README table.
EXISTING = {
    "AAPL": {
        "fiscal_year": 2025,
        "scores": {"factual_grounding": 4, "internal_consistency": 5,
                   "honesty": 5, "specificity": 5},
        "memo_cost": 1.2377,
        "judge_cost": 0.4017,
        "note": "generated in Task 3, judged in Task 4",
    }
}


class CompanyPlan(BaseModel):
    """One company's resolved fiscal year and projected cost."""

    ticker: str
    fiscal_year: int
    current_tokens: int
    prior_tokens: int
    projected_cost_usd: float


def _resolve_plan(ticker: str, connection: ConnectionLike) -> CompanyPlan | None:
    """Find the latest fiscal year with both filings and project the cost."""
    cursor = connection.cursor()
    cursor.execute(
        """
        select max(m.fiscal_year)
        from EDGAR_X.INTERMEDIATE.INT_ML_FEATURES m
        join EDGAR_X.RAW.RAW_FILINGS f on m.accession_number = f.accession_number
        where m.ticker = %s and f.mdna_text is not null
          and f.risk_factors_text is not null
          and exists (
            select 1 from EDGAR_X.INTERMEDIATE.INT_ML_FEATURES p
            join EDGAR_X.RAW.RAW_FILINGS pf on p.accession_number = pf.accession_number
            where p.ticker = m.ticker and p.fiscal_year = m.fiscal_year - 1
              and pf.mdna_text is not null and pf.risk_factors_text is not null
          )
        """,
        (ticker,),
    )
    row = cursor.fetchone()
    if row is None or row[0] is None:
        return None
    fiscal_year = int(row[0])
    current = load_filing_text(ticker, fiscal_year, connection=connection)
    prior = load_filing_text(ticker, fiscal_year - 1, connection=connection)
    if current is None or prior is None:
        return None

    def tokens(filing: object) -> int:
        return int(
            (len(getattr(filing, "mdna_text", "") or "")
             + len(getattr(filing, "risk_factors_text", "") or "")) / 4
        )

    now_tok, prev_tok = tokens(current), tokens(prior)
    sys_tok, struct_tok = 500, 750
    cost = (
        estimate_max_cost("claude-fable-5", input_tokens=sys_tok + now_tok,
                          max_output_tokens=4000)
        + estimate_max_cost("claude-fable-5",
                            input_tokens=sys_tok + now_tok + prev_tok + struct_tok,
                            max_output_tokens=4000)
        + estimate_max_cost("claude-fable-5", input_tokens=sys_tok + struct_tok,
                            max_output_tokens=2000)
        + estimate_max_cost("claude-fable-5", input_tokens=sys_tok + 10_000,
                            max_output_tokens=8000)
        + estimate_max_cost("claude-opus-4-8",
                            input_tokens=sys_tok + now_tok + prev_tok + 4_000,
                            max_output_tokens=1500)
    )
    return CompanyPlan(
        ticker=ticker,
        fiscal_year=fiscal_year,
        current_tokens=now_tok,
        prior_tokens=prev_tok,
        projected_cost_usd=round(cost, 4),
    )


def project() -> list[CompanyPlan]:
    """Resolve all candidates and print the batch cost projection."""
    conn = open_connection()
    plans: list[CompanyPlan] = []
    try:
        for ticker in CANDIDATES:
            plan = _resolve_plan(ticker, conn)
            if plan is None:
                print(f"  {ticker:<6} EXCLUDED: no fiscal year with two consecutive "
                      f"parsed filings")
                continue
            plans.append(plan)
    finally:
        conn.close()

    print(f"\n{'ticker':<8}{'FY':<7}{'cur_tok':>9}{'prev_tok':>9}{'worst_case':>12}")
    for plan in plans:
        print(f"{plan.ticker:<8}{plan.fiscal_year:<7}{plan.current_tokens:>9,}"
              f"{plan.prior_tokens:>9,}{plan.projected_cost_usd:>11.4f}$")
    total = sum(p.projected_cost_usd for p in plans)
    print(f"\nPROJECTED BATCH TOTAL (worst case, {len(plans)} companies): ${total:.2f}")
    print(f"Proposed batch cap: ${BATCH_SPEND_CAP_USD:.2f}")
    print("AAPL is reused from Tasks 3-4 (no respend).")
    return plans


STATE_PATH = MEMO_DIR / ".batch_state.json"


def _load_state() -> dict[str, dict[str, object]]:
    """Load merged per-ticker results from previous batch runs."""
    if STATE_PATH.exists():
        return json.loads(STATE_PATH.read_text())
    return {}


def _save_state(state: dict[str, dict[str, object]]) -> None:
    """Persist per-ticker results so reruns merge instead of forgetting."""
    STATE_PATH.write_text(json.dumps(state, indent=1))


def _warnings_from_json(ticker: str) -> int:
    """Count code-verified warnings from a persisted memo JSON."""
    path = MEMO_DIR / f"{ticker}.json"
    if not path.exists():
        return 0
    memo = json.loads(path.read_text())
    return len(memo.get("traceability_warnings", [])) + len(
        memo.get("signal", {}).get("grounding_warnings", [])
    )


def run(plans: list[CompanyPlan], *, cap: float, reuse_memos: bool) -> None:
    """Execute the batch under one capped tracker and write the README table."""
    tracker = CostTracker(spend_cap_usd=cap)
    state = _load_state()
    failures: list[str] = []

    for plan in plans:
        ticker, fiscal_year = plan.ticker, plan.fiscal_year
        spent_before = tracker.session_total_usd
        try:
            memo_path = MEMO_DIR / f"{ticker}.md"
            if reuse_memos and memo_path.exists():
                memo_cost = float(state.get(ticker, {}).get("memo_cost", 0.0))
                warnings_count = _warnings_from_json(ticker)
                logger.info("memo_reused", ticker=ticker)
            else:
                memo = generate_memo(ticker, fiscal_year, tracker=tracker)
                memo_cost = tracker.session_total_usd - spent_before
                warnings_count = len(memo.traceability_warnings) + len(
                    memo.signal.grounding_warnings
                )

            conn = open_connection()
            try:
                current = load_filing_text(ticker, fiscal_year, connection=conn)
                prior = load_filing_text(ticker, fiscal_year - 1, connection=conn)
                features = load_company_year(ticker, fiscal_year, connection=conn)
                score = load_model_score(ticker, fiscal_year, connection=conn)
            finally:
                conn.close()
            judge_before = tracker.session_total_usd
            result = MemoJudge(tracker=tracker).judge(
                memo_markdown=(MEMO_DIR / f"{ticker}.md").read_text(),
                current_filing=current,  # type: ignore[arg-type]
                prior_filing=prior,
                features=features,  # type: ignore[arg-type]
                score=score,  # type: ignore[arg-type]
            )
            judge_cost = tracker.session_total_usd - judge_before
            report = render_judge_report(result, cost_usd=judge_cost)
            (MEMO_DIR / f"{ticker}_judge_report.md").write_text(report)

            state[ticker] = {
                "ticker": ticker,
                "fiscal_year": fiscal_year,
                "scores": {s.dimension: s.score for s in result.scores},
                "memo_cost": round(memo_cost, 4),
                "judge_cost": round(judge_cost, 4),
                "warnings": warnings_count,
                "note": "",
            }
            _save_state(state)
        except Exception as exc:  # noqa: BLE001 - batch must report, not die
            from agents.cost_tracker import SpendCapExceededError  # noqa: PLC0415

            failures.append(f"{ticker} FY{fiscal_year}: {exc}")
            logger.error("memo_failed", ticker=ticker, error=str(exc))
            if isinstance(exc, SpendCapExceededError):
                print(f"BATCH ABORTED at {ticker}: {exc}")
                break

    rows = sorted(state.values(), key=lambda r: str(r["ticker"]))
    _write_readme(rows, failures, tracker)
    print(f"\nBATCH DONE: {len(rows)} total in table, {len(failures)} failed this run | "
          f"total spend ${tracker.session_total_usd:.4f} / ${tracker.spend_cap_usd:.2f}")
    for failure in failures:
        print(f"  FAILED: {failure}")


def _write_readme(
    rows: list[dict[str, object]], failures: list[str], tracker: CostTracker
) -> None:
    """Write the demo summary table."""
    all_rows = [
        {"ticker": t, "fiscal_year": meta["fiscal_year"], "scores": meta["scores"],
         "memo_cost": meta["memo_cost"], "judge_cost": meta["judge_cost"],
         "warnings": 1, "note": meta["note"]}
        for t, meta in EXISTING.items()
    ] + rows
    lines = [
        "# EDGAR-X sample memos",
        "",
        "Research memos generated by the Layer-4 agent pipeline (Claude Fable 5 "
        "specialists + orchestrator) from real SEC EDGAR data in Snowflake, each "
        "independently scored by an LLM judge (Claude Opus 4.8) against the "
        "primary sources. Scores are 1-5: factual grounding / internal "
        "consistency / honesty / specificity. Warnings are code-verified "
        "traceability or grounding flags — kept visible, never scrubbed.",
        "",
        "| company | FY | grounding | consistency | honesty | specificity | "
        "warnings | memo cost | judge cost |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    pending = [r for r in all_rows if not r["scores"]]
    all_rows = [r for r in all_rows if r["scores"]]
    for row in all_rows:
        scores = row["scores"]
        note = f" ({row['note']})" if row["note"] else ""
        lines.append(
            f"| [{row['ticker']}]({row['ticker']}.md){note} | {row['fiscal_year']} "
            f"| {scores['factual_grounding']} | {scores['internal_consistency']} "
            f"| {scores['honesty']} | {scores['specificity']} | {row['warnings']} "
            f"| ${row['memo_cost']:.2f} | ${row['judge_cost']:.2f} |"
        )
    total_memo = sum(float(r["memo_cost"]) for r in all_rows)
    total_judge = sum(float(r["judge_cost"]) for r in all_rows)
    lines += [
        "",
        f"**Total spend**: ${total_memo + total_judge:.2f} "
        f"(memos ${total_memo:.2f} + judging ${total_judge:.2f}) across "
        f"{len(all_rows)} companies.",
        "",
        "Each `{ticker}_judge_report.md` contains the judge's per-dimension "
        "justifications and the concrete defects it found. Every memo lists its "
        "Snowflake/EDGAR sources and carries code-owned limitations "
        "(ranked-screen model framing, ex-Financials universe, "
        "filing-date-only information).",
    ]
    if pending:
        lines += ["", "## Generated but not yet judged", ""]
        lines += [f"- {r['ticker']} (memo cost ${float(r['memo_cost']):.2f})" for r in pending]
    if failures:
        lines += ["", "## Failed generations (kept honest)", ""]
        lines += [f"- {failure}" for failure in failures]
    lines += [""]
    (MEMO_DIR / "README.md").write_text("\n".join(lines))


def main() -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--project", action="store_true", help="projection only")
    mode.add_argument("--run", action="store_true", help="spend money")
    parser.add_argument("--tickers", type=str, default=None,
                        help="comma-separated subset to process")
    parser.add_argument("--cap", type=float, default=BATCH_SPEND_CAP_USD,
                        help="spend cap for this run (USD)")
    parser.add_argument("--reuse-memos", action="store_true",
                        help="skip generation when {ticker}.md exists; judge only")
    args = parser.parse_args()

    plans = project()
    if args.tickers:
        wanted = {t.strip().upper() for t in args.tickers.split(",")}
        plans = [p for p in plans if p.ticker in wanted]
        print(f"Filtered to {len(plans)} tickers: "
              f"{', '.join(p.ticker for p in plans)}")
    if args.run:
        run(plans, cap=args.cap, reuse_memos=args.reuse_memos)
    return 0


if __name__ == "__main__":
    sys.exit(main())
