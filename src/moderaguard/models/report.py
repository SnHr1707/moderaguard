"""Evaluation charts saved next to each MLflow run (owner: M3).

These make a run in the MLflow UI self-explanatory: how good the model is
(ROC, precision-recall, confusion matrix), how confident it is (score
distribution), and what it learned (the n-grams that push a comment towards
toxic or towards clean).
"""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # no display in containers
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from sklearn.metrics import (  # noqa: E402
    auc,
    average_precision_score,
    confusion_matrix,
    precision_recall_curve,
    roc_curve,
)

INK, ACCENT, MUTED = "#1f2933", "#2563eb", "#9aa5b1"


def _save(fig, path: Path) -> Path:
    fig.tight_layout()
    fig.savefig(path, dpi=120)
    plt.close(fig)
    return path


def evaluation_figures(y_true, scores, out_dir: Path, label: str, threshold: float = 0.5) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    y_true, scores = np.asarray(y_true), np.asarray(scores)
    y_pred = (scores >= threshold).astype(int)
    paths = []

    # Curves drawn directly from the numbers (no sklearn Display classes, whose
    # arguments change between versions).
    fpr, tpr, _ = roc_curve(y_true, scores)
    fig, ax = plt.subplots(figsize=(4.5, 4))
    ax.plot(fpr, tpr, color=ACCENT, lw=2, label=f"{label} (AUC = {auc(fpr, tpr):.3f})")
    ax.plot([0, 1], [0, 1], ls="--", color=MUTED, lw=1, label="random guess")
    ax.set(xlabel="false-positive rate", ylabel="true-positive rate", title="ROC curve")
    ax.legend(frameon=False, loc="lower right")
    paths.append(_save(fig, out_dir / "roc_curve.png"))

    prec, rec, _ = precision_recall_curve(y_true, scores)
    fig, ax = plt.subplots(figsize=(4.5, 4))
    ax.plot(rec, prec, color=ACCENT, lw=2, label=f"AP = {average_precision_score(y_true, scores):.3f}")
    ax.set(xlabel="recall", ylabel="precision", title="Precision-recall curve", ylim=(0, 1.02))
    ax.legend(frameon=False, loc="lower left")
    paths.append(_save(fig, out_dir / "precision_recall.png"))

    cm = confusion_matrix(y_true, y_pred, labels=[0, 1])
    fig, ax = plt.subplots(figsize=(4.2, 4))
    ax.imshow(cm, cmap="Blues")
    names = ["clean", label]
    ax.set(xticks=[0, 1], yticks=[0, 1], xticklabels=names, yticklabels=names,
           xlabel="predicted", ylabel="actual", title=f"Confusion matrix (threshold {threshold})")
    for i in range(2):
        for j in range(2):
            ax.text(j, i, str(cm[i, j]), ha="center", va="center", fontsize=13,
                    color="white" if cm[i, j] > cm.max() / 2 else INK)
    paths.append(_save(fig, out_dir / "confusion_matrix.png"))

    fig, ax = plt.subplots(figsize=(6, 3.6))
    bins = np.linspace(0, 1, 26)
    ax.hist(scores[y_true == 0], bins=bins, alpha=0.75, color=MUTED, label=f"truly clean (n={int((y_true == 0).sum())})")
    ax.hist(scores[y_true == 1], bins=bins, alpha=0.75, color=ACCENT, label=f"truly {label} (n={int((y_true == 1).sum())})")
    ax.axvline(threshold, color=INK, ls="--", lw=1)
    ax.set_xlabel(f"predicted probability of {label}")
    ax.set_ylabel("comments")
    ax.set_title("Score distribution on the test set")
    ax.legend(frameon=False)
    paths.append(_save(fig, out_dir / "score_distribution.png"))
    return paths


def top_ngrams(pipeline, k: int = 15) -> dict[str, list[tuple[str, float]]] | None:
    """The n-grams with the largest positive / negative weights (linear models only)."""
    clf = pipeline.named_steps["clf"]
    coef = getattr(clf, "coef_", None)
    if coef is None:  # e.g. the calibrated SVM: average the inner models' weights
        inner = getattr(clf, "calibrated_classifiers_", None)
        if not inner:
            return None
        coef = np.mean([c.estimator.coef_ for c in inner], axis=0)
    coef = np.asarray(coef).ravel()
    feats = pipeline.named_steps["features"]
    names = np.concatenate([
        [f"{n}" for n in feats.transformer_list[0][1].get_feature_names_out()],
        [f"'{n}'" for n in feats.transformer_list[1][1].get_feature_names_out()],  # char n-grams quoted
    ])
    order = np.argsort(coef)
    return {
        "towards_positive": [(str(names[i]), round(float(coef[i]), 3)) for i in order[::-1][:k]],
        "towards_negative": [(str(names[i]), round(float(coef[i]), 3)) for i in order[:k]],
    }


def ngram_figure(top: dict, out_dir: Path, label: str) -> Path:
    pos, neg = top["towards_positive"][:12], top["towards_negative"][:12]
    fig, axes = plt.subplots(1, 2, figsize=(9, 4.2))
    for ax, items, colour, title in ((axes[0], pos, ACCENT, f"push towards {label}"),
                                     (axes[1], neg, MUTED, "push towards clean")):
        words = [w for w, _ in items][::-1]
        vals = [abs(v) for _, v in items][::-1]
        ax.barh(words, vals, color=colour)
        ax.set_title(title)
        ax.set_xlabel("weight in the model")
        ax.tick_params(axis="y", labelsize=8)
    fig.suptitle("What the model learned (largest weights; quoted = character n-grams)", fontsize=10)
    return _save(fig, out_dir / "top_ngrams.png")
