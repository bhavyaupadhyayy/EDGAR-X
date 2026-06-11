"""Shared Airflow alerting callbacks for all EDGAR-X DAGs.

Failures and SLA misses are logged as structured JSON and, when
``SLACK_WEBHOOK_URL`` is configured, posted to Slack. Alerting must never
raise — a broken webhook should not mask the original task failure.
"""

from __future__ import annotations

from typing import Any

import httpx

from core.config import get_settings
from core.logging import configure_logging, get_logger

configure_logging()
logger = get_logger(__name__)


def _post_to_slack(text: str) -> None:
    """Post an alert to Slack when a webhook is configured; never raises."""
    webhook_url = get_settings().slack_webhook_url
    if not webhook_url:
        return
    try:
        response = httpx.post(webhook_url, json={"text": text}, timeout=10.0)
        response.raise_for_status()
    except httpx.HTTPError as exc:
        logger.error("slack_alert_failed", error=str(exc))


def on_failure_callback(context: dict[str, Any]) -> None:
    """Airflow task failure callback: structured log + optional Slack alert.

    Args:
        context: The Airflow task context dict.
    """
    task_instance = context.get("task_instance")
    dag_id = getattr(task_instance, "dag_id", "unknown")
    task_id = getattr(task_instance, "task_id", "unknown")
    exception = context.get("exception")
    logger.error(
        "airflow_task_failed",
        dag_id=dag_id,
        task_id=task_id,
        execution_date=str(context.get("logical_date") or context.get("execution_date")),
        error=str(exception),
    )
    _post_to_slack(f":rotating_light: EDGAR-X task failed: `{dag_id}.{task_id}` — {exception}")


def sla_miss_callback(
    dag: Any,
    task_list: str,
    blocking_task_list: str,
    slas: list[Any],
    blocking_tis: list[Any],
) -> None:
    """Airflow SLA-miss callback: structured log + optional Slack alert.

    Args:
        dag: The DAG that missed its SLA.
        task_list: Newline-separated task ids that missed the SLA.
        blocking_task_list: Tasks blocking the SLA-missed tasks.
        slas: SLA records.
        blocking_tis: Blocking task instances.
    """
    dag_id = getattr(dag, "dag_id", "unknown")
    logger.warning(
        "airflow_sla_missed", dag_id=dag_id, tasks=task_list, blocking=blocking_task_list
    )
    _post_to_slack(f":hourglass: EDGAR-X SLA missed in `{dag_id}`: {task_list}")
