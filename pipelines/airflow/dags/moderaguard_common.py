"""Shared settings for the ModeraGuard DAGs (owner: M2).

The ML code runs in its own virtualenv inside the Airflow image (/opt/ml-venv),
so its dependencies (scikit-learn, MLflow, Evidently) never clash with Airflow's.
The repository is mounted at /opt/moderaguard.
"""

from __future__ import annotations

import os

REPO = os.environ.get("MODERAGUARD_REPO", "/opt/moderaguard")
PY = os.environ.get("ML_PYTHON", "/opt/ml-venv/bin/python")

# Passed to every task so the ML code reaches MLflow, S3 and Postgres.
# These are added on top of the Airflow worker's own environment (append_env
# below). Without that, a BashOperator `env` REPLACES the whole environment, and
# PYTHONPATH, HOME etc. disappear, so `python -m moderaguard...` cannot be found.
ML_ENV = {
    "MODERAGUARD_ROOT": REPO,
    "PYTHONPATH": f"{REPO}/src",
    "MPLCONFIGDIR": "/tmp/matplotlib",
    "MLFLOW_TRACKING_URI": os.environ.get("MLFLOW_TRACKING_URI", "http://mlflow:5000"),
    "MLFLOW_S3_ENDPOINT_URL": os.environ.get("MLFLOW_S3_ENDPOINT_URL", "http://s3:8333"),
    "AWS_ACCESS_KEY_ID": os.environ.get("AWS_ACCESS_KEY_ID", ""),
    "AWS_SECRET_ACCESS_KEY": os.environ.get("AWS_SECRET_ACCESS_KEY", ""),
    "PREDICTIONS_DSN": os.environ.get("PREDICTIONS_DSN", ""),
    "GATEWAY_URL": os.environ.get("GATEWAY_URL", "http://gateway:8000"),
    "PUSHGATEWAY": os.environ.get("PUSHGATEWAY", "pushgateway:9091"),
    "DATA_DIR": f"{REPO}/data/processed",
    "DRIFT_DIR": f"{REPO}/reports/drift",
    "JENKINS_URL": os.environ.get("JENKINS_URL", ""),
    "JENKINS_USER": os.environ.get("JENKINS_USER", ""),
    "JENKINS_API_TOKEN": os.environ.get("JENKINS_API_TOKEN", ""),
    "PATH": "/opt/ml-venv/bin:/usr/local/bin:/usr/bin:/bin",
}

# append_env=True: keep the worker's environment and add ML_ENV on top.
DEFAULT_ARGS = {"owner": "moderaguard", "retries": 1, "append_env": True}


def cmd(module_or_script: str) -> str:
    """Build a bash command that runs ML code from the repo root."""
    return f"cd {REPO} && {PY} {module_or_script}"
