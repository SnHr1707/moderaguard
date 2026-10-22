"""Re-evaluate the model that is currently deployed on the current test set (owner: M3).

Used before the quality gate during retraining: the new test set contains the
newer comments, so the champion must be scored on the same data as the
candidate, otherwise the comparison is unfair.

Run:  python -m moderaguard.models.rescore --task toxicity --alias champion --source mlflow
Writes models/<task>/<alias>/model.joblib and reports/metrics_<task>_<alias>.json.
"""

from __future__ import annotations

import argparse
import json

import joblib
import pandas as pd

from moderaguard.config import MODELS_DIR, PROCESSED_DIR, REPORTS_DIR, ensure_dirs
from moderaguard.models.evaluate import classification_metrics
from moderaguard.serving.loader import load_model


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--task", choices=["toxicity", "spam"], default="toxicity")
    parser.add_argument("--alias", default="champion")
    parser.add_argument("--source", choices=["mlflow", "local"], default="mlflow")
    args = parser.parse_args(argv)
    ensure_dirs()

    model = load_model(args.task, source=args.source, alias=args.alias)
    text_col, label_col = ("comment_text", "toxic") if args.task == "toxicity" else ("text", "spam")
    test = pd.read_parquet(PROCESSED_DIR / f"{args.task}_test.parquet")
    metrics = classification_metrics(test[label_col], model.score(test[text_col].tolist()))

    out = MODELS_DIR / args.task / args.alias
    out.mkdir(parents=True, exist_ok=True)
    joblib.dump(model, out / "model.joblib")
    (REPORTS_DIR / f"metrics_{args.task}_{args.alias}.json").write_text(json.dumps(metrics, indent=2))
    print(json.dumps({"task": args.task, "alias": args.alias, **metrics}, indent=2))


if __name__ == "__main__":
    main()
