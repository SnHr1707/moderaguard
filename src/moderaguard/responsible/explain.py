"""Explain a single moderation decision (owner: M4).

Occlusion: remove each word in turn and measure how much the score drops.
Words whose removal lowers the score the most are the ones driving it. This
works for any model behind `score()`, so the challenger can be explained too.

The drop is measured in log-odds, not probability: near a score of 1.0 the
probability hardly moves when one word is removed (0.999 -> 0.998), while the
log-odds still show clearly which words matter.
"""

from __future__ import annotations

import math
import re

_WORD = re.compile(r"\S+")


def _logit(p: float) -> float:
    p = min(max(p, 1e-6), 1 - 1e-6)
    return math.log(p / (1 - p))


def explain(scorer, text: str, top_k: int = 5) -> dict:
    words = _WORD.findall(text)
    base = scorer.score([text])[0]
    if not words:
        return {"score": base, "contributions": []}
    # One batch call: the comment with each word removed
    variants = [" ".join(words[:i] + words[i + 1 :]) for i in range(len(words))]
    scores = scorer.score(variants)
    contributions = [
        {"word": w, "contribution": round(_logit(base) - _logit(s), 4)} for w, s in zip(words, scores, strict=True)
    ]
    contributions.sort(key=lambda c: c["contribution"], reverse=True)
    return {"score": base, "unit": "log-odds", "contributions": contributions[:top_k]}
