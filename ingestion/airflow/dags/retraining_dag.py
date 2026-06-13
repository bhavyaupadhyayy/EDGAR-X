"""Self-improvement retraining pipeline DAG.

SCAFFOLD PENDING LAYER 7. The task graph is real and reflects the Layer-5
self-improvement loop — refresh outcomes -> calibration -> trigger check ->
conditional retrain -> update training state — but it is created PAUSED and is
not scheduled. It runs only once Layer 7 wires deployment (Airflow image with
the project + Snowflake/Anthropic credentials, scheduling, artifact promotion,
and rollback). Until then the trigger decision is produced on-demand via
``python -m self_improvement.retraining_trigger`` in dry-run mode.

The PythonOperator callables import lazily and are thin wrappers over the
working Layer-5 modules; the conditional-retrain branch deliberately stays in
dry-run unless an explicit Airflow Variable enables execution.
"""

from __future__ import annotations

from typing import Any

from airflow import DAG
from airflow.operators.empty import EmptyOperator
from airflow.operators.python import BranchPythonOperator, PythonOperator

from ingestion.airflow.dags._common import DEFAULT_ARGS, START_DATE


def _refresh_outcomes(**_: Any) -> int:
    """Re-score predictions so newly-materialized outcomes are reflected."""
    from self_improvement.score_predictions import score_all  # noqa: PLC0415

    return score_all()


def _run_calibration(**_: Any) -> str:
    """Rebuild the calibration report from the refreshed outcomes."""
    from self_improvement.calibration import build_report, load_outcomes, main  # noqa: PLC0415

    main()  # writes docs/calibration_report.{json,md}
    return build_report(load_outcomes()).verdict


def _check_trigger(**_: Any) -> str:
    """Evaluate the retrain trigger; branch on the decision."""
    from self_improvement.retraining_trigger import (  # noqa: PLC0415
        evaluate_trigger,
        load_calibration_report,
        load_training_state,
    )

    decision = evaluate_trigger(load_calibration_report(), load_training_state())
    return "conditional_retrain" if decision.retrain_needed else "no_retrain_needed"


def _conditional_retrain(**_: Any) -> bool:
    """Retrain ONLY if an explicit Airflow Variable opts in (Layer 7 control)."""
    from airflow.models import Variable  # noqa: PLC0415

    from self_improvement.retraining_trigger import (  # noqa: PLC0415
        evaluate_trigger,
        load_calibration_report,
        load_training_state,
    )

    # Default OFF: even when the trigger fires, execution requires an operator
    # to set edgar_x_enable_retrain=true. Prevents surprise compute/cost spend.
    enabled = Variable.get("edgar_x_enable_retrain", default_var="false") == "true"
    decision = evaluate_trigger(load_calibration_report(), load_training_state())
    from self_improvement.retraining_trigger import maybe_retrain  # noqa: PLC0415

    return maybe_retrain(decision, dry_run=not enabled)


with DAG(
    dag_id="model_retraining",
    description="Layer-5 self-improvement loop (SCAFFOLD — paused pending Layer 7)",
    schedule=None,
    start_date=START_DATE,
    catchup=False,
    is_paused_upon_creation=True,
    default_args=DEFAULT_ARGS,
    tags=["ml", "self-improvement", "scaffold"],
) as dag:
    refresh_outcomes = PythonOperator(
        task_id="refresh_outcomes", python_callable=_refresh_outcomes
    )
    calibration = PythonOperator(
        task_id="calibration", python_callable=_run_calibration
    )
    trigger_check = BranchPythonOperator(
        task_id="trigger_check", python_callable=_check_trigger
    )
    conditional_retrain = PythonOperator(
        task_id="conditional_retrain", python_callable=_conditional_retrain
    )
    no_retrain_needed = EmptyOperator(task_id="no_retrain_needed")

    refresh_outcomes >> calibration >> trigger_check >> [
        conditional_retrain,
        no_retrain_needed,
    ]
