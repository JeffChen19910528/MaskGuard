from maskguard.detection.keyword_detector import KeywordDetector

from conftest import line


def test_password_keyword_is_flagged_critical():
    tokens = line("password:", "hunter2")
    hits = KeywordDetector().detect(tokens)
    assert any(h.category == "Credential" and h.critical for h in hits)


def test_chinese_id_keyword_is_flagged_critical():
    tokens = line("身分證:", "A123456789")
    hits = KeywordDetector().detect(tokens)
    assert any(h.category == "PersonalID" and h.critical for h in hits)


def test_no_keyword_hits_for_plain_text():
    tokens = line("this", "is", "unrelated", "text")
    hits = KeywordDetector().detect(tokens)
    assert hits == []
