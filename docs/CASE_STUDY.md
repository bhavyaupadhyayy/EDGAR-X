# EDGAR-X: an engineering case study

*What it actually takes to turn SEC filings into a trustworthy ML dataset — told through the four bugs that automated data tests caught before they poisoned a model.*

## The problem

Public-company fundamentals look like clean, structured data: the SEC publishes every company's XBRL-tagged financials through a free API. The premise of this project was to treat that promise seriously — build a real pipeline (Kafka, Airflow, Snowflake, dbt), pull genuine data for the S&P 500, and train a model on a question with a self-sourcing label: **for a company's fiscal year N, will FY N+1 revenue be higher?** No purchased consensus data, no synthetic rows, and features restricted to what was knowable on the 10-K filing date.

The interesting engineering wasn't the happy path. It was that *every layer of defensive infrastructure earned its keep within days*: range-bound dbt tests, uniqueness tests, a 20-company sample run before the full backfill, and mandatory baselines in the ML evaluation each caught a distinct, real failure that would otherwise have silently corrupted the dataset or inflated the results.

## The approach

- **Layer 1 — ingestion**: async, rate-limited API clients (SEC caps fair access at 10 req/sec) with retry/backoff, and a checkpointed, idempotent backfill (per-company delete-before-insert) that resumes after a crash without duplicating rows — **this backfill is the path every row of real data took into Snowflake**. Kafka producers/consumers with Avro schemas and per-topic dead-letter queues, plus Airflow DAGs, are built and unit-tested, but the Kafka→Snowflake sink is not yet wired and no scheduled DAG run has landed real data in the warehouse; streaming-to-warehouse is built in parts and planned for completion.
- **Layer 2 — transformation**: dbt with two targets (DuckDB for zero-credential dev, Snowflake via key-pair JWT auth for prod). Staging models deduplicate at-least-once delivery; intermediate models compute financial ratios and filing-language features; 75 tests including a custom `financial_ratio_bounds` generic test.
- **Layer 3 — ML**: a labeled mart (one row per company-fiscal-year), strict time-based splits, Optuna tuning quarantined to training years, two mandatory baselines, SHAP attribution, and a model card that leads with limitations.

Scale achieved: 498 of 503 current S&P 500 constituents, 7,863 company-year fundamentals (FY2007–FY2026), 4,758 parsed 10-Ks, 11,583 macro observations, 6,234 labeled training rows.

## Four war stories from real data

These are the bugs that matter — not exotic, but exactly the kind that quietly destroy financial datasets. Each was caught by an automated check, root-caused to a verifiable fact about SEC data, fixed at the source, and pinned with a regression test.

### 1. The XBRL tag migration (NVIDIA)

**Symptom**: the `net_margin` bounds test (`-2 ≤ margin ≤ 1`) failed with NVDA at **4.46** — net income four times revenue.

**Root cause**: NVIDIA stopped tagging revenue under `RevenueFromContractWithCustomerExcludingAssessedTax` after FY2022 and reverted to the older `Revenues` tag. The extractor tried tags in priority order and accepted the *first tag with any annual fact* — so it anchored revenue to a stale FY2022 fact ($26.9B) while net income resolved to the latest year ($120B). Filers migrate tags over time; tag priority alone cannot be trusted.

**Fix**: resolve each field to the latest annual fact *across all candidate tags* (greatest period end wins). The fix shipped with an NVDA-shaped regression test, and a re-run brought NVDA's FY2026 margin to a sane 0.556.

### 2. Silent pagination truncation (Alphabet)

**Symptom**: on the 20-company sample run — run deliberately before committing to the multi-hour full backfill — Alphabet returned only **3** ten-Ks for a 10-year window. No error, no warning; the log line just said `count=3`.

**Root cause**: EDGAR's submissions API returns a `recent` window capped at ~1,000 filings. Alphabet is a high-volume filer; its window reached back only to 2023. Older filings live in separately-listed archive pages the client never requested. For most companies 1,000 filings covers a decade — which is what makes this failure mode dangerous: it only bites the biggest filers, and silently.

**Fix**: the client now walks the paginated archive files whenever the requested date range predates the `recent` window, with unit tests asserting both that archives are fetched when needed and *not* fetched when they aren't. Alphabet: 3 → 10 filings.

### 3. Revenue that wasn't revenue (the REITs)

**Symptom**: at full-universe scale the margin bounds tests lit up with 169 violations. The worst: AvalonBay FY2018 with revenue of **$3.6M** against net income of **$975M** (real revenue: ~$2.3B). Camden Property Trust showed *negative* gross margins in every year.

**Root cause**: a genuine accounting subtlety. REIT rental income is recognized under lease accounting (ASC 842), which lives *outside* the contract-revenue concept (ASC 606). So a REIT's highest-priority revenue tag legitimately exists — covering only the sliver of non-lease revenue (management fees, etc.). No fixed tag ordering can be right: for Apple the contract-revenue tag *is* total revenue; for AvalonBay it's 0.2% of it.

**Fix**: exploit an invariant instead of an ordering — a revenue *component can never exceed the total*. Per fiscal period, after letting restatements win within each tag, take the **maximum across candidate tags**, and add the ASC 842 lease-income concepts to the candidate set (Camden's real $1.57B revenue lives under `OperatingLeaseLeaseIncome`). Violations went from 169 to 8, and the residual 8 were all one company fixed by the lease-tag addition.

The same investigation produced a second honest decision: banks and insurers showed "margins" of 1.2–25 because *their* revenue genuinely isn't expressible in these concepts at all. Rather than patch them, **Financials (~70 companies) are excluded from the ML dataset**, and the bounds tests are scoped to match — the dataset claims only what it can measure.

### 4. The negative debt restatement (DuPont)

**Symptom**: two rows with *negative* debt-to-equity despite a positive-equity guard.

**Root cause**: DuPont's FY2019 10-K — filed amid the DowDuPont separation — restated `LongTermDebt` as **−$12.6B and −$15.6B**. Those negative facts are really in EDGAR. The pipeline's restatements-beat-originals rule (correct in general) faithfully propagated a filer sign error over the valid original ($38.3B).

**Fix**: fields that are non-negative by definition (debt, assets, liabilities, revenue, shares) now reject negative facts, so the valid original wins — and where every fact is invalid, the field is honestly NULL rather than wrong. FY2018 recovered $38.3B; FY2019 is NULL.

**The meta-lesson** across all four: *range and uniqueness tests on derived ratios are bug detectors for upstream extraction*. Margins are scale-invariant, so they can't catch unit errors — but they're devastatingly effective at catching tag-selection errors, which is where XBRL actually fails. The discipline that mattered most was refusing to widen a test bound until the violating rows were individually inspected: of the bound failures investigated, some were bugs to fix (stories 1, 3, 4) and some were reality to accommodate (post-spin-off Allegion's real debt/equity of 66; COVID-era cruise-line margins near −7; eBay's one-time gain pushing net margin above 1). The test suite now encodes which is which, with the reasoning in comments.

## The modeling result, told honestly

**Setup**: binary label (FY N+1 revenue > FY N revenue), time-based split — train FY2007–2023 (5,787 rows), test FY2024–2025 (447 rows). Optuna tuned on training years only, validated on an inner time split (≤2021 fit / 2022–23 validate); the test set was scored exactly once. Test base rate: **83% positive** — current S&P 500 members usually grow.

| model | accuracy | precision | recall | F1 | **ROC-AUC** |
|---|---|---|---|---|---|
| majority class ("always up") | 0.830 | 0.830 | 1.000 | 0.907 | 0.500 |
| logistic regression | 0.834 | 0.838 | 0.992 | 0.909 | 0.607 |
| XGBoost (tuned) | 0.830 | 0.830 | 1.000 | 0.907 | **0.726** |

**Why AUC leads**: with an 83% base rate, accuracy is a trap — XGBoost's hard predictions at the default 0.5 threshold are all-positive, making its accuracy *identical to the do-nothing baseline*. The model's real output is a ranking: AUC 0.726 means a randomly chosen revenue-decliner scores below a randomly chosen grower 73% of the time, a clear lift over logistic regression's 0.607. **The deliverable is a ranked screen** — "which companies look most likely to shrink?" — not a classifier, and no document in this repo claims otherwise. Inner-validation AUC (0.730) matched test AUC (0.726), evidence the tuning didn't overfit.

**SHAP findings**: revenue momentum (`revenue_growth_1y`) dominates, followed by company size and the macro regime at filing time (yield-curve spread, CPI YoY, unemployment). By feature family: fundamentals 39%, macro 29%, sector 16%, **filing-language 16%**. Two language features (`risk_word_total`, `impairment_mentions`) reach the top 12 — but language covers only 56% of rows (the 10-year filing lookback reaches only the newer half of the 19 labeled fiscal years, FY2007–FY2025), and tree models partially exploit the *missingness pattern itself*. Honest verdict: language signal is **present but unproven**; a fair test requires full filing coverage.

## Limitations and honest scoping

- **Survivorship bias**: the universe is the *current* S&P 500. Companies that shrank out of the index are absent, which inflates the positive base rate and likely flatters measured predictability. Results do not generalize to "stocks" — at best to "companies resembling current large-caps."
- **Financials excluded** (~70 companies): their revenue is not captured by the XBRL concepts used. Every metric is for the *S&P 500 ex-Financials*.
- **2 of 5 designed data streams carry real data** (EDGAR, FRED). Options flow, Reddit sentiment, and earnings-call transcripts are scaffolded at every hop (clients, Avro schemas, topics, empty warehouse tables) but intentionally unpopulated.
- **The real data path is the backfill script, not streaming**: Kafka producers, Avro schemas, and Airflow DAGs exist and are unit-tested, but the Kafka→Snowflake sink is not wired and no scheduled DAG run has landed real data in the warehouse.
- **Not deployed**: this is production-*quality* engineering (typed, tested, idempotent, observable) running on a laptop against a real warehouse — not a deployed, monitored production system. The Layer-4 agent tier is built and demonstrated on 5 companies ([docs/sample_memos/README.md](sample_memos/README.md)), but it runs on-demand from a laptop. The Layer-5 self-improvement loop (outcome tracking, calibration, retraining trigger) is also built, with its calibration findings explicitly caveated as preliminary on a 447-row out-of-sample window and its retrain execution scaffolded for Layer 7. The Layer-6 Streamlit dashboard is built and deploys free on Community Cloud against a committed static snapshot (no live DB/API/secrets); the Layer-6 FastAPI service and Layer 7 (cloud deployment) are design only.
- **Prediction time is the filing date**, not fiscal year end — macro features legitimately include the first ~2–3 months of FY N+1.
- **Residual XBRL noise**: extraction is best-effort against a messy reality; bounds tests catch gross errors, not subtle ones, in both features and labels.

## What's next

In intended order, none of it started:

1. **Wire streaming to the warehouse** — connect the existing Kafka topics to a Snowflake sink and let the Airflow DAGs run real data on a schedule, replacing the one-shot backfill as the ongoing ingestion path.
2. **The remaining data streams** — populate options flow, sentiment, and transcript pipelines; their staging models and tests already exist.
3. **Scaling the agent tier (Layer 4 is built)** — the agent tier exists: three source-attributed specialists, a Fable 5 orchestrator with code-side traceability verification, and an Opus 4.8 judge, demonstrated on 5 companies under hard spend caps ([docs/sample_memos/README.md](sample_memos/README.md)). What remains is scale: scheduled generation across the universe and completing the companies cut short by output-cap and billing interruptions.
4. **Serving (Layer 6)** — the Streamlit dashboard is built and deployable free on a static snapshot; a FastAPI service over the marts and the ranked screen remains future work.
5. **Deployment (Layer 7)** — containerized services to cloud infrastructure with CI/CD and monitoring, at which point "production-quality" could honestly become "production."
6. **Fixing survivorship bias** — backfilling *historical* index membership is the single highest-value data improvement: it would make the label distribution honest and the model evaluable on the companies that actually declined.
