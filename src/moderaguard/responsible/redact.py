"""Privacy: mask personal data before any comment text is logged or stored (owner: M4).

Used by the gateway (request logs), the consumer (prediction log) and
anything else that writes comment text to disk. Models still see the
original text; only what is persisted is redacted.
"""

from __future__ import annotations

import re

_PATTERNS = [
    ("[EMAIL]", re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")),
    ("[URL]", re.compile(r"https?://\S+|www\.\S+")),
    # phone numbers: +91 98765 43210, (555) 123-4567, 9876543210 ...
    ("[PHONE]", re.compile(r"(?<!\w)(?:\+?\d{1,3}[\s-]?)?(?:\(?\d{2,5}\)?[\s-]?)?\d{3,5}[\s-]?\d{4,5}(?!\w)")),
    ("[HANDLE]", re.compile(r"(?<![\w.])@\w{2,}")),
]


def redact(text: str) -> str:
    out = str(text)
    for token, pattern in _PATTERNS:
        out = pattern.sub(token, out)
    return out
