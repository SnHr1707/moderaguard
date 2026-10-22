"""Daily ingestion: prepare -> validate -> report (owner: M2).

Re-runs the data stages so the processed splits and the validation report stay
current when new raw data lands in data/raw/. A validation failure stops the
DAG and shows up red in the Airflow UI.
"""

from __future__ import annotations

import os
import sys
from datetime import datetime

from airflow.providers.standard.operators.bash import BashOperator
from airflow.sdk import DAG

# The shared helpers live next to this file. Airflow 3 does not always put the
# DAGs folder on sys.path, so add it explicitly.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from moderaguard_common import DEFAULT_ARGS, ML_ENV, cmd  # noqa: E402

with DAG(
    dag_id="ingest_dag",
    description="Prepare and validate the ModeraGuard datasets",
    schedule="@daily",
    start_date=datetime(2026, 10, 1),
    catchup=False,
    default_args=DEFAULT_ARGS,
    tags=["moderaguard", "data"],
) as dag:
    prepare = BashOperator(task_id="prepare", bash_command=cmd("-m moderaguard.data.prepare"), env=ML_ENV)
    validate = BashOperator(task_id="validate", bash_command=cmd("-m moderaguard.data.validate"), env=ML_ENV)
    summary = BashOperator(task_id="summary", bash_command="cat /opt/moderaguard/reports/data_summary.json")

    prepare >> validate >> summary
