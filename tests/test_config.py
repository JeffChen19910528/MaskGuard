from maskguard.config import load_config


def test_default_config_loads_from_repo_yaml():
    config = load_config()
    assert config.ocr.engine == "local"
    assert config.masking.default_action == "blur"
    assert config.output.preserve_metadata is False


def test_strict_mode_forces_local_and_verification():
    config = load_config()
    config.masking.verification = False
    config.apply_strict_mode()
    assert config.strict_mode is True
    assert config.ocr.engine == "local"
    assert config.masking.verification is True
