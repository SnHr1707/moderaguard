"""Text cleaning and TF-IDF features (owner: M1).

The same `build_features()` object is fitted inside each model pipeline, so
training and serving always transform text identically (no train/serve skew).
"""

from __future__ import annotations

import re

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.pipeline import FeatureUnion

_URL = re.compile(r"https?://\S+|www\.\S+")
_USER = re.compile(r"@\w+")
_NUM = re.compile(r"\d+")
_REPEAT = re.compile(r"(.)\1{3,}")
_SPACE = re.compile(r"\s+")


def clean_text(text: str) -> str:
    """Lower-case and normalise a comment while keeping signal useful for moderation.

    URLs become a `urltoken` (useful for spam), user handles become `usertoken`,
    long character repeats are squashed ("soooooo" -> "sooo").
    """
    text = str(text).lower()
    text = _URL.sub(" urltoken ", text)
    text = _USER.sub(" usertoken ", text)
    text = _NUM.sub(" 0 ", text)
    text = _REPEAT.sub(r"\1\1\1", text)
    return _SPACE.sub(" ", text).strip()


def build_features(cfg: dict) -> FeatureUnion:
    """Word n-grams + character n-grams. Char n-grams make the model robust to misspellings."""
    word = TfidfVectorizer(
        preprocessor=clean_text,
        analyzer="word",
        ngram_range=(1, cfg["word_ngram_max"]),
        max_features=cfg["word_max_features"],
        min_df=cfg["min_df"],
        sublinear_tf=True,
    )
    char = TfidfVectorizer(
        preprocessor=clean_text,
        analyzer="char_wb",
        ngram_range=(cfg["char_ngram_min"], cfg["char_ngram_max"]),
        max_features=cfg["char_max_features"],
        min_df=cfg["min_df"],
        sublinear_tf=True,
    )
    return FeatureUnion([("word", word), ("char", char)])
