"""Thin helpers around MLflow so training code stays readable (owner: M3).

Set MLFLOW_TRACKING_URI (e.g. http://localhost:5000) to log to the shared
server; without it MLflow logs to a local store. Set MODERAGUARD_DISABLE_MLFLOW=1
to skip MLflow entirely (used by unit tests).
"""

from __future__ import annotations

import contextlib
import os
import subprocess
from pathlib import Path


def mlflow_enabled() -> bool:
    return os.environ.get("MODERAGUARD_DISABLE_MLFLOW", "0") != "1"


def git_commit() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], stderr=subprocess.DEVNULL).decode().strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return "unknown"


@contextlib.contextmanager
def run(experiment: str, run_name: str, tags: dict | None = None):
    """Yield an active MLflow run, or None when MLflow is disabled."""
    if not mlflow_enabled():
        yield None
        return
    import mlflow

    mlflow.set_experiment(experiment)
    with mlflow.start_run(run_name=run_name, tags={"git_commit": git_commit(), **(tags or {})}) as active:
        yield active


def log_pyfunc_model(model_file: Path, input_example: list[str]) -> str:
    """Log a joblib model file as an MLflow pyfunc in the active run. Returns the model URI."""
    import mlflow
    import pandas as pd

    from moderaguard.models.pyfunc import ModeraGuardPyfunc

    info = mlflow.pyfunc.log_model(
        name="model",
        python_model=ModeraGuardPyfunc(),
        artifacts={"model": str(model_file)},
        input_example=pd.DataFrame({"text": input_example}),
        pip_requirements=["scikit-learn", "pandas", "joblib", "mlflow-skinny"],
    )
    return info.model_uri
