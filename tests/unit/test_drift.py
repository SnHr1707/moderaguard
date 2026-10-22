"""Drift job: newer comments (after the drift date) must be detected as drift; a
second sample of the training-era comments must not."""

import joblib
import pandas as pd
import pytest

import drift
from moderaguard.config import MODELS_DIR, PROCESSED_DIR


@pytest.fixture(scope="module")
def frames(trained_models):
    tox = joblib.load(MODELS_DIR / "toxicity" / "champion" / "model.joblib")
    spam = joblib.load(MODELS_DIR / "spam" / "champion" / "model.joblib")
    train = pd.read_parquet(PROCESSED_DIR / "toxicity_train.parquet")
    vocab = {w for t in train["comment_text"].str.lower() for w in drift._WORD.findall(t)}

    def featurise(texts: pd.Series) -> pd.DataFrame:
        texts = texts.reset_index(drop=True)
        return pd.concat([drift.text_features(texts, vocab),
                          pd.DataFrame({"toxicity": tox.score(texts.tolist()), "spam": spam.score(texts.tolist())})],
                         axis=1)

    test = pd.read_parquet(PROCESSED_DIR / "toxicity_test.parquet")["comment_text"]
    stream = pd.read_parquet(PROCESSED_DIR / "toxicity_stream.parquet")["comment_text"]
    half = len(test) // 2
    return featurise(test.iloc[:half]), featurise(test.iloc[half:]), featurise(stream)


def test_new_slang_is_detected_as_drift(frames):
    reference, _, stream = frames
    result = drift.compute_drift(reference, stream)
    assert result["drift_share"] >= 0.4
    assert result["p_values"]["oov_rate"] < 0.05


def test_same_distribution_is_not_drift(frames):
    reference, same, _ = frames
    assert drift.compute_drift(reference, same)["drift_share"] < 0.4
