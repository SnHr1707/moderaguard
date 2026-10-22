from moderaguard.models.core import LangId


def test_fallback_detects_common_languages():
    lid = LangId(model_path=None)
    assert lid.backend == "stopwords"
    langs = [lang for lang, _ in lid.detect([
        "This is a comment about the article and it is good",
        "Muy buen articulo, gracias por compartir",
        "Je ne suis pas d'accord avec cet article",
        "Yeh article bahut accha hai",
    ])]
    assert langs == ["en", "es", "fr", "hi"]


def test_empty_text_is_undetermined():
    assert LangId().detect([""]) == [("und", 0.0)]
