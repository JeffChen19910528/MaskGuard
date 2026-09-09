"""Real-Tesseract end-to-end validation of the full MaskGuard pipeline:

    Image -> Preprocess -> Real OCR -> Detection -> Risk -> Policy
          -> Redaction -> Verification (re-OCR) -> Output

Every test here is skipped (not failed, not passed) when the Tesseract
binary/language data isn't installed — see tests/e2e/_environment.py and
conftest.py's `ocr_env` fixture, which is the thing that actually enforces
"SKIPPED / ENVIRONMENT NOT READY" instead of a false pass.

All fixture images are synthetic (see scripts/generate_test_images.py) and
carry a visible "TEST DATA (SYNTHETIC)" banner.
"""
from __future__ import annotations

import json

import pytest
from PIL import Image

from maskguard.config import load_config
from maskguard.detection import ContextDetector, KeywordDetector, RegexDetector
from maskguard.models import RedactionAction, RiskLevel
from maskguard.ocr.tesseract_engine import LocalOcrEngine
from maskguard.pipeline import Pipeline
from maskguard.policy import PolicyEngine
from maskguard.preprocessing import load_and_normalize
from maskguard.redaction import RedactionEngine
from maskguard.risk import RiskEngine
from maskguard.verification import VerificationEngine

LANGUAGES = ["zh-TW", "en"]


# ---------------------------------------------------------------------------
# 1 & 2: OCR extracts text with correct, in-bounds bounding boxes
# ---------------------------------------------------------------------------


def test_ocr_extracts_text_from_real_image(ocr_env, fixture_path):
    image = load_and_normalize(str(fixture_path("mixed_sensitive.png")))
    tokens = LocalOcrEngine().recognize(image, LANGUAGES)

    assert len(tokens) > 5, "expected multiple OCR tokens from a multi-line test image"
    joined = " ".join(t.text for t in tokens).lower()
    assert "example.com" in joined or "example" in joined


def test_ocr_reads_mixed_chinese_english_text(ocr_env, fixture_path):
    """Requirement: verify OCR on a line mixing Chinese and English/Latin
    script in the same image (Skill.md §35 "中英文混合"). This only checks
    that OCR recovers text in *both* scripts — see
    test_context_detector_misses_chinese_labeled_name_due_to_per_character_tokenization
    for the separate, real classification gap this fixture also exposes.
    """
    image = load_and_normalize(str(fixture_path("mixed_language.png")))
    tokens = LocalOcrEngine().recognize(image, LANGUAGES)
    joined = "".join(t.text for t in tokens)

    assert "Wang" in joined or "wang" in joined.lower(), "expected Latin-script name fragment from OCR"
    has_cjk = any("一" <= ch <= "鿿" for ch in joined)
    assert has_cjk, "expected at least one recognized CJK character from OCR"


def test_ocr_bounding_boxes_are_within_image_bounds(ocr_env, fixture_path):
    image = load_and_normalize(str(fixture_path("mixed_sensitive.png")))
    tokens = LocalOcrEngine().recognize(image, LANGUAGES)

    assert tokens, "OCR returned no tokens at all"
    for token in tokens:
        box = token.bounding_box
        assert box.width > 0 and box.height > 0
        assert box.x >= 0 and box.y >= 0
        assert box.x + box.width <= image.width
        assert box.y + box.height <= image.height


# ---------------------------------------------------------------------------
# 3: Sensitive Detector finds the expected data types per fixture
# ---------------------------------------------------------------------------

_SINGLE_VALUE_FIXTURES = [
    "email.png", "phone.png", "taiwan_id.png", "credit_card.png", "api_key.png",
    "passport.png", "bank_account.png",
]


@pytest.mark.parametrize("fixture_name", _SINGLE_VALUE_FIXTURES)
def test_detection_finds_expected_type_per_fixture(ocr_env, fixture_path, fixtures_manifest, fixture_name):
    expected_types = set(fixtures_manifest[fixture_name]["expected_types"])
    image = load_and_normalize(str(fixture_path(fixture_name)))
    tokens = LocalOcrEngine().recognize(image, LANGUAGES)

    detections = RegexDetector().detect(tokens) + ContextDetector().detect(tokens)
    found_types = {d.type for d in detections}

    assert expected_types & found_types, (
        f"{fixture_name}: expected one of {expected_types}, OCR+detection found {found_types}"
    )


def test_context_detector_finds_chinese_labeled_name_against_real_ocr(ocr_env, fixture_path):
    """P0-2 FIX REGRESSION TEST (requirement A).

    Was: Tesseract's chi_tra recognition returns each Han character as its
    own separate word-token (confirmed against this exact fixture: "姓","名",
    "﹕","王","小","明" as six tokens for "姓名：王小明"), and the old
    `ContextDetector` matched against a raw single-space token join, so the
    label substring "姓名" never appeared contiguously and the detection was
    silently missed — a real false negative reproduced against real OCR
    output, not a hypothetical.

    Now: `ContextDetector` matches against `normalize_for_context()`'s
    output, which drops the artificial join-space between two CJK tokens
    (keeping it only at a real word boundary, e.g. before a Latin/digit
    value), so "姓 名 ﹕ 王 小 明" normalizes to "姓名:王小明" and the label
    matches. This must now find PersonalName "王小明" in the real image.
    """
    image = load_and_normalize(str(fixture_path("mixed_sensitive.png")))
    tokens = LocalOcrEngine().recognize(image, LANGUAGES)

    detections = RegexDetector().detect(tokens) + ContextDetector().detect(tokens)
    name_detections = [d for d in detections if d.type == "PersonalName"]

    assert name_detections, "PersonalName was not detected — P0-2 fix regressed"
    assert any("王小明" in d.text for d in name_detections)


def test_detection_finds_all_types_in_mixed_sensitive_image(ocr_env, fixture_path, fixtures_manifest):
    expected_types = set(fixtures_manifest["mixed_sensitive.png"]["expected_types"])
    image = load_and_normalize(str(fixture_path("mixed_sensitive.png")))
    tokens = LocalOcrEngine().recognize(image, LANGUAGES)

    detections = RegexDetector().detect(tokens) + ContextDetector().detect(tokens)
    found_types = {d.type for d in detections}

    missing = expected_types - found_types
    # Real OCR is not 100% accurate; report which types were missed rather
    # than silently failing on a single OCR misread. Threshold raised to 5/6
    # (was 4/6) after the P0-2 fix: PersonalName is now reliably recovered
    # too, so only genuine single-character OCR misreads (unrelated to
    # tokenization/spacing) should ever cost a point here.
    assert len(found_types & expected_types) >= 5, (
        f"too few expected types recovered: found={found_types}, missing={missing}"
    )


# ---------------------------------------------------------------------------
# 4 & 5 & 9: Risk Engine scores correctly, Policy Engine assigns the right
# action, and CRITICAL data always gets FULL_MASK — using real OCR input.
# ---------------------------------------------------------------------------


def test_risk_and_policy_engines_on_real_ocr_output(ocr_env, fixture_path):
    config = load_config()
    image = load_and_normalize(str(fixture_path("credit_card.png")))
    tokens = LocalOcrEngine().recognize(image, LANGUAGES)

    detections = RegexDetector().detect(tokens)
    keyword_hits = KeywordDetector().detect(tokens)

    # Before Risk/Policy run, no detector may have set a final action —
    # this is the "AI/Detector -> Recommendation only" invariant (Skill.md §41).
    assert all(d.action == RedactionAction.NONE for d in detections)

    scored = RiskEngine().score(detections, keyword_hits)
    credit_card = next((d for d in scored if d.type == "CreditCard"), None)
    assert credit_card is not None, "real OCR + regex failed to find the test credit card number"
    assert credit_card.risk_level == RiskLevel.CRITICAL

    decided = PolicyEngine(config.masking).decide(scored)
    credit_card_decided = next(d for d in decided if d.type == "CreditCard")
    assert credit_card_decided.action == RedactionAction.FULL_MASK, (
        "CRITICAL data (credit card) must always resolve to FULL_MASK (Skill.md §12 Critical)"
    )


# ---------------------------------------------------------------------------
# Intrinsic Critical Sensitive Data Risk Classification (P0 fix):
# TaiwanID / Passport / BankAccount / CreditCard must resolve CRITICAL ->
# FULL_MASK through the REAL full pipeline (real Tesseract OCR, real
# RiskEngine intrinsic-floor logic, real PolicyEngine, real RedactionEngine,
# real re-OCR Verification) — not a fake OCR engine standing in for any of
# these types.
# ---------------------------------------------------------------------------

_INTRINSIC_CRITICAL_FIXTURES = [
    ("taiwan_id.png", "TaiwanID"),
    ("passport.png", "Passport"),
    ("bank_account.png", "BankAccount"),
    ("credit_card.png", "CreditCard"),
    ("api_key.png", "SecretKeyValue"),
]


@pytest.mark.parametrize("fixture_name,expected_type", _INTRINSIC_CRITICAL_FIXTURES)
def test_intrinsic_critical_type_reaches_full_mask_and_passes_verification_via_real_ocr(
    ocr_env, fixture_path, tmp_path, fixture_name, expected_type
):
    """Full real pipeline: Image -> real Tesseract OCR -> Detection -> Risk
    (intrinsic floor) -> Policy -> FULL_MASK -> Verification -> PASS.

    This is the concrete proof for the "TaiwanID/Passport/BankAccount was
    landing HIGH->BLUR instead of CRITICAL->FULL_MASK" bug: run the exact
    same Pipeline the CLI uses, against a real synthetic image, through real
    OCR both for detection AND for verification's re-OCR pass.
    """
    config = load_config()
    pipeline = Pipeline(config)

    input_path = fixture_path(fixture_name)
    output_image = tmp_path / "out.png"
    report_path = tmp_path / "out.json"
    log_path = tmp_path / "audit.log"

    result = pipeline.process(str(input_path), str(output_image), str(report_path), str(log_path))

    assert not result.blocked
    matching = [d for d in result.report["detections"] if d["type"] == expected_type]
    assert matching, f"{fixture_name}: expected type {expected_type} was not detected at all"
    assert matching[0]["risk"] == "CRITICAL", (
        f"{fixture_name}: {expected_type} must be CRITICAL, was {matching[0]['risk']}"
    )
    assert matching[0]["action"] == "FULL_MASK", (
        f"{fixture_name}: {expected_type} must resolve to FULL_MASK, was {matching[0]['action']}"
    )
    assert result.verification.status == "PASSED", (
        f"{fixture_name}: verification did not pass: {result.verification}"
    )


# ---------------------------------------------------------------------------
# 6 & 7: Redaction actually changes pixels in sensitive regions and leaves
# non-sensitive regions untouched.
# ---------------------------------------------------------------------------


def test_redaction_modifies_sensitive_region_only(ocr_env, fixture_path, tmp_path):
    config = load_config()
    config.masking.verification = False  # isolate redaction behavior from verification retries

    pipeline = Pipeline(config)
    input_path = fixture_path("credit_card.png")
    output_image = tmp_path / "out.png"
    report_path = tmp_path / "out.json"
    log_path = tmp_path / "audit.log"

    result = pipeline.process(str(input_path), str(output_image), str(report_path), str(log_path))
    assert not result.blocked

    original = Image.open(input_path).convert("RGB")
    redacted = Image.open(output_image).convert("RGB")
    assert original.size == redacted.size

    # A corner far from any text must be untouched (still pure white).
    assert redacted.getpixel((5, 5)) == (255, 255, 255)

    # At least one pixel must have actually changed (proves redaction ran).
    diff_found = any(
        original.getpixel((x, y)) != redacted.getpixel((x, y))
        for x in range(0, original.width, 4)
        for y in range(0, original.height, 4)
    )
    assert diff_found, "redacted output is pixel-identical to the input — redaction did not run"


# ---------------------------------------------------------------------------
# 8: Redacted region cannot be re-recognized as the original sensitive value
# (independent check, on top of the pipeline's own verification step).
# ---------------------------------------------------------------------------


def test_full_pipeline_output_does_not_leak_raw_values_under_reocr(ocr_env, fixture_path, tmp_path):
    config = load_config()  # default: verification enabled

    pipeline = Pipeline(config)
    input_path = fixture_path("mixed_sensitive.png")
    output_image = tmp_path / "out.png"
    report_path = tmp_path / "out.json"
    log_path = tmp_path / "audit.log"

    result = pipeline.process(str(input_path), str(output_image), str(report_path), str(log_path))
    assert not result.blocked
    assert result.verification.status == "PASSED", (
        f"verification did not pass: {result.verification}"
    )

    # Independent whole-image re-OCR check (not reusing VerificationEngine's
    # own bounding boxes) for the raw secrets used in this fixture.
    redacted_tokens = LocalOcrEngine().recognize(Image.open(output_image).convert("RGB"), LANGUAGES)
    recovered_text = " ".join(t.text for t in redacted_tokens)

    for raw_secret in ["A123456789", "4111 1111 1111 1111", "demo_test_key_123456789"]:
        assert raw_secret not in recovered_text, f"raw secret leaked in redacted output: {raw_secret!r}"


# ---------------------------------------------------------------------------
# 10: Verification failure must trigger escalation (widen box / stronger
# method) until it passes or exhausts retries.
# ---------------------------------------------------------------------------


def test_verification_escalates_a_weak_initial_redaction(ocr_env, fixture_path):
    """Simulates a Policy Engine bug/undecided action (RedactionAction.NONE,
    i.e. no redaction at all) to deterministically exercise the escalation
    ladder against real OCR: first attempt must fail (text still fully
    readable), escalate() must kick in, and a later attempt must pass.

    Uses api_key.png rather than credit_card.png deliberately: the API key
    value OCRs as a single contiguous token both on the full page and on the
    re-OCR'd crop, so this test isolates the escalation ladder itself from
    the *separate* tokenization-mismatch bug documented in
    test_verification_residual_check_can_miss_retokenized_multi_word_values
    (a real multi-token value like the credit card number can legitimately
    OCR into different word-groupings on a full page vs. a tight crop, which
    defeats the naive substring residual check independently of escalation).
    """
    image = load_and_normalize(str(fixture_path("api_key.png")))
    tokens = LocalOcrEngine().recognize(image, LANGUAGES)
    detections = RegexDetector().detect(tokens)
    secret = next(d for d in detections if d.type == "SecretKeyValue")
    secret.action = RedactionAction.NONE  # deliberately weak/unset action

    redaction_engine = RedactionEngine()
    verification_engine = VerificationEngine(LocalOcrEngine(), redaction_engine, max_retries=4)

    redacted, verification = verification_engine.verify_and_fix(image, [secret], LANGUAGES)

    assert verification.attempts > 1, "expected escalation to require more than one attempt"
    assert verification.status == "PASSED"
    assert secret.action == RedactionAction.FULL_MASK, (
        "escalation ladder must end at FULL_MASK when weaker methods fail"
    )


def test_verification_fails_on_unredacted_card_despite_ocr_retokenization(ocr_env, fixture_path):
    """P0-1 FIX REGRESSION TEST (requirements B & D) — THE ORIGINAL P0 REPRO.

    Was: `VerificationEngine._find_residual` compared the ORIGINAL OCR
    reading of a detection (`detection.text`, captured once at detection
    time) against a FRESH OCR reading of the cropped region using exact
    substring equality. Confirmed against this exact fixture: the full-page
    OCR pass mis-tokenizes "4111 1111 1111 1111" as "41111111 11111111" (two
    8-digit halves), while a fresh OCR of the same, still fully-visible
    region (action deliberately left as NONE — never redacted) correctly
    reads it back as "4111 1111 1111 1111" (four 4-digit groups). Those two
    strings never share a common substring, so the old exact-match check
    reported "no residual" — a **false PASS while the card number was still
    completely readable in the output image**.

    Now: `_find_residual` compares both readings through
    `normalize_for_verification()`, which reduces both to the identical
    canonical digit string regardless of how either OCR pass grouped/spaced
    them, and separately re-runs `RegexDetector` on the fresh crop as a second
    independent check. Verification must now correctly FAIL — an OCR wording/
    tokenization difference must never manufacture a false PASS.
    """
    image = load_and_normalize(str(fixture_path("credit_card.png")))
    tokens = LocalOcrEngine().recognize(image, LANGUAGES)
    detections = RegexDetector().detect(tokens)
    credit_card = next(d for d in detections if d.type == "CreditCard")
    credit_card.action = RedactionAction.NONE  # never redacted — the sensitive value is still fully visible

    verification_engine = VerificationEngine(LocalOcrEngine(), RedactionEngine(), max_retries=1)
    _redacted, verification = verification_engine.verify_and_fix(image, [credit_card], LANGUAGES)

    assert verification.status == "FAILED", (
        "P0-1 regression: verification must FAIL when the card number is still "
        "fully visible, even though the two real OCR passes tokenized/spaced it "
        "differently — it must never produce a false PASS from wording alone"
    )
    assert verification.residual_count == 1


def test_verification_passes_only_after_genuine_full_mask_of_credit_card(ocr_env, fixture_path, tmp_path):
    """Requirement C: once the same credit card is genuinely redacted (via
    the real Policy Engine decision — CRITICAL risk -> FULL_MASK — and the
    real RedactionEngine), verification against real OCR must PASS."""
    config = load_config()
    pipeline = Pipeline(config)

    input_path = fixture_path("credit_card.png")
    output_image = tmp_path / "out.png"
    report_path = tmp_path / "out.json"
    log_path = tmp_path / "audit.log"

    result = pipeline.process(str(input_path), str(output_image), str(report_path), str(log_path))

    assert not result.blocked
    assert result.verification.status == "PASSED"
    credit_card_entries = [d for d in result.report["detections"] if d["type"] == "CreditCard"]
    assert credit_card_entries and credit_card_entries[0]["action"] == "FULL_MASK"

    # Independent re-OCR of the actual output file, not reusing the engine's
    # own crop/box math, as a second confirmation nothing leaked.
    redacted_tokens = LocalOcrEngine().recognize(Image.open(output_image).convert("RGB"), LANGUAGES)
    recovered_text = " ".join(t.text for t in redacted_tokens)
    assert "4111 1111 1111 1111" not in recovered_text
    assert "4111111111111111" not in recovered_text.replace(" ", "")


# ---------------------------------------------------------------------------
# 11: EXIF metadata must be stripped from the output.
# ---------------------------------------------------------------------------


def test_exif_metadata_is_removed_from_output(ocr_env, fixture_path, tmp_path):
    source = Image.open(fixture_path("email.png")).convert("RGB")
    exif = source.getexif()
    exif[0x010F] = "MaskGuardTestCameraMake"  # EXIF "Make" tag
    input_with_exif = tmp_path / "input_with_exif.png"
    source.save(input_with_exif, exif=exif.tobytes())

    # Confirm the EXIF actually round-trips into the input file before testing removal.
    assert Image.open(input_with_exif).getexif().get(0x010F) == "MaskGuardTestCameraMake"

    config = load_config()
    pipeline = Pipeline(config)
    output_image = tmp_path / "out.png"
    report_path = tmp_path / "out.json"
    log_path = tmp_path / "audit.log"

    pipeline.process(str(input_with_exif), str(output_image), str(report_path), str(log_path))

    output_exif = Image.open(output_image).getexif()
    assert 0x010F not in output_exif, "EXIF Make tag survived into the redacted output (Skill.md §23)"


# ---------------------------------------------------------------------------
# 12: Audit log and processing report must never contain raw sensitive text.
# ---------------------------------------------------------------------------


def test_audit_log_and_report_never_contain_raw_sensitive_text(ocr_env, fixture_path, tmp_path):
    config = load_config()
    pipeline = Pipeline(config)

    input_path = fixture_path("mixed_sensitive.png")
    output_image = tmp_path / "out.png"
    report_path = tmp_path / "out.json"
    log_path = tmp_path / "audit.log"

    pipeline.process(str(input_path), str(output_image), str(report_path), str(log_path))

    log_content = log_path.read_text(encoding="utf-8")
    report_content = report_path.read_text(encoding="utf-8")

    raw_secrets = ["A123456789", "4111 1111 1111 1111", "4111", "demo_test_key_123456789", "0912345678"]
    for secret in raw_secrets:
        assert secret not in log_content, f"audit log leaked raw text: {secret!r}"
        assert secret not in report_content, f"processing report leaked raw text: {secret!r}"

    # Report/log must still carry the *metadata* about what was found (Skill.md §22/§25).
    report = json.loads(report_content)
    assert len(report["detections"]) > 0
    for detection in report["detections"]:
        assert set(detection.keys()) == {"type", "confidence", "risk", "action", "region", "needs_review"}


# ---------------------------------------------------------------------------
# Architecture invariant: no single component decides the final action.
# ---------------------------------------------------------------------------


def test_only_policy_engine_sets_final_action_on_real_detections(ocr_env, fixture_path):
    image = load_and_normalize(str(fixture_path("mixed_sensitive.png")))
    tokens = LocalOcrEngine().recognize(image, LANGUAGES)

    regex_detections = RegexDetector().detect(tokens)
    context_detections = ContextDetector().detect(tokens)
    keyword_hits = KeywordDetector().detect(tokens)

    # Detectors (Regex/Keyword/Context) must never set a final action themselves.
    for detection in regex_detections + context_detections:
        assert detection.action == RedactionAction.NONE

    all_detections = regex_detections + context_detections
    scored = RiskEngine().score(all_detections, keyword_hits)

    # Risk Engine assigns risk_score/risk_level, but must still not set the action.
    for detection in scored:
        assert detection.action == RedactionAction.NONE
        assert detection.risk_level in RiskLevel

    decided = PolicyEngine(load_config().masking).decide(scored)
    # Only after the Policy Engine runs does every surviving detection carry a real action.
    for detection in decided:
        assert detection.action != RedactionAction.NONE
