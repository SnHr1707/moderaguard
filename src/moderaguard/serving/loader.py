"""Load a task model for serving (owner: M5).

MODEL_SOURCE=mlflow  -> models:/moderaguard-<task>@<MODEL_ALIAS> from the registry
MODEL_SOURCE=local   -> models/<task>/<variant>/model.joblib (no MLflow needed;
                        used by tests and for quick local runs)
"""

from __future__ import annotations

import os
from pathlib import Path

import joblib

from moderaguard.config import MODELS_DIR, REGISTERED_MODEL_NAMES


def load_model(task: str, source: str | None = None, alias: str | None = None):
    source = source or os.environ.get("MODEL_SOURCE", "local")
    alias = alias or os.environ.get("MODEL_ALIAS", "champion")
    if source == "mlflow":
        import mlflow.pyfunc

        uri = f"models:/{REGISTERED_MODEL_NAMES[task]}@{alias}"
        impl = mlflow.pyfunc.load_model(uri).unwrap_python_model().impl
        impl.version = f"{getattr(impl, 'version', 'unknown')} ({alias})"
        return impl
    model_dir = Path(os.environ.get("MODEL_DIR", MODELS_DIR / task / alias))
    return joblib.load(model_dir / "model.joblib")
