"""Deterministic text normalization for the Verification Engine (Skill.md
§16, §36).

P0-1 fix: the residual check used to compare the EXACT string
`Detection.text` captured at detection time against a fresh OCR read of the
(possibly still-unmasked) region. Because Tesseract can tokenize the same
digits differently depending on context — confirmed against real OCR output:
"4111 1111 1111 1111" misread as "41111111 11111111" on the full page, then
correctly re-split into "4111"/"1111"/"1111"/"1111" tokens on an isolated
crop — that exact-string comparison could report "no residual" (a **false
PASS**) even though the raw value was never redacted at all.

`normalize_for_detection()` and `normalize_for_verification()` both reduce a
string to the same canonical form, so a tokenization/spacing difference
between the two OCR passes can no longer hide a real residual match. They
are exposed as two named entry points (matching the two call sites — the
value captured once at detection time, and the value re-read on every
verification attempt) even though they currently share one implementation:
the correctness property this fixes depends on both sides *always* landing
on the same canonical text, so keeping one shared core is deliberate, not
incidental duplication.
"""
from __future__ import annotations

import re

# Sensitive types whose *rendered* value legitimately contains separator
# characters (spaces, dashes, dots, slashes) that carry no information —
# e.g. a credit card is grouped in 4s, a phone number may have dashes. For
# these we strip whitespace AND those separators before comparing.
_NUMERIC_SEPARATOR_TYPES = {"CreditCard", "BankAccount", "Phone", "PhoneTW"}

_WHITESPACE_RE = re.compile(r"\s+")
_NUMERIC_SEPARATOR_RE = re.compile(r"[\s\-./]+")


def _normalize_core(text: str, data_type: str | None) -> str:
    if data_type in _NUMERIC_SEPARATOR_TYPES:
        # Numeric data: whitespace and common numeric separators carry no
        # information — "4111 1111 1111 1111" and "4111-1111-1111-1111" and
        # "41111111 11111111" must all normalize identically.
        return _NUMERIC_SEPARATOR_RE.sub("", text)
    # Alphanumeric / secret data (JWT, API keys, Taiwan ID, ...): only strip
    # OCR-introduced whitespace. Punctuation like "." in a JWT or "_"/"="
    # in an API key is part of the value's actual grammar and must be kept,
    # since stripping it could make two DIFFERENT secrets normalize equal.
    return _WHITESPACE_RE.sub("", text)


def normalize_for_detection(text: str, data_type: str | None = None) -> str:
    """Canonicalize a value as captured at detection time (`Detection.text`)."""
    return _normalize_core(text, data_type)


def normalize_for_verification(text: str, data_type: str | None = None) -> str:
    """Canonicalize a value re-recognized during a verification re-OCR pass.

    Deliberately calls the same core normalizer as `normalize_for_detection`
    — see module docstring for why sharing this core is the point, not an
    accident.
    """
    return _normalize_core(text, data_type)
