"""Retraining after drift (owner: M2; steps owned by M1, M3, M4, M6).

Started by the alert bridge when Alertmanager fires `ModelDriftDetected`
(or manually from the Airflow UI).

  prepare (with newly labelled comments) -> validate
    -> train candidate ----------------------\
    -> re-score current champion on new data --> fairness audit -> quality gate
    -> register candidate as @challenger -> ask Jenkins to roll it out as a canary

If the quality gate fails, the DAG stops there and the champion stays live.
"""

from __future__ import annotations

import os
import sys

from airflow.providers.standard.operators.bash import BashOperator
from airflow.sdk import DAG

# The shared helpers live next to this file. Airflow 3 does not always put the
# DAGs folder on sys.path, so add it explicitly.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from moderaguard_common import DEFAULT_ARGS, ML_ENV, cmd  # noqa: E402

TRIGGER_JENKINS = """
if [ -z "$JENKINS_URL" ]; then
  echo "JENKINS_URL not set: run the 'moderaguard' Jenkins job with DEPLOY_MODE=canary-registered to roll out the challenger."
  exit 0
fi
curl -fsS -X POST -u "$JENKINS_USER:$JENKINS_API_TOKEN" \
  "$JENKINS_URL/job/moderaguard/buildWithParameters?DEPLOY_MODE=canary-registered&REASON=drift-retrain"
"""

with DAG(
    dag_id="retrain_dag",
    description="Retrain the toxicity model on new data, gate it, register it as challenger",
    schedule=None,
    catchup=False,
    max_active_runs=1,
    default_args=DEFAULT_ARGS,
    tags=["moderaguard", "training"],
) as dag:
    prepare = BashOperator(task_id="prepare_with_new_data",
                           bash_command=cmd("-m moderaguard.data.prepare --include-stream"), env=ML_ENV)
    validate = BashOperator(task_id="validate", bash_command=cmd("-m moderaguard.data.validate"), env=ML_ENV)
    train = BashOperator(
        task_id="train_candidate",
        bash_command=cmd("-m moderaguard.models.train --task toxicity --variant champion --name candidate"),
        env=ML_ENV,
    )
    rescore = BashOperator(
        task_id="rescore_champion",
        bash_command=cmd("-m moderaguard.models.rescore --task toxicity --alias champion --source mlflow"),
        env=ML_ENV,
    )
    fairness = BashOperator(task_id="fairness_audit",
                            bash_command=cmd("-m moderaguard.responsible.fairness --variant candidate champion"),
                            env=ML_ENV)
    gate = BashOperator(
        task_id="quality_gate",
        bash_command=cmd("-m moderaguard.responsible.quality_gate --task toxicity --candidate candidate --baseline champion"),
        env=ML_ENV,
    )
    register = BashOperator(
        task_id="register_challenger",
        bash_command=cmd("-m moderaguard.models.register register --task toxicity --variant candidate --alias challenger"),
        env=ML_ENV,
    )
    deploy = BashOperator(task_id="request_canary_deploy", bash_command=TRIGGER_JENKINS, env=ML_ENV, retries=0)

    prepare >> validate >> [train, rescore] >> fairness >> gate >> register >> deploy
