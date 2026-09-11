"""Phase 10.3 §49-51/§63/§79: role-mapping configuration loading/
validation. Pure unit tests — no Tesseract, no HTTP, no Docker.
"""
from __future__ import annotations

import pytest
import yaml

from maskguard.api.authorization.role_config import AuthorizationConfigError, _load_yaml_mapping


def _write(tmp_path, content: dict):
    path = tmp_path / "roles.yaml"
    path.write_text(yaml.safe_dump(content), encoding="utf-8")
    return str(path)


def test_valid_mapping_loads(tmp_path):
    path = _write(tmp_path, {"mappings": [{"issuer": "https://idp.example", "subject": "abc", "roles": ["Operator"]}]})
    mapping = _load_yaml_mapping(path)
    assert mapping.roles_for("https://idp.example|abc") == frozenset({"Operator"})


def test_unmapped_identity_gets_no_roles(tmp_path):
    path = _write(tmp_path, {"mappings": [{"issuer": "https://idp.example", "subject": "abc", "roles": ["Operator"]}]})
    mapping = _load_yaml_mapping(path)
    assert mapping.roles_for("https://idp.example|someone-else") == frozenset()


def test_missing_file_fails_closed():
    with pytest.raises(AuthorizationConfigError):
        _load_yaml_mapping("/nonexistent/path/does/not/exist.yaml")


def test_malformed_yaml_fails_closed(tmp_path):
    path = tmp_path / "roles.yaml"
    path.write_text("not: valid: yaml: [[[", encoding="utf-8")
    with pytest.raises(AuthorizationConfigError):
        _load_yaml_mapping(str(path))


def test_missing_mappings_key_fails_closed(tmp_path):
    path = _write(tmp_path, {"not_mappings": []})
    with pytest.raises(AuthorizationConfigError):
        _load_yaml_mapping(path)


def test_unknown_role_fails_closed(tmp_path):
    path = _write(tmp_path, {"mappings": [{"issuer": "https://idp.example", "subject": "abc", "roles": ["SuperAdmin"]}]})
    with pytest.raises(AuthorizationConfigError):
        _load_yaml_mapping(path)


def test_duplicate_identity_entry_fails_closed(tmp_path):
    path = _write(
        tmp_path,
        {
            "mappings": [
                {"issuer": "https://idp.example", "subject": "abc", "roles": ["Operator"]},
                {"issuer": "https://idp.example", "subject": "abc", "roles": ["Reviewer"]},
            ]
        },
    )
    with pytest.raises(AuthorizationConfigError):
        _load_yaml_mapping(path)


def test_missing_issuer_fails_closed(tmp_path):
    path = _write(tmp_path, {"mappings": [{"subject": "abc", "roles": ["Operator"]}]})
    with pytest.raises(AuthorizationConfigError):
        _load_yaml_mapping(path)


def test_missing_subject_fails_closed(tmp_path):
    path = _write(tmp_path, {"mappings": [{"issuer": "https://idp.example", "roles": ["Operator"]}]})
    with pytest.raises(AuthorizationConfigError):
        _load_yaml_mapping(path)


def test_empty_roles_list_fails_closed(tmp_path):
    path = _write(tmp_path, {"mappings": [{"issuer": "https://idp.example", "subject": "abc", "roles": []}]})
    with pytest.raises(AuthorizationConfigError):
        _load_yaml_mapping(path)


def test_multiple_roles_per_identity(tmp_path):
    path = _write(
        tmp_path, {"mappings": [{"issuer": "https://idp.example", "subject": "abc", "roles": ["Reviewer", "Auditor"]}]}
    )
    mapping = _load_yaml_mapping(path)
    assert mapping.roles_for("https://idp.example|abc") == frozenset({"Reviewer", "Auditor"})


def test_empty_file_is_empty_mapping(tmp_path):
    path = tmp_path / "roles.yaml"
    path.write_text("", encoding="utf-8")
    mapping = _load_yaml_mapping(str(path))
    assert mapping.roles_for("anyone|anywhere") == frozenset()
