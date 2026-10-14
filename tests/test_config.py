"""Tests for configuration loading and validation (no network)."""

# pyright: reportPrivateUsage=false

from __future__ import annotations

from pathlib import Path

import pytest

import main


def test_require_int_ok() -> None:
    assert main._require_int({"A": 3}, "A") == 3


@pytest.mark.parametrize(
    "config",
    [
        {},
        {"A": None},
        {"A": "3"},
        {"A": 3.5},
        {"A": True},
    ],
)
def test_require_int_rejects(config: dict[str, object]) -> None:
    with pytest.raises(main.ConfigurationError):
        main._require_int(config, "A")


def test_require_str_map_missing_is_empty() -> None:
    assert main._require_str_map({}, "SUBJECT_MAPPING") == {}


def test_require_str_map_coerces() -> None:
    assert main._require_str_map({"M": {"A": "B", 1: 2}}, "M") == {"A": "B", "1": "2"}


def test_require_str_map_rejects_non_mapping() -> None:
    with pytest.raises(main.ConfigurationError):
        main._require_str_map({"M": ["A"]}, "M")


def test_real_mapping_config_loads() -> None:
    mappings = main.load_mappings_config()
    assert isinstance(mappings.CONTROLLER_MODE, int)
    assert isinstance(mappings.ACTION_TYPE, int)
    assert isinstance(mappings.MENU_ID, int)
    assert isinstance(mappings.SUBJECT_MAPPING, dict)


def test_load_mappings_config_missing_file(tmp_path: Path) -> None:
    with pytest.raises(main.ConfigurationError, match="not found"):
        main.load_mappings_config(tmp_path / "mapping.json")


def test_load_mappings_config_invalid_json(tmp_path: Path) -> None:
    bad = tmp_path / "mapping.json"
    bad.write_text("{not json", encoding="utf-8")
    with pytest.raises(main.ConfigurationError, match="Invalid JSON"):
        main.load_mappings_config(bad)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("1", True),
        ("true", True),
        ("yes", True),
        ("0", False),
        ("false", False),
        ("", False),
    ],
)
def test_env_bool(monkeypatch: pytest.MonkeyPatch, value: str, expected: bool) -> None:
    monkeypatch.setenv("ATTEND_TEST_FLAG", value)
    assert main._env_bool("ATTEND_TEST_FLAG") is expected


def test_env_bool_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ATTEND_TEST_FLAG", raising=False)
    assert main._env_bool("ATTEND_TEST_FLAG") is False
    assert main._env_bool("ATTEND_TEST_FLAG", "true") is True


def test_get_branch_config() -> None:
    config = main.MappingsConfig(
        {
            "CONTROLLER_MODE": 1,
            "ACTION_TYPE": 2,
            "MENU_ID": 3,
            "SUBJECT_MAPPING": {"A": "B"},
        }
    )
    branch = config.get_branch_config("PES2UG23CS001")
    assert (branch.controller_mode, branch.action_type, branch.menu_id) == (1, 2, 3)
    assert branch.subject_mapping == {"A": "B"}
