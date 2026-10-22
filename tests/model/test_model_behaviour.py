"""Behavioural tests: check what the model does, not just its AUC.

* minimum functionality: obvious cases are scored correctly
* directional: adding an insult must raise the toxicity score
* invariance: swapping one identity term for another must not swing the score much
"""

import json

import joblib

from moderaguard.config import MODELS_DIR, REPORTS_DIR


def _tox():
    return joblib.load(MODELS_DIR / "toxicity" / "champion" / "model.joblib")


def test_metrics_meet_minimum(trained_models):
    metrics = json.loads((REPORTS_DIR / "metrics_toxicity_champion.json").read_text())
    assert metrics["auc"] >= 0.8


def test_obvious_cases(trained_models):
    clean, insult = _tox().score(["Thanks for sharing, this was a helpful read",
                                  "You are a complete idiot and should shut up"])
    assert clean < 0.5 < insult


def test_adding_an_insult_raises_score(trained_models):
    base, worse = _tox().score(["I disagree with the author", "I disagree with the author, what a moron"])
    assert worse > base


def test_identity_swap_is_roughly_invariant(trained_models):
    scores = _tox().score([f"Good to see {who} represented in the discussion"
                           for who in ("christians", "muslims", "gay people", "white people", "black people")])
    # identity terms are masked in the toxicity model, so swapping the group cannot change the score
    assert max(scores) - min(scores) < 0.01


def test_spam_model(trained_models):
    spam = joblib.load(MODELS_DIR / "spam" / "champion" / "model.joblib")
    ham, junk = spam.score(["The guitar solo is amazing", "Subscribe to my channel http://bit.ly/123 free gift"])
    assert ham < 0.5 < junk
