"""Shared paths and settings. Everything reads params.yaml through here."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

import yaml

ROOT = Path(os.environ.get("MODERAGUARD_ROOT", Path(__file__).resolve().parents[2]))
DATA_DIR = ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
SAMPLE_DIR = DATA_DIR / "sample"
PROCESSED_DIR = DATA_DIR / "processed"
MODELS_DIR = ROOT / "models"
REPORTS_DIR = ROOT / "reports"

# Names shared across the whole system (see docs/contracts.md)
TASKS = ("toxicity", "spam", "langid")
REGISTERED_MODEL_NAMES = {task: f"moderaguard-{task}" for task in TASKS}
CHAMPION_ALIAS = "champion"
CHALLENGER_ALIAS = "challenger"


@lru_cache(maxsize=1)
def params() -> dict:
    """Load params.yaml once per process."""
    path = Path(os.environ.get("MODERAGUARD_PARAMS", ROOT / "params.yaml"))
    with open(path) as f:
        return yaml.safe_load(f)


def ensure_dirs() -> None:
    for d in (PROCESSED_DIR, MODELS_DIR, REPORTS_DIR):
        d.mkdir(parents=True, exist_ok=True)
