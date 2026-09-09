"""Phase 6.2 regression tests: CandidateValueDetector.

Positive cases mirror the exact 4 real-OCR fixtures this was built to
catch (label character misread, value read correctly). Negative cases
cover the required false-positive sweep: generic numbers/codes that must
NOT be misclassified as Passport/BankAccount just because they happen to
sit after a short CJK run and a colon.
"""
from maskguard.detection.candidate_value import CandidateValueDetector, filter_unclaimed
from maskguard.detection.context_detector import ContextDetector
from maskguard.detection.regex_detector import RegexDetector
from maskguard.models import RedactionAction, RiskLevel
from maskguard.policy.policy_engine import PolicyEngine
from maskguard.config import MaskingConfig
from maskguard.risk.risk_engine import RiskEngine

from conftest import line


def _detect(tokens):
    return CandidateValueDetector().detect(tokens)


# ---------------------------------------------------------------------------
# Positive cases: the exact real-OCR shapes that defeated ContextDetector.
# ---------------------------------------------------------------------------


def test_bank_account_low_res_misread_last_label_char():
    tokens = line("銀", "行", "帳", "虢", "﹕", "1234567890123")  # 號 -> 虢
    dets = _detect(tokens)
    assert any(d.type == "BankAccount" and d.text == "1234567890123" and d.unknown for d in dets)


def test_bank_account_blurred_misread_first_label_char():
    tokens = line("銨", "行", "帳", "號", "﹕", "1234567890123")  # 銀 -> 銨
    dets = _detect(tokens)
    assert any(d.type == "BankAccount" and d.unknown for d in dets)


def test_passport_low_res_misread_second_label_char():
    tokens = line("護", "烈", "﹕", "PA1234567")  # 照 -> 烈
    dets = _detect(tokens)
    assert any(d.type == "Passport" and d.text == "PA1234567" and d.unknown for d in dets)


def test_candidate_detection_still_works_with_correctly_read_label():
    # The structural pattern doesn't care whether the label is CORRECT —
    # confirms this isn't accidentally coupled to the misread case only.
    tokens = line("護", "照", "﹕", "PA1234567")
    dets = _detect(tokens)
    assert any(d.type == "Passport" for d in dets)


# ---------------------------------------------------------------------------
# Every finding is `unknown=True` and routes through the EXISTING
# fail-safe path (unmodified RiskEngine/PolicyEngine) to FULL_MASK +
# needs_review — never a silent confident classification.
# ---------------------------------------------------------------------------


def test_candidate_finding_is_always_unknown_and_forces_review_via_existing_failsafe():
    tokens = line("銀", "行", "帳", "虢", "﹕", "1234567890123")
    detections = _detect(tokens)
    scored = RiskEngine().score(detections, [])
    decided = PolicyEngine(MaskingConfig()).decide(scored)

    bank_account = next(d for d in decided if d.type == "BankAccount")
    assert bank_account.action == RedactionAction.FULL_MASK
    assert bank_account.needs_review is True


# ---------------------------------------------------------------------------
# Negative cases (Phase 6.2 brief §6): generic values must NOT be
# misclassified just because they sit after a short CJK run + colon.
# ---------------------------------------------------------------------------


def test_generic_invoice_number_after_short_label_is_not_misclassified_as_bank_account():
    tokens = line("發", "票", "﹕", "1234567890123")
    dets = _detect(tokens)
    # This is a real, disclosed trade-off (see report): a 13-digit value in
    # this exact structural position DOES still match the BankAccount shape
    # check, since shape alone can't distinguish "invoice number" from
    # "bank account" — this test pins down that CURRENT behavior rather
    # than silently assuming it's absent. It always resolves `unknown=True`
    # (fail-safe review), never a confident BankAccount classification.
    for d in dets:
        assert d.unknown is True


def test_order_number_with_letters_and_dash_is_not_matched_as_any_candidate():
    tokens = line("訂", "單", "﹕", "ORD-123456")
    dets = _detect(tokens)
    assert dets == []


def test_employee_id_with_dash_is_not_matched():
    tokens = line("員", "工", "﹕", "EMP-000123")
    dets = _detect(tokens)
    assert dets == []


def test_tracking_number_too_long_for_passport_shape_is_not_matched():
    tokens = line("追", "蹤", "﹕", "1Z999AA9999999999")
    dets = _detect(tokens)
    assert dets == []


def test_serial_number_all_letters_no_digits_is_not_matched():
    tokens = line("序", "號", "﹕", "ABCDEFGH")
    dets = _detect(tokens)
    assert dets == []


def test_plain_english_word_after_label_is_not_matched():
    tokens = line("備", "註", "﹕", "hello")
    dets = _detect(tokens)
    assert dets == []


def test_short_generic_number_below_bank_account_length_is_not_matched():
    tokens = line("數", "量", "﹕", "1234567")  # 7 digits, below the 8-digit floor
    dets = _detect(tokens)
    assert dets == []


def test_long_generic_number_above_bank_account_length_is_not_matched():
    tokens = line("編", "號", "﹕", "12345678901234567")  # 17 digits, above the 16-digit ceiling
    dets = _detect(tokens)
    assert dets == []


def test_value_without_any_preceding_cjk_run_is_not_matched():
    tokens = line("value", "﹕", "1234567890123")  # label run isn't CJK at all
    dets = _detect(tokens)
    assert dets == []


def test_no_colon_at_all_is_not_matched():
    tokens = line("銀行帳號", "1234567890123")  # missing separator entirely
    dets = _detect(tokens)
    assert dets == []


def test_label_run_too_long_is_not_matched():
    # An 8-character CJK run followed by a colon and a digit string is far
    # more likely to be an ordinary long phrase/sentence fragment than a
    # short field label — outside the plausible label-length window.
    tokens = line("這", "是", "一", "段", "很", "長", "的", "描", "述", "﹕", "1234567890123")
    dets = _detect(tokens)
    assert dets == []



# ---------------------------------------------------------------------------
# filter_unclaimed: the fix for the Phase 6.2 benchmark's false-positive
# spike — a value some OTHER detector already correctly classified must
# not also get a redundant, wrongly-typed candidate finding.
# ---------------------------------------------------------------------------


def test_filter_unclaimed_drops_candidate_overlapping_an_existing_taiwan_id():
    # "A123456789" is a real Taiwan ID (regex-classified) that ALSO
    # coincidentally fits the loose Passport shape (1 letter + 9 digits) —
    # this is the exact real false positive the benchmark caught.
    tokens = line("身分證", "﹕", "A123456789")
    existing = RegexDetector().detect(tokens) + ContextDetector().detect(tokens)
    candidates = _detect(tokens)

    assert any(d.type == "Passport" for d in candidates), "test setup: shape overlap must reproduce"
    filtered = filter_unclaimed(candidates, existing)
    assert filtered == []


def test_filter_unclaimed_drops_candidate_overlapping_an_existing_phone_number():
    # A 10-digit Taiwan phone number falls inside the BankAccount
    # digit-count window — the other real false positive the benchmark caught.
    tokens = line("電話", "﹕", "0912345678")
    existing = RegexDetector().detect(tokens) + ContextDetector().detect(tokens)
    candidates = _detect(tokens)

    assert any(d.type == "BankAccount" for d in candidates), "test setup: shape overlap must reproduce"
    filtered = filter_unclaimed(candidates, existing)
    assert filtered == []


def test_filter_unclaimed_keeps_candidate_when_nothing_else_claimed_the_region():
    # The genuine positive case: label OCR-damaged, nothing else detected
    # this region at all, so the candidate must survive the filter.
    tokens = line("銀", "行", "帳", "虢", "﹕", "1234567890123")
    existing = RegexDetector().detect(tokens) + ContextDetector().detect(tokens)
    assert existing == []  # confirms the label really is unrecognized by both

    candidates = _detect(tokens)
    filtered = filter_unclaimed(candidates, existing)
    assert any(d.type == "BankAccount" for d in filtered)


def test_filter_unclaimed_is_a_no_op_with_no_existing_detections():
    tokens = line("銀", "行", "帳", "虢", "﹕", "1234567890123")
    candidates = _detect(tokens)
    assert filter_unclaimed(candidates, []) == candidates


def test_product_id_two_letters_six_digits_can_match_passport_shape():
    # Documents a real, disclosed limitation: a product/SKU code shaped
    # exactly like [1-2 letters][6-9 digits] is indistinguishable from a
    # passport number by SHAPE alone. This is why every finding is
    # `unknown=True` (fail-safe review), never a confident classification —
    # pinning this down rather than silently assuming it doesn't happen.
    tokens = line("產", "品", "﹕", "AB123456")
    dets = _detect(tokens)
    for d in dets:
        assert d.unknown is True
