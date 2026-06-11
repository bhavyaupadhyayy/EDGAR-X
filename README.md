# EDGAR-X

Autonomous multi-agent financial intelligence operating system. Monitors the
US public equity universe across five data modalities, runs a three-tier
agent hierarchy orchestrated by Claude Fable 5, trains and retrains its own
ML models, and serves institutional-grade research via a real-time API and
dashboard.

## Build status

| Layer | Scope | Status |
|---|---|---|
| 1 | Ingestion infrastructure (clients, Kafka/Avro, DLQ, Airflow, compose) | ✅ Built |
| 2 | dbt transformation layer | ⬜ Pending |
| 3 | ML models (XGBoost, Isolation Forest, Bayesian calibrator) | ⬜ Pending |
| 4 | Agent architecture (Tier 1/2 + Fable 5 orchestrator) | ⬜ Pending |
| 5 | Self-improvement loop | ⬜ Pending |
| 6 | FastAPI + Streamlit dashboard | ⬜ Pending |
| 7 | Terraform / Kubernetes / CI-CD / monitoring | ⬜ Pending |

## Layer 1 architecture

```
 EDGAR ─┐
 FRED ──┤   async clients          Kafka (Avro + Schema Registry)
 Polygon┼─► rate limit + retry ──► filings.raw / transcripts.raw /
 Reddit ┤   (httpx / asyncpraw)    macro.raw / options.unusual_activity /
 Fool ──┘        ▲                 sentiment.raw   (+ per-topic .dlq)
                 │
        Airflow DAGs (hourly/daily/intraday, SLA + failure alerting)
```

- `ingestion/sources/` — five async source clients sharing one tested
  rate-limiter/retry core (`http_utils.py`).
- `ingestion/kafka/` — Avro producer/consumer with Schema Registry and a
  dead letter queue; poison messages never block a partition.
- `ingestion/airflow/dags/` — five ingestion DAGs plus the Layer-5
  retraining placeholder, all with retries, SLAs, and Slack-or-log alerting.

## Quickstart

```bash
cp .env.example .env            # fill in API keys + a real EDGAR_USER_AGENT
docker compose up -d            # Kafka, Schema Registry, Airflow, Redis, Postgres
# dev extras (Kafka UI on :8090, MinIO on :9001):
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d
```

Airflow UI: <http://localhost:8080> (admin/admin, dev only).

## Development

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e '.[dev]'
pytest                          # 80% coverage gate enforced
ruff check . && mypy ingestion core
```

## Conventions

- Python 3.11+, async-first (httpx/asyncpraw), full type hints.
- Pydantic v2 models on every module boundary.
- structlog JSON logging with correlation ids (`core/logging.py`).
- All configuration via environment variables — see `.env.example`.
- Every module has a matching test in `tests/unit/`.
