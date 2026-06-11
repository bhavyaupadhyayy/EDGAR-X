"""Automated model retraining pipeline — implemented in Layer 5.

This placeholder registers a paused DAG so the dag-bag stays consistent; the
real pipeline (performance-decay trigger → feature refresh → retrain →
evaluate → promote artifact) lands with the self-improvement loop.
"""

from __future__ import annotations

from airflow import DAG
from airflow.operators.empty import EmptyOperator

from ingestion.airflow.dags._common import DEFAULT_ARGS, START_DATE

with DAG(
    dag_id="model_retraining",
    description="Placeholder: automated retraining pipeline (Layer 5)",
    schedule=None,
    start_date=START_DATE,
    catchup=False,
    is_paused_upon_creation=True,
    default_args=DEFAULT_ARGS,
    tags=["ml", "placeholder"],
) as dag:
    placeholder = EmptyOperator(task_id="placeholder_layer_5")
