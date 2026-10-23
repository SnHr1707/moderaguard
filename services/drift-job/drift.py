"""Drift detection with Evidently (owner: M7).

Compares the most recent predictions (from the consumer's Postgres table) with
a reference window built from the data the model was trained on, and pushes
the result to the Prometheus Pushgateway. Alertmanager fires the retrain alert
when the drifted-feature share crosses `drift.threshold` in params.yaml.

Features compared (all cheap to compute, no labels needed):
  text_length, word_count       how comments are written
  oov_rate                      share of words never seen in training: rises with new slang
  toxicity, spam                the models' own outputs: prediction drift

Usage:
  python services/drift-job/drift.py build-reference   # once, after training (calls the gateway)
  python services/drift-job/drift.py run               # every N minutes, scheduled by Airflow

Env: PREDICTIONS_DSN, GATEWAY_URL [http://gateway:8000], PUSHGATEWAY [pushgateway:9091],
     DATA_DIR [data/processed], DRIFT_DIR [reports/drift]
"""

from __future__ import annotations

import argparse
import json
import os
import re
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

FEATURES = ["text_length", "word_count", "oov_rate", "toxicity", "spam"]
_WORD = re.compile(r"[a-z']+")
DRIFT_DIR = Path(os.environ.get("DRIFT_DIR", "reports/drift"))


def text_features(texts: pd.Series, vocab: set[str]) -> pd.DataFrame:
    words = texts.fillna("").str.lower().map(_WORD.findall)
    return pd.DataFrame({
        "text_length": texts.fillna("").str.len().astype(float),
        "word_count": words.map(len).astype(float),
        "oov_rate": words.map(lambda ws: sum(w not in vocab for w in ws) / len(ws) if ws else 0.0),
    })


def compute_drift(reference: pd.DataFrame, current: pd.DataFrame, html_path: Path | None = None) -> dict:
    """Run Evidently's data drift preset. Returns the drifted share and a p-value per feature."""
    from evidently import DataDefinition, Dataset, Report
    from evidently.presets import DataDriftPreset

    cols = [c for c in FEATURES if c in reference and c in current]
    definition = DataDefinition(numerical_columns=cols)
    snapshot = Report([DataDriftPreset()]).run(
        current_data=Dataset.from_pandas(current[cols].dropna(), data_definition=definition),
        reference_data=Dataset.from_pandas(reference[cols].dropna(), data_definition=definition),
    )
    if html_path is not None:
        html_path.parent.mkdir(parents=True, exist_ok=True)
        snapshot.save_html(str(html_path))

    share, per_feature = 0.0, {}
    for metric in snapshot.dict()["metrics"]:
        mid = metric.get("metric_name") or metric.get("metric_id") or ""
        if mid.startswith("DriftedColumnsCount"):
            share = float(metric["value"]["share"])
        elif mid.startswith("ValueDrift"):
            column = re.search(r"column=([^,)]+)", mid).group(1)
            per_feature[column] = float(metric["value"])
    return {"drift_share": round(share, 4), "p_values": per_feature,
            "n_reference": len(reference), "n_current": len(current)}


def push(result: dict, gateway: str) -> None:
    from prometheus_client import CollectorRegistry, Gauge, push_to_gateway

    registry = CollectorRegistry()
    Gauge("moderaguard_drift_share", "Share of drifted features", registry=registry).set(result["drift_share"])
    pv = Gauge("moderaguard_drift_p_value", "Drift test p-value per feature", ["feature"], registry=registry)
    for feature, value in result["p_values"].items():
        pv.labels(feature).set(value)
    Gauge("moderaguard_drift_window_size", "Comments in the current window", registry=registry).set(result["n_current"])
    Gauge("moderaguard_drift_last_run_timestamp", "Last drift run", registry=registry).set_to_current_time()
    push_to_gateway(gateway, job="moderaguard-drift", registry=registry)


def build_reference(n: int = 500) -> None:
    import httpx

    data_dir = Path(os.environ.get("DATA_DIR", "data/processed"))
    train = pd.read_parquet(data_dir / "toxicity_train.parquet", columns=["comment_text"])
    vocab = sorted({w for t in train["comment_text"].str.lower() for w in _WORD.findall(t)})
    ref = pd.read_parquet(data_dir / "toxicity_test.parquet", columns=["comment_text"]).sample(
        min(n, 10_000), random_state=0)

    gateway = os.environ.get("GATEWAY_URL", "http://gateway:8000")
    scores = []
    with httpx.Client(timeout=10) as client:
        for text in ref["comment_text"]:
            r = client.post(f"{gateway}/moderate", json={"text": text}).json()
            scores.append({"toxicity": r["toxicity"], "spam": r["spam"]})
    reference = pd.concat([text_features(ref["comment_text"].reset_index(drop=True), set(vocab)),
                           pd.DataFrame(scores)], axis=1)
    DRIFT_DIR.mkdir(parents=True, exist_ok=True)
    reference.to_parquet(DRIFT_DIR / "reference.parquet", index=False)
    (DRIFT_DIR / "vocab.json").write_text(json.dumps(vocab))
    print(f"[drift] reference built from {len(reference)} comments, vocabulary {len(vocab)} words")


def load_current(window: int) -> pd.DataFrame:
    import psycopg2

    dsn = os.environ.get("PREDICTIONS_DSN", "postgresql://moderaguard:moderaguard@postgres:5432/moderaguard")
    with psycopg2.connect(dsn) as conn:
        return pd.read_sql(
            "SELECT text, toxicity, spam FROM predictions WHERE language = 'en' ORDER BY ts DESC LIMIT %s",
            conn, params=(window,))


def run(window: int, min_rows: int = 100) -> dict | None:
    reference = pd.read_parquet(DRIFT_DIR / "reference.parquet")
    vocab = set(json.loads((DRIFT_DIR / "vocab.json").read_text()))
    current_raw = load_current(window)
    if len(current_raw) < min_rows:
        print(f"[drift] only {len(current_raw)} predictions so far, need {min_rows}; skipping")
        return None
    current = pd.concat([text_features(current_raw["text"], vocab), current_raw[["toxicity", "spam"]]], axis=1)
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    result = compute_drift(reference, current, DRIFT_DIR / f"report-{stamp}.html")
    result["ts"] = stamp
    (DRIFT_DIR / "latest.json").write_text(json.dumps(result, indent=2))
    push(result, os.environ.get("PUSHGATEWAY", "pushgateway:9091"))
    print(json.dumps(result, indent=2))
    return result


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=["build-reference", "run"])
    parser.add_argument("--window", type=int, default=int(os.environ.get("DRIFT_WINDOW", 1000)))
    args = parser.parse_args(argv)
    if args.command == "build-reference":
        build_reference()
    else:
        run(args.window)


if __name__ == "__main__":
    main()
