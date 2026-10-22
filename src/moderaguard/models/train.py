"""Train a task model, evaluate it and log everything to MLflow (owner: M3).

Examples:
  python -m moderaguard.models.train --task toxicity --variant champion
  python -m moderaguard.models.train --task toxicity --variant challenger
  python -m moderaguard.models.train --task toxicity --variant champion --no-mitigation
  python -m moderaguard.models.train --task spam
  python -m moderaguard.models.train --task langid
  # retraining (Airflow): champion settings on the new data, saved as "candidate"
  python -m moderaguard.models.train --task toxicity --variant champion --name candidate

Outputs:
  models/<task>/<name>/model.joblib   the model object used by serving (<name> defaults to the variant)
  models/<task>/<name>/run.json       MLflow run id + model URI, used by register.py
  reports/metrics_<task>_<name>.json  test-set metrics
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import UTC, datetime

import joblib
import pandas as pd

from moderaguard.config import MODELS_DIR, PROCESSED_DIR, RAW_DIR, REPORTS_DIR, ensure_dirs, params
from moderaguard.models import tracking
from moderaguard.models.core import LangId, TextScorer, build_pipeline
from moderaguard.models.evaluate import classification_metrics
from moderaguard.responsible.fairness import counterfactual_augment, mitigation_weights

EXAMPLES = ["Thanks for the helpful article", "You are an idiot"]


def _text_and_label(task: str) -> tuple[str, str]:
    return ("comment_text", "toxic") if task == "toxicity" else ("text", "spam")


def train_scorer(task: str, variant: str, mitigation: bool) -> tuple[TextScorer, dict, tuple]:
    p = params()
    text_col, label_col = _text_and_label(task)
    train = pd.read_parquet(PROCESSED_DIR / f"{task}_train.parquet")
    test = pd.read_parquet(PROCESSED_DIR / f"{task}_test.parquet")
    model_cfg = p["toxicity"][variant] if task == "toxicity" else p["spam"]

    sample_weight, mask = None, False
    if task == "toxicity" and mitigation:
        mcfg = p["toxicity"]["mitigation"]
        mask = bool(mcfg.get("mask_identity_terms", False))
        train = counterfactual_augment(train, mcfg.get("counterfactual_copies", 0), seed=p["data"]["seed"])
        sample_weight = mitigation_weights(train, p)

    pipeline = build_pipeline(model_cfg, p["features"], seed=p["data"]["seed"], mask_identity=mask)
    fit_kwargs = {"clf__sample_weight": sample_weight} if sample_weight is not None else {}
    pipeline.fit(train[text_col].tolist(), train[label_col].to_numpy(), **fit_kwargs)

    version = f"{variant}-{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}"
    scorer = TextScorer(task=task, pipeline=pipeline, version=version,
                        metadata={"algorithm": model_cfg["algorithm"], "mitigation": mitigation})
    test_scores = scorer.score(test[text_col].tolist())
    metrics = classification_metrics(test[label_col], test_scores)
    scorer.metadata.update(train_rows=len(train), test_rows=len(test))
    return scorer, metrics, (test[label_col].to_numpy(), test_scores)


def _log_evaluation(mlflow, model: TextScorer, y_test, test_scores, task: str, out_dir) -> None:
    """Charts that make the run readable in the MLflow UI. Never fails the training run."""
    try:
        from moderaguard.models import report

        label = "toxic" if task == "toxicity" else "spam"
        figs = report.evaluation_figures(y_test, test_scores, out_dir / "evaluation", label)
        top = report.top_ngrams(model.pipeline)
        if top:
            figs.append(report.ngram_figure(top, out_dir / "evaluation", label))
            mlflow.log_dict(top, "evaluation/top_ngrams.json")
        for f in figs:
            mlflow.log_artifact(str(f), artifact_path="evaluation")
    except Exception as e:  # noqa: BLE001 - charts are a bonus, not a reason to lose the model
        print(f"[train] could not create evaluation charts: {e}")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--task", choices=["toxicity", "spam", "langid"], required=True)
    parser.add_argument("--variant", choices=["champion", "challenger"], default="champion")
    parser.add_argument("--no-mitigation", action="store_true", help="train toxicity without bias mitigation")
    parser.add_argument("--name", help="output folder/report name (default: the variant)")
    args = parser.parse_args(argv)
    ensure_dirs()

    mitigation = args.task == "toxicity" and not args.no_mitigation
    suffix = "_unmitigated" if args.task == "toxicity" and not mitigation else ""
    name = args.name or f"{args.variant}{suffix}"
    out_dir = MODELS_DIR / args.task / name
    out_dir.mkdir(parents=True, exist_ok=True)

    if args.task == "langid":
        model = LangId(model_path=os.environ.get("LANGID_MODEL_PATH", str(RAW_DIR / "lid.176.ftz")))
        model.version = f"{args.variant}-{model.backend}"
        metrics = {"backend": model.backend}
    else:
        model, metrics, (y_test, test_scores) = train_scorer(args.task, args.variant, mitigation)

    model_file = out_dir / "model.joblib"
    joblib.dump(model, model_file)
    (REPORTS_DIR / f"metrics_{args.task}_{name}.json").write_text(json.dumps(metrics, indent=2))

    run_info = {"version": model.version, "run_id": None, "model_uri": None}
    with tracking.run(f"moderaguard-{args.task}", run_name=model.version,
                      tags={"task": args.task, "variant": args.variant, "name": name}) as active:
        if active is not None:
            import mlflow

            mlflow.log_params({"task": args.task, "variant": args.variant, "mitigation": mitigation})
            if args.task != "langid":
                cfg = params()["toxicity"][args.variant] if args.task == "toxicity" else params()["spam"]
                mlflow.log_params({f"model.{k}": v for k, v in cfg.items()})
                mlflow.log_params({f"features.{k}": v for k, v in params()["features"].items()})
                if mitigation:
                    mlflow.log_params({f"mitigation.{k}": v for k, v in params()["toxicity"]["mitigation"].items()})
                mlflow.log_params({"data.train_rows": model.metadata["train_rows"],
                                   "data.test_rows": model.metadata["test_rows"]})
                mlflow.log_metrics({k: v for k, v in metrics.items() if isinstance(v, int | float)})
                _log_evaluation(mlflow, model, y_test, test_scores, args.task, out_dir)
            data_summary = REPORTS_DIR / "data_summary.json"
            if data_summary.exists():
                mlflow.log_artifact(str(data_summary), artifact_path="data")
            run_info["run_id"] = active.info.run_id
            run_info["model_uri"] = tracking.log_pyfunc_model(model_file, EXAMPLES)

    (out_dir / "run.json").write_text(json.dumps(run_info, indent=2))
    print(json.dumps({"task": args.task, "variant": args.variant, **metrics, **run_info}, indent=2))


if __name__ == "__main__":
    main()
