"""Tests for attendance formatting helpers (no network)."""

# pyright: reportPrivateUsage=false

from __future__ import annotations

import pytest

import main


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("10", 10),
        (" 12 classes ", 12),
        ("NA", None),
        ("na", None),
        ("  NA  ", None),
        (None, None),
        ("", None),
        ("abc", None),
    ],
)
def test_coerce_int(raw: str | None, expected: int | None) -> None:
    assert main._coerce_int(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("80%", 80.0),
        ("82.5 %", 82.5),
        ("75", 75.0),
        ("NA", None),
        ("na", None),
        (None, None),
        ("", None),
        ("abc", None),
    ],
)
def test_coerce_float(raw: str | None, expected: float | None) -> None:
    assert main._coerce_float(raw) == expected


def test_format_attendance_data_applies_mapping() -> None:
    rows = [["CS101", "Intro to CS", "10", "80%"]]
    out = main.format_attendance_data(rows, {"CS101": "Intro CS"})
    assert out == [
        {
            "subject": "Intro CS",
            "course_name": "Intro to CS",
            "total_classes": 10,
            "percentage": 80.0,
            "raw_data": "10",
        }
    ]


def test_format_attendance_data_falls_back_to_code() -> None:
    rows = [["UNKNOWN01", "Something", "5", "50%"]]
    out = main.format_attendance_data(rows, {})
    assert out[0]["subject"] == "UNKNOWN01"


def test_format_attendance_data_normalizes_na() -> None:
    rows = [["CS102", "Algo", "NA", "NA"]]
    out = main.format_attendance_data(rows, {})
    assert out[0]["total_classes"] is None
    assert out[0]["percentage"] is None
    assert out[0]["raw_data"] == "NA"


def test_format_attendance_data_skips_empty_rows() -> None:
    assert main.format_attendance_data([[]], {}) == []


def test_attendance_record_defaults() -> None:
    record = main.AttendanceRecord(subject="CS101")
    assert record.course_name is None
    assert record.total_classes is None
    assert record.percentage is None
    assert record.raw_data is None
