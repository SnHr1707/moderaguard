"""Shared test fixtures.

Unit tests never need MLflow, Kafka or Postgres. The `trained_models` fixture
builds the sample data and trains small models once per test session (a few
seconds) if they are not already present.
"""

from __future__ import annotations

import os

os.environ.setdefault("MODERAGUARD_DISABLE_MLFLOW", "1")
os.environ.setdefault("MODEL_SOURCE", "local")

import pytest  # noqa: E402

from moderaguard.config import MODELS_DIR, PROCESSED_DIR, SAMPLE_DIR  # noqa: E402


@pytest.fixture(scope="session")
def processed_data():
    if not (SAMPLE_DIR / "jigsaw" / "all_data.csv").exists():
        from moderaguard.data import make_sample

        make_sample.main([])
    if not (PROCESSED_DIR / "toxicity_train.parquet").exists():
        from moderaguard.data import prepare

        prepare.main([])
    return PROCESSED_DIR


@pytest.fixture(scope="session")
def trained_models(processed_data):
    from moderaguard.models import train

    for task in ("toxicity", "spam", "langid"):
        if not (MODELS_DIR / task / "champion" / "model.joblib").exists():
            train.main(["--task", task, "--variant", "champion"])
    return MODELS_DIR
