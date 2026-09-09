"""Candidate Value Detection for Passport / Bank Account (Phase 6.2).

Root cause (Phase 6.1 benchmark, re-confirmed against the exact 4 remaining
false-negative fixtures — see benchmarks/README.md): OCR correctly reads
the sensitive VALUE ("1234567890123", "PA1234567") but misreads exactly one
character of the adjacent Chinese LABEL ("銀"->"銨", "號"->"虢", "照"->"烈").
`ContextDetector` requires an exact (normalized) literal match against
"銀行帳號"/"護照", so a single wrong character anywhere in the label makes
the whole line invisible to it — and by extension to
`WholeImageSanityScanner`, which reuses the same exact-match logic.

This module does NOT fuzzy-match label text against "銀行帳號"/"護照" (that
was evaluated and rejected — see module docstring bottom section, "Why not
OCR-tolerant fuzzy label matching"). Instead it looks for a STRUCTURAL
pattern that doesn't care what the label characters actually say:

    [a short run of CJK-only tokens] [a colon-like token] [a value-shaped token]

i.e. "something label-shaped, followed by a colon, followed by something
that looks like a Passport/BankAccount value" — evaluated purely on token
SHAPE and POSITION, never on whether the CJK run's text matches a known
word. This is deliberately looser on the label side (it doesn't need to be
right) and therefore MUST be stricter about requiring combined evidence
before it means anything (Security Rule, Phase 6.2 brief §4): a plausible
value shape by itself is never sufficient — it is only ever emitted
alongside the structural label-position evidence, and every Detection this
module produces is `unknown=True`. That routes it through Policy Engine's
EXISTING fail-safe path (`_ALWAYS_FAIL_SAFE_TYPES` already includes both
Passport and BankAccount, unmodified) — which forces FULL_MASK +
needs_review=True. This module cannot cause an unreviewed, confident
release; a false positive here fails safe (over-masking + a review flag),
never silently under-masks.

Why not OCR-tolerant fuzzy label matching (e.g. edit-distance against
"銀行帳號"/"護照")? Evaluated and rejected for this phase: on a
single/double-character label, an edit-distance-1 threshold loose enough to
catch "銀行帳虢" would also match a large fraction of unrelated 4-character
CJK phrases by chance, and there is no natural "distance threshold" that
cleanly separates "OCR typo of a known label" from "a different label
entirely" at this string length. The structural approach below doesn't need
that threshold at all — it doesn't inspect what the label says.
"""
from __future__ import annotations

import re

from ..models import Detection, OcrToken
from ..textline import group_into_lines
from .normalization import is_colon_like_token

_CJK_RANGE = ("一", "鿿")  # CJK Unified Ideographs block, same range ai_detector.py already uses
_MAX_TOKEN_CJK_LEN = 4
_LABEL_RUN_LENGTH_RANGE = (2, 6)  # total CJK characters across the run, e.g. "護照"=2, "銀行帳號"=4

_BANK_ACCOUNT_DIGIT_RANGE = (8, 16)  # plausible bank-account digit-count window
_PASSPORT_SHAPE = re.compile(r"^[A-Z]{1,2}[0-9]{6,9}$")


def _is_cjk_only_token(text: str) -> bool:
    if not text or len(text) > _MAX_TOKEN_CJK_LEN:
        return False
    return all(_CJK_RANGE[0] <= ch <= _CJK_RANGE[1] for ch in text)


def _candidate_type_for_value(text: str) -> str | None:
    if text.isdigit() and _BANK_ACCOUNT_DIGIT_RANGE[0] <= len(text) <= _BANK_ACCOUNT_DIGIT_RANGE[1]:
        return "BankAccount"
    if _PASSPORT_SHAPE.fullmatch(text):
        return "Passport"
    return None


class CandidateValueDetector:
    """Structural fallback for Passport/BankAccount when the label itself
    is OCR-damaged. Every emitted Detection has `unknown=True` — see module
    docstring for why that is the load-bearing safety property here."""

    def detect(self, tokens: list[OcrToken]) -> list[Detection]:
        detections: list[Detection] = []
        for line in group_into_lines(tokens):
            detections.extend(self._scan_line(line))
        return detections

    def _scan_line(self, line: list[OcrToken]) -> list[Detection]:
        detections: list[Detection] = []
        n = len(line)
        for colon_index in range(1, n - 1):
            if not is_colon_like_token(line[colon_index].text):
                continue

            value_token = line[colon_index + 1]
            candidate_type = _candidate_type_for_value(value_token.text)
            if candidate_type is None:
                continue

            run_start = self._find_cjk_run_start(line, colon_index)
            if run_start is None:
                continue

            detections.append(
                Detection(
                    type=candidate_type,
                    text=value_token.text,
                    confidence=0.5,
                    bounding_box=value_token.bounding_box,
                    source_layers=["candidate_value"],
                    unknown=True,
                )
            )
        return detections

    def _find_cjk_run_start(self, line: list[OcrToken], colon_index: int) -> int | None:
        """Walks backward from the colon to find a contiguous run of
        CJK-only tokens immediately preceding it, and checks the run's
        TOTAL character length falls in the plausible label-length window.
        Returns the run's start index, or None if there's no such run."""
        run_length = 0
        index = colon_index - 1
        while index >= 0 and _is_cjk_only_token(line[index].text):
            run_length += len(line[index].text)
            index -= 1

        run_start = index + 1
        if run_start == colon_index:
            return None  # no CJK token immediately before the colon at all
        if not (_LABEL_RUN_LENGTH_RANGE[0] <= run_length <= _LABEL_RUN_LENGTH_RANGE[1]):
            return None
        return run_start


def _boxes_overlap(a, b) -> bool:
    ax0, ay0, ax1, ay1 = a.as_rect()
    bx0, by0, bx1, by1 = b.as_rect()
    return ax0 < bx1 and bx0 < ax1 and ay0 < by1 and by0 < ay1


def filter_unclaimed(candidates: list[Detection], existing_detections: list[Detection]) -> list[Detection]:
    """Drops any candidate whose region overlaps a detection any OTHER
    detector already produced — REGARDLESS of type.

    Root cause this fixes (Phase 6.2 benchmark false-positive sweep): a
    value that some other detector already classified correctly can still
    coincidentally match one of THIS module's loose shape checks under a
    DIFFERENT type — e.g. a Taiwan ID's "A123456789" (1 letter + 9 digits)
    also fits the loose Passport shape, and a 10-digit phone number falls
    inside the BankAccount digit-count window. This module exists
    specifically as a fallback for when normal detection found NOTHING at
    that location (a damaged label) — if something was already found there,
    a redundant same-spot guess only adds noise, never safety.
    """
    if not existing_detections:
        return candidates
    return [
        candidate
        for candidate in candidates
        if not any(_boxes_overlap(candidate.bounding_box, existing.bounding_box) for existing in existing_detections)
    ]
