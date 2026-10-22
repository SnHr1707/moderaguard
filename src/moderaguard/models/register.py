"""Register trained models in the MLflow Model Registry and manage aliases (owner: M3).

Each task has one registered model (moderaguard-toxicity, -spam, -langid).
Serving loads `models:/<name>@champion` or `@challenger`, so promoting a model
is just moving an alias; no service needs rebuilding.

Examples:
  # register the latest local training run and point an alias at it
  python -m moderaguard.models.register register --task toxicity --variant challenger --alias challenger
  # challenger passed the gate and the canary: make it the champion
  python -m moderaguard.models.register promote --task toxicity
  # roll back: point champion at a previous version
  python -m moderaguard.models.register set-alias --task toxicity --alias champion --version 3
  python -m moderaguard.models.register show --task toxicity
"""

from __future__ import annotations

import argparse
import json

from mlflow import MlflowClient
from mlflow.exceptions import MlflowException

from moderaguard.config import CHALLENGER_ALIAS, CHAMPION_ALIAS, MODELS_DIR, REGISTERED_MODEL_NAMES


def register(task: str, variant: str, alias: str) -> int:
    import mlflow

    run = json.loads((MODELS_DIR / task / variant / "run.json").read_text())
    if not run.get("model_uri"):
        raise SystemExit("this model was trained with MLflow disabled; retrain with MLflow on")
    name = REGISTERED_MODEL_NAMES[task]
    mv = mlflow.register_model(run["model_uri"], name, tags={"variant": variant, "local_version": run["version"]})
    MlflowClient().set_registered_model_alias(name, alias, mv.version)
    print(f"registered {name} version {mv.version} with alias @{alias}")
    return int(mv.version)


def promote(task: str) -> None:
    client, name = MlflowClient(), REGISTERED_MODEL_NAMES[task]
    challenger = client.get_model_version_by_alias(name, CHALLENGER_ALIAS)
    try:
        previous = client.get_model_version_by_alias(name, CHAMPION_ALIAS).version
        client.set_registered_model_alias(name, "previous-champion", previous)
    except MlflowException:
        previous = None
    client.set_registered_model_alias(name, CHAMPION_ALIAS, challenger.version)
    print(f"{name}: champion is now version {challenger.version} (was {previous})")


def show(task: str) -> None:
    client, name = MlflowClient(), REGISTERED_MODEL_NAMES[task]
    for found in client.search_model_versions(f"name='{name}'"):
        mv = client.get_model_version(name, found.version)  # search results do not include aliases
        print(f"version {mv.version}  aliases={mv.aliases}  run={mv.run_id}  tags={mv.tags}")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("register")
    r.add_argument("--task", required=True)
    r.add_argument("--variant", default="champion")
    r.add_argument("--alias", default=CHAMPION_ALIAS)
    p = sub.add_parser("promote")
    p.add_argument("--task", required=True)
    s = sub.add_parser("set-alias")
    s.add_argument("--task", required=True)
    s.add_argument("--alias", required=True)
    s.add_argument("--version", required=True)
    sh = sub.add_parser("show")
    sh.add_argument("--task", required=True)
    args = parser.parse_args(argv)

    if args.cmd == "register":
        register(args.task, args.variant, args.alias)
    elif args.cmd == "promote":
        promote(args.task)
    elif args.cmd == "set-alias":
        MlflowClient().set_registered_model_alias(REGISTERED_MODEL_NAMES[args.task], args.alias, args.version)
        print(f"{REGISTERED_MODEL_NAMES[args.task]}@{args.alias} -> version {args.version}")
    else:
        show(args.task)


if __name__ == "__main__":
    main()
