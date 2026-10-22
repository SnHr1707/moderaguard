"""Model objects shared by training and serving (owner: M3).

Every task model exposes one small interface, so the model service does not
care which algorithm is inside:

* TextScorer.score(texts)  -> list of probabilities (toxicity, spam)
* LangId.detect(texts)     -> list of (language_code, confidence)
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from sklearn.calibration import CalibratedClassifierCV
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.svm import LinearSVC

from moderaguard.features.text import build_features


def build_pipeline(model_cfg: dict, feature_cfg: dict, seed: int = 42, mask_identity: bool = False) -> Pipeline:
    algo = model_cfg["algorithm"]
    class_weight = model_cfg.get("class_weight")
    if algo == "logreg":
        clf = LogisticRegression(C=model_cfg["C"], class_weight=class_weight, max_iter=2000, random_state=seed)
    elif algo == "linear_svm":
        # LinearSVC has no probabilities; calibration turns its margins into scores in [0, 1]
        clf = CalibratedClassifierCV(
            LinearSVC(C=model_cfg["C"], class_weight=class_weight, random_state=seed), cv=3
        )
    else:
        raise ValueError(f"unknown algorithm: {algo}")
    return Pipeline([("features", build_features(feature_cfg, mask_identity=mask_identity)), ("clf", clf)])


@dataclass
class TextScorer:
    """Binary text classifier wrapper: returns P(positive class)."""

    task: str
    pipeline: Pipeline
    version: str = "local"
    metadata: dict = field(default_factory=dict)

    def score(self, texts: Sequence[str]) -> list[float]:
        if len(texts) == 0:
            return []
        proba = self.pipeline.predict_proba(list(texts))[:, 1]
        return [round(float(p), 6) for p in proba]


# ---------------------------------------------------------------------------
# Language identification
# ---------------------------------------------------------------------------

# Very common words per language, used when the fastText model is not available.
_STOPWORDS = {
    "en": {"the", "and", "is", "to", "of", "you", "this", "that", "it", "in", "a", "for", "are", "i", "be"},
    "es": {"el", "la", "de", "que", "y", "en", "los", "por", "muy", "gracias", "es", "una", "con", "para"},
    "fr": {"le", "la", "les", "de", "et", "est", "je", "ne", "pas", "suis", "avec", "cet", "une", "pour"},
    "de": {"der", "die", "das", "und", "ist", "ein", "nicht", "sehr", "ich", "mit", "beitrag", "zu"},
    "hi": {"hai", "bahut", "accha", "yeh", "kya", "nahi", "aur", "ke", "ki", "dhanyavaad", "mein", "ho"},
}
_TOKEN = re.compile(r"[a-zA-ZÀ-ſ']+")


@dataclass
class LangId:
    """Language identification.

    Uses the pretrained fastText model (lid.176.ftz) when `model_path` exists,
    which covers 176 languages. Otherwise it falls back to a stop-word
    heuristic that is good enough for the demo and the tests.
    """

    model_path: str | None = None
    version: str = "local"
    _ft: object | None = field(default=None, init=False, repr=False)
    _ft_bytes: bytes | None = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        if self.model_path and Path(self.model_path).exists():
            # keep the file's bytes so the model travels inside the pickle / MLflow artifact
            self._ft_bytes = Path(self.model_path).read_bytes()
            self._load_fasttext()

    def _load_fasttext(self) -> None:
        if self._ft_bytes is None:
            return
        try:
            import tempfile

            import fasttext  # type: ignore
        except ImportError:  # fasttext not installed here: use the fallback
            self._ft = None
            return
        with tempfile.NamedTemporaryFile(suffix=".ftz") as tmp:
            tmp.write(self._ft_bytes)
            tmp.flush()
            self._ft = fasttext.load_model(tmp.name)

    # The loaded fastText object cannot be pickled; store the file bytes instead.
    def __getstate__(self) -> dict:
        state = self.__dict__.copy()
        state["_ft"] = None
        return state

    def __setstate__(self, state: dict) -> None:
        self.__dict__.update(state)
        self._load_fasttext()

    @property
    def backend(self) -> str:
        return "fasttext" if self._ft is not None else "stopwords"

    def detect(self, texts: Sequence[str]) -> list[tuple[str, float]]:
        return [self._detect_one(t) for t in texts]

    def _detect_one(self, text: str) -> tuple[str, float]:
        text = str(text).replace("\n", " ").strip()
        if not text:
            return ("und", 0.0)
        if self._ft is not None:
            # the low-level predictor: FastText.predict() is broken under NumPy 2
            prob, label = self._ft.f.predict(text, 1, 0.0, "strict")[0]
            return (label.replace("__label__", ""), round(float(prob), 4))
        tokens = [t.lower() for t in _TOKEN.findall(text)]
        if not tokens:
            return ("und", 0.0)
        counts = {lang: sum(t in words for t in tokens) for lang, words in _STOPWORDS.items()}
        best = max(counts, key=counts.get)
        hits = counts[best]
        if hits == 0:
            # no stop words at all: short English-looking text is the common case
            return ("en", 0.5)
        total = sum(counts.values())
        return (best, round(float(np.clip(hits / total, 0.0, 1.0)), 4))
