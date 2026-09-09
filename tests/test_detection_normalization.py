"""P0-2 regression tests: Context/Keyword detection must not miss a Chinese
label because the OCR engine split it into one token per character."""
from maskguard.detection.context_detector import ContextDetector
from maskguard.detection.keyword_detector import KeywordDetector
from maskguard.detection.line_matching import LineIndex, build_line_index
from maskguard.detection.normalization import normalize_for_context

from conftest import line, tok


def test_per_character_name_label_normalizes_to_contiguous_text():
    # Simulates real Tesseract chi_tra output for "姓名：王小明": one token
    # per Han character, plus the small-form colon variant it sometimes uses.
    tokens = line("姓", "名", "﹕", "王", "小", "明")
    index = build_line_index(tokens)
    normalized = normalize_for_context(index)
    assert normalized.normalized_text == "姓名:王小明"


def test_context_detector_finds_name_when_ocr_splits_every_character():
    tokens = line("姓", "名", "﹕", "王", "小", "明")
    detections = ContextDetector().detect(tokens)
    assert any(d.type == "PersonalName" and d.text == "王小明" for d in detections)


def test_context_detector_still_works_with_single_token_label():
    # Ensures the fix doesn't regress the case where OCR already returns the
    # label as one contiguous token (e.g. a cleaner font/engine).
    tokens = line("姓名：", "王小明")
    detections = ContextDetector().detect(tokens)
    assert any(d.type == "PersonalName" and d.text == "王小明" for d in detections)


def test_context_detector_bounding_box_maps_back_to_only_the_value_tokens():
    tokens = line("姓", "名", "﹕", "王", "小", "明")
    detections = ContextDetector().detect(tokens)
    name_detection = next(d for d in detections if d.type == "PersonalName")

    value_tokens = tokens[3:]  # 王, 小, 明
    label_tokens = tokens[:3]  # 姓, 名, ﹕

    expected_left = min(t.bounding_box.x for t in value_tokens)
    expected_right = max(t.bounding_box.x + t.bounding_box.width for t in value_tokens)
    assert name_detection.bounding_box.x == expected_left
    assert name_detection.bounding_box.x + name_detection.bounding_box.width == expected_right

    # The label's own tokens must NOT be swept into the detected region.
    label_right_edge = max(t.bounding_box.x + t.bounding_box.width for t in label_tokens)
    assert name_detection.bounding_box.x >= label_right_edge


def test_keyword_detector_finds_chinese_id_keyword_split_per_character():
    tokens = line("身", "分", "證", "﹕", "A123456789")
    hits = KeywordDetector().detect(tokens)
    assert any(h.category == "PersonalID" and h.critical for h in hits)


def test_normalize_for_context_collapses_multiple_spaces_between_cjk():
    # "姓 名" (single space) and "姓  名" (double space) between two CJK
    # tokens must both normalize the same as "姓名" (no space) — the
    # requirement explicitly calls out this whitespace-count independence.
    # `build_line_index` always inserts exactly one join-space, so this
    # constructs a LineIndex directly to exercise a real multi-space run.
    t1, t2 = tok("姓", x=0), tok("名", x=50)
    single_space_index = LineIndex(text="姓 名", token_spans=[(0, 1, t1), (2, 3, t2)])
    double_space_index = LineIndex(text="姓  名", token_spans=[(0, 1, t1), (3, 4, t2)])

    assert normalize_for_context(single_space_index).normalized_text == "姓名"
    assert normalize_for_context(double_space_index).normalized_text == "姓名"


def test_normalize_for_context_does_not_insert_spaces_inside_a_single_token():
    # Regression guard: normalization must only ever act BETWEEN tokens, never
    # inside one token's own text (e.g. underscores in an API key token).
    tokens = [tok("demo_test_key_123456789", x=0)]
    normalized = normalize_for_context(build_line_index(tokens))
    assert normalized.normalized_text == "demo_test_key_123456789"


def test_normalize_for_context_keeps_space_between_label_and_latin_value():
    # "身分證: A123456789" style boundary — CJK/punctuation followed directly
    # by a Latin/digit token should keep exactly one canonical space, since
    # that IS a real word boundary (unlike CJK-CJK token joins).
    tokens = line("身", "分", "證", "﹕", "A123456789")
    normalized = normalize_for_context(build_line_index(tokens))
    assert normalized.normalized_text == "身分證: A123456789"
