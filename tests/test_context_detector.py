from maskguard.detection.context_detector import ContextDetector

from conftest import line


def test_bare_name_becomes_classifiable_via_label():
    tokens = line("姓名：", "王小明")
    detections = ContextDetector().detect(tokens)
    assert any(d.type == "PersonalName" and d.text == "王小明" for d in detections)


def test_no_match_without_label():
    tokens = line("王小明")
    detections = ContextDetector().detect(tokens)
    assert detections == []
