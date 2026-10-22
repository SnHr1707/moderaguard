import pandas as pd
import pytest

from moderaguard.config import PROCESSED_DIR
from moderaguard.data.validate import spam_schema, toxicity_schema, validate_frame


def test_processed_data_passes(processed_data):
    for split in ("train", "test"):
        validate_frame(pd.read_parquet(PROCESSED_DIR / f"toxicity_{split}.parquet"), toxicity_schema(), split)
        validate_frame(pd.read_parquet(PROCESSED_DIR / f"spam_{split}.parquet"), spam_schema(), split)


def test_bad_labels_are_rejected(processed_data):
    df = pd.read_parquet(PROCESSED_DIR / "toxicity_train.parquet").head(200).copy()
    df.loc[df.index[:5], "toxic"] = 7
    with pytest.raises(ValueError, match="validation failures"):
        validate_frame(df, toxicity_schema(), "broken")


def test_empty_comments_are_rejected(processed_data):
    df = pd.read_parquet(PROCESSED_DIR / "spam_train.parquet").head(100).copy()
    df.loc[df.index[0], "text"] = ""
    with pytest.raises(ValueError):
        validate_frame(df, spam_schema(), "broken")
