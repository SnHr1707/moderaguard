"""Hyperparameter tuning with Optuna; every trial is logged to MLflow (owner: M3).

Tunes the regularisation strength C and the n-gram ranges for a task with
3-fold cross-validated AUC on the training split. The best values are written
to reports/tuning_<task>.json; copy them into params.yaml to adopt them, so
the change shows up in Git history and `dvc repro` re-trains.

Run:  python -m moderaguard.models.tune --task toxicity --trials 20
"""

from __future__ import annotations

import argparse
import json

import optuna
import pandas as pd
from sklearn.model_selection import cross_val_score

from moderaguard.config import PROCESSED_DIR, REPORTS_DIR, ensure_dirs, params
from moderaguard.models import tracking
from moderaguard.models.core import build_pipeline


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--task", choices=["toxicity", "spam"], default="toxicity")
    parser.add_argument("--trials", type=int, default=None)
    args = parser.parse_args(argv)
    ensure_dirs()
    p = params()
    n_trials = args.trials or p["tuning"]["n_trials"]
    text_col, label_col = ("comment_text", "toxic") if args.task == "toxicity" else ("text", "spam")
    train = pd.read_parquet(PROCESSED_DIR / f"{args.task}_train.parquet")
    X, y = train[text_col].tolist(), train[label_col].to_numpy()
    base_model = p["toxicity"]["champion"] if args.task == "toxicity" else p["spam"]

    def objective(trial: optuna.Trial) -> float:
        model_cfg = {**base_model, "C": trial.suggest_float("C", 0.05, 20.0, log=True)}
        feat_cfg = {
            **p["features"],
            "word_ngram_max": trial.suggest_int("word_ngram_max", 1, 3),
            "char_ngram_max": trial.suggest_int("char_ngram_max", 4, 6),
        }
        mask = args.task == "toxicity" and p["toxicity"]["mitigation"].get("mask_identity_terms", False)
        pipe = build_pipeline(model_cfg, feat_cfg, mask_identity=mask)
        auc = cross_val_score(pipe, X, y, cv=3, scoring="roc_auc").mean()
        with tracking.run(f"moderaguard-{args.task}-tuning", run_name=f"trial-{trial.number}",
                          tags={"task": args.task}) as active:
            if active is not None:
                import mlflow

                mlflow.log_params(trial.params)
                mlflow.log_metric("cv_auc", auc)
        return auc

    study = optuna.create_study(direction="maximize", sampler=optuna.samplers.TPESampler(seed=p["data"]["seed"]))
    study.optimize(objective, n_trials=n_trials)
    result = {"task": args.task, "best_cv_auc": round(study.best_value, 4), "best_params": study.best_params,
              "n_trials": n_trials}
    (REPORTS_DIR / f"tuning_{args.task}.json").write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
