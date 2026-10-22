from moderaguard.features.text import build_features, clean_text


def test_clean_text_normalises():
    assert clean_text("SOOOOOO   good!!!! http://x.co @bob 2024") == "sooo good!!! urltoken usertoken 0"


def test_features_fit_and_transform():
    cfg = {"word_max_features": 100, "word_ngram_max": 2, "char_max_features": 100,
           "char_ngram_min": 3, "char_ngram_max": 4, "min_df": 1}
    feats = build_features(cfg)
    X = feats.fit_transform(["you are great", "you are awful", "great work"])
    assert X.shape[0] == 3 and X.shape[1] > 0
