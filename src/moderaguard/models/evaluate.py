"""Classification metrics used by training and the quality gate (owner: M3)."""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np
from sklearn.metrics import accuracy_score, f1_score, precision_score, recall_score, roc_auc_score


def classification_metrics(y_true: Sequence[int], scores: Sequence[float], threshold: float = 0.5) -> dict:
    y_true = np.asarray(y_true)
    scores = np.asarray(scores)
    y_pred = (scores >= threshold).astype(int)
    return {
        "auc": round(float(roc_auc_score(y_true, scores)), 4),
        "f1": round(float(f1_score(y_true, y_pred, zero_division=0)), 4),
        "precision": round(float(precision_score(y_true, y_pred, zero_division=0)), 4),
        "recall": round(float(recall_score(y_true, y_pred, zero_division=0)), 4),
        "accuracy": round(float(accuracy_score(y_true, y_pred)), 4),
        "positive_rate": round(float(y_pred.mean()), 4),
        "n": int(len(y_true)),
    }
