"""Airflow DAG integrity tests (owner: M2).

Skipped unless Airflow is installed (it is in the Airflow image and in CI's
`airflow-dags` job). Run locally with:
  pip install "apache-airflow==3.3.2" --constraint \
    https://raw.githubusercontent.com/apache/airflow/constraints-3.3.2/constraints-3.12.txt
  pytest tests/unit/test_dags.py
"""

from pathlib import Path

import pytest

airflow = pytest.importorskip("airflow")

DAGS = Path(__file__).resolve().parents[2] / "pipelines" / "airflow" / "dags"


@pytest.fixture(scope="module")
def bag():
    from airflow.dag_processing.dagbag import DagBag

    return DagBag(dag_folder=str(DAGS))


def test_no_import_errors(bag):
    assert bag.import_errors == {}


def test_expected_dags(bag):
    assert set(bag.dags) == {"ingest_dag", "drift_check_dag", "retrain_dag"}


def test_retrain_gate_runs_before_registration(bag):
    dag = bag.dags["retrain_dag"]
    order = [t.task_id for t in dag.topological_sort()]
    assert order.index("quality_gate") < order.index("register_challenger") < order.index("request_canary_deploy")
    assert dag.get_task("fairness_audit").upstream_task_ids == {"train_candidate", "rescore_champion"}


def test_retrain_is_only_triggered_not_scheduled(bag):
    assert type(bag.dags["retrain_dag"].timetable).__name__ == "NullTimetable"


def test_tasks_keep_the_worker_environment(bag):
    """A BashOperator `env` replaces the whole environment unless append_env is set;
    then PYTHONPATH is lost and `python -m moderaguard...` fails in every task."""
    for dag in bag.dags.values():
        for task in dag.tasks:
            if getattr(task, "env", None):
                assert task.append_env, f"{dag.dag_id}.{task.task_id} would drop PYTHONPATH"
                assert task.env["PYTHONPATH"].endswith("/src")
