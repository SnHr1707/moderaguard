"""Drift check every 10 minutes (owners: M2 schedules, M7 owns the job).

1. Build the drift reference once (scores training-era comments through the gateway).
2. Compare the latest predictions with the reference and push the result to
   the Pushgateway. Prometheus scrapes it; Alertmanager decides on retraining.
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta

from airflow.providers.standard.operators.bash import BashOperator
from airflow.sdk import DAG

# The shared helpers live next to this file. Airflow 3 does not always put the
# DAGs folder on sys.path, so add it explicitly.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from moderaguard_common import DEFAULT_ARGS, ML_ENV, REPO, cmd  # noqa: E402

DRIFT = "services/drift-job/drift.py"

with DAG(
    dag_id="drift_check_dag",
    description="Evidently drift check on recent predictions",
    schedule=timedelta(minutes=10),
    start_date=datetime(2026, 10, 1),
    catchup=False,
    max_active_runs=1,
    default_args=DEFAULT_ARGS,
    tags=["moderaguard", "monitoring"],
) as dag:
    reference = BashOperator(
        task_id="ensure_reference",
        bash_command=f"test -f {REPO}/reports/drift/reference.parquet || ({cmd(DRIFT + ' build-reference')})",
        env=ML_ENV,
    )
    check = BashOperator(task_id="check_drift", bash_command=cmd(f"{DRIFT} run"), env=ML_ENV)

    reference >> check
