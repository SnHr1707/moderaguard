"""Fairness audit and bias mitigation for the toxicity model (owner: M4).

Metrics follow the Jigsaw Unintended Bias competition:

* Subgroup AUC  - AUC on comments that mention the group. Low = the model
  cannot separate toxic from non-toxic comments about this group.
* BPSN AUC      - Background Positive, Subgroup Negative. Low = non-toxic
  comments about the group score higher than toxic comments elsewhere,
  i.e. false positives on the group.
* BNSP AUC      - Background Negative, Subgroup Positive. Low = toxic comments
  about the group are missed.

Plus, through Fairlearn, the false-positive rate per group at the serving
threshold, since a false positive here means a harmless comment hidden.

Run:  python -m moderaguard.responsible.fairness --variant champion
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from fairlearn.metrics import MetricFrame, false_positive_rate
from sklearn.metrics import roc_auc_score

from moderaguard.config import MODELS_DIR, PROCESSED_DIR, REPORTS_DIR, ensure_dirs, params
from moderaguard.identity import IDENTITY_TERMS

_TERM_PATTERNS = [
    (group, term, re.compile(rf"\b{re.escape(term)}\b", re.IGNORECASE))
    for group, terms in IDENTITY_TERMS.items()
    for term in sorted(terms, key=len, reverse=True)
]


def counterfactual_augment(train: pd.DataFrame, copies: int, seed: int = 0) -> pd.DataFrame:
    """Counterfactual data augmentation (Dixon et al., 2018; Garg et al., 2019).

    For each comment that names an identity group, add `copies` versions where
    that group's term is replaced with a term for a different group. Labels
    are kept, so the model learns that the group named does not change toxicity.
    """
    if copies <= 0:
        return train
    rng = np.random.default_rng(seed)
    groups = list(IDENTITY_TERMS)
    new_rows = []
    for row in train.itertuples(index=False):
        text = row.comment_text
        match = next(((g, pat) for g, _, pat in _TERM_PATTERNS if pat.search(text)), None)
        if match is None:
            continue
        group, pattern = match
        others = [g for g in groups if g != group]
        for target in rng.choice(others, size=min(copies, len(others)), replace=False):
            replacement = IDENTITY_TERMS[target][0]
            swapped = row._asdict()
            swapped["comment_text"] = pattern.sub(replacement, text, count=1)
            # identity columns follow the swap so fairness metrics stay correct
            for col in groups:
                if col in swapped:
                    swapped[col] = 1.0 if col == target else 0.0
            new_rows.append(swapped)
    if not new_rows:
        return train
    return pd.concat([train, pd.DataFrame(new_rows)], ignore_index=True)


def mitigation_weights(train: pd.DataFrame, p: dict) -> np.ndarray:
    """Up-weight non-toxic comments that mention an identity group."""
    cols = [c for c in p["fairness"]["identity_columns"] if c in train.columns]
    mentions = (train[cols].fillna(0) >= p["fairness"]["identity_threshold"]).any(axis=1)
    weight = p["toxicity"]["mitigation"]["neutral_identity_weight"]
    weights = np.ones(len(train))
    weights[(mentions & (train["toxic"] == 0)).to_numpy()] = weight
    return weights


def _auc(y: pd.Series, s: pd.Series) -> float | None:
    if y.nunique() < 2:
        return None
    return round(float(roc_auc_score(y, s)), 4)


def bias_metrics(df: pd.DataFrame, identity_cols: list[str], threshold: float, min_size: int) -> pd.DataFrame:
    """df needs columns: toxic, score, and the identity columns."""
    rows = []
    for col in identity_cols:
        in_group = df[col].fillna(0) >= threshold
        if in_group.sum() < min_size:
            continue
        sub, bg = df[in_group], df[~in_group]
        bpsn = pd.concat([sub[sub.toxic == 0], bg[bg.toxic == 1]])
        bnsp = pd.concat([sub[sub.toxic == 1], bg[bg.toxic == 0]])
        rows.append(
            {
                "group": col,
                "size": int(in_group.sum()),
                "subgroup_auc": _auc(sub.toxic, sub.score),
                "bpsn_auc": _auc(bpsn.toxic, bpsn.score),
                "bnsp_auc": _auc(bnsp.toxic, bnsp.score),
            }
        )
    return pd.DataFrame(rows)


def final_bias_score(overall_auc: float, table: pd.DataFrame, p: float = -5.0, w: float = 0.25) -> float:
    """Jigsaw's final metric: weighted overall AUC + power means of the bias AUCs."""
    def power_mean(values: pd.Series) -> float:
        v = values.dropna().to_numpy()
        return float(np.power(np.mean(np.power(v, p)), 1 / p)) if len(v) else overall_auc

    score = w * overall_auc + sum(w * power_mean(table[c]) for c in ("subgroup_auc", "bpsn_auc", "bnsp_auc"))
    return round(score, 4)


def audit(scores: pd.Series, test: pd.DataFrame, p: dict, serving_threshold: float = 0.5) -> dict:
    cfg = p["fairness"]
    cols = [c for c in cfg["identity_columns"] if c in test.columns]
    df = test.assign(score=scores.to_numpy())
    overall_auc = round(float(roc_auc_score(df.toxic, df.score)), 4)
    table = bias_metrics(df, cols, cfg["identity_threshold"], cfg["min_group_size"])

    # Fairlearn: false-positive rate per group at the threshold the service uses
    groups = df[cols].fillna(0).ge(cfg["identity_threshold"])
    group_label = groups.apply(lambda r: next((c for c in cols if r[c]), "no_identity"), axis=1)
    frame = MetricFrame(
        metrics=false_positive_rate,
        y_true=df.toxic,
        y_pred=(df.score >= serving_threshold).astype(int),
        sensitive_features=group_label,
    )
    fpr = {k: round(float(v), 4) for k, v in frame.by_group.items() if not np.isnan(v)}
    base_fpr = fpr.get("no_identity", float(frame.overall))
    worst_gap = max((v - base_fpr for k, v in fpr.items() if k != "no_identity"), default=0.0)

    return {
        "overall_auc": overall_auc,
        "final_bias_score": final_bias_score(overall_auc, table) if len(table) else overall_auc,
        "worst_fpr_gap": round(float(worst_gap), 4),
        "fpr_by_group": fpr,
        "groups": table.to_dict(orient="records"),
    }


def fpr_figure(result: dict, path: Path, title: str) -> Path:
    """Bar chart of the false-positive rate per identity group."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fpr = result["fpr_by_group"]
    groups = sorted((g for g in fpr if g != "no_identity"), key=lambda g: fpr[g])
    fig, ax = plt.subplots(figsize=(6.5, 3.8))
    ax.barh([g.replace("_", " ") for g in groups], [fpr[g] for g in groups], color="#2563eb")
    base = fpr.get("no_identity", 0.0)
    ax.axvline(base, color="#1f2933", ls="--", lw=1, label=f"comments naming no group ({base:.2f})")
    ax.set_xlabel("false-positive rate (harmless comments flagged)")
    ax.set_title(title)
    ax.legend(frameon=False, fontsize=8)
    fig.tight_layout()
    fig.savefig(path, dpi=120)
    plt.close(fig)
    return path


def _log_to_mlflow(variant: str, result: dict) -> None:
    """Attach the audit to the MLflow run that trained this model, if there is one."""
    from moderaguard.models import tracking

    run_file = MODELS_DIR / "toxicity" / variant / "run.json"
    if not tracking.mlflow_enabled() or not run_file.exists():
        return
    run_id = json.loads(run_file.read_text()).get("run_id")
    if not run_id:
        return
    try:
        import mlflow

        with mlflow.start_run(run_id=run_id):
            mlflow.log_metrics({"fairness.final_bias_score": result["final_bias_score"],
                                "fairness.worst_fpr_gap": result["worst_fpr_gap"]})
            mlflow.log_dict(result, "fairness/fairness.json")
            fig = fpr_figure(result, MODELS_DIR / "toxicity" / variant / "fpr_by_group.png",
                             f"False positives by identity group ({variant})")
            mlflow.log_artifact(str(fig), artifact_path="fairness")
    except Exception as e:  # noqa: BLE001
        print(f"[fairness] could not log to MLflow run {run_id}: {e}")


def to_markdown(results: dict[str, dict]) -> str:
    lines = ["# Fairness report (toxicity model)", "",
             "Generated by `python -m moderaguard.responsible.fairness`. Re-run after every retrain.", ""]
    lines += ["| Model | Overall AUC | Final bias score | Worst FPR gap vs no-identity comments |",
              "| --- | --- | --- | --- |"]
    for name, r in results.items():
        lines.append(f"| {name} | {r['overall_auc']} | {r['final_bias_score']} | {r['worst_fpr_gap']} |")
    for name, r in results.items():
        lines += ["", f"## {name}", "", "| Group | Size | Subgroup AUC | BPSN AUC | BNSP AUC | FPR |",
                  "| --- | --- | --- | --- | --- | --- |"]
        for g in r["groups"]:
            lines.append(f"| {g['group']} | {g['size']} | {g['subgroup_auc']} | {g['bpsn_auc']} | "
                         f"{g['bnsp_auc']} | {r['fpr_by_group'].get(g['group'], '')} |")
        lines.append(f"| no identity mentioned | | | | | {r['fpr_by_group'].get('no_identity', '')} |")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--variant", nargs="+", default=["champion"],
                        help="model folders under models/toxicity/ to audit, e.g. champion champion_unmitigated")
    parser.add_argument("--markdown", type=Path, default=REPORTS_DIR / "fairness_report.md")
    args = parser.parse_args(argv)
    ensure_dirs()
    p = params()
    test = pd.read_parquet(PROCESSED_DIR / "toxicity_test.parquet")

    results = {}
    for variant in args.variant:
        path = MODELS_DIR / "toxicity" / variant / "model.joblib"
        if not path.exists():
            print(f"[fairness] skipping {variant}: {path} not found")
            continue
        model = joblib.load(path)
        scores = pd.Series(model.score(test["comment_text"].tolist()))
        results[variant] = audit(scores, test, p)
        (REPORTS_DIR / f"fairness_{variant}.json").write_text(json.dumps(results[variant], indent=2))
        _log_to_mlflow(variant, results[variant])

    args.markdown.write_text(to_markdown(results))
    print(json.dumps({k: {m: v[m] for m in ("overall_auc", "final_bias_score", "worst_fpr_gap")}
                      for k, v in results.items()}, indent=2))


if __name__ == "__main__":
    main()
