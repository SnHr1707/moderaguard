from moderaguard.responsible.redact import redact


def test_email_is_masked():
    assert redact("mail me at priya.s@example.com now") == "mail me at [EMAIL] now"


def test_phone_numbers_are_masked():
    assert "[PHONE]" in redact("call +91 98765 43210 today")
    assert "[PHONE]" in redact("my number is 9876543210")


def test_handles_and_urls_are_masked():
    out = redact("ask @rahul_k or see https://example.com/post?id=3")
    assert "@rahul_k" not in out and "https://" not in out
    assert "[HANDLE]" in out and "[URL]" in out


def test_ordinary_text_is_unchanged():
    text = "The council meets on 12 March at 5 pm"
    assert redact(text) == text
