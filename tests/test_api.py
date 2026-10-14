"""Tests for the FastAPI routes (scraper stubbed, no network)."""

# pyright: reportPrivateUsage=false
# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from fastapi.testclient import TestClient

import main

ROWS = [["CS101", "Intro", "10", "80%"]]


class _StubScraper:
    def __init__(self) -> None:
        self.subject_mapping = {"CS101": "Intro CS"}
        self.auto_discovered_batch_ids: list[int] | None = [11, 22]


async def _stub_fetch(
    username: str, password: str, batch_id: int | None = None
) -> tuple[list[list[str]], _StubScraper]:
    del username, password, batch_id
    return ROWS, _StubScraper()


async def _stub_auth_failure(
    username: str, password: str, batch_id: int | None = None
) -> tuple[list[list[str]] | None, _StubScraper]:
    del username, password, batch_id
    raise main.AuthenticationError("bad credentials")


async def _stub_no_data(
    username: str, password: str, batch_id: int | None = None
) -> tuple[None, _StubScraper]:
    del username, password, batch_id
    return None, _StubScraper()


class _StubSemesterScraper:
    def __init__(self, username: str, password: str) -> None:
        del username, password

    async def login(self) -> None:
        return None

    async def logout(self) -> None:
        return None

    async def close(self) -> None:
        return None

    async def get_semester_options(self) -> dict[int, str] | None:
        return {11: "Sem 1"}


class _FailingSemesterScraper(_StubSemesterScraper):
    async def login(self) -> None:
        raise RuntimeError("boom")


def test_healthcheck(client: TestClient) -> None:
    response: Any = client.get("/api/healthcheck")
    assert response.status_code == 200
    assert response.json()["code"] == "healthcheck_ok"


def test_attendance_rejects_empty_credentials(client: TestClient) -> None:
    response: Any = client.post(
        "/api/attendance", json={"username": "", "password": "x"}
    )
    assert response.status_code == 422


def test_attendance_success(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(main, "fetch_student_attendance", _stub_fetch)
    response: Any = client.post(
        "/api/attendance", json={"username": "u", "password": "p"}
    )
    assert response.status_code == 200
    body: Any = response.json()
    assert body["code"] == "attendance_retrieved"
    assert body["data"]["status"] == "complete"
    assert body["data"]["attendance"][0]["subject"] == "Intro CS"
    assert body["data"]["discovered_batch_ids"] == ["11", "22"]


def test_attendance_auth_failure(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(main, "fetch_student_attendance", _stub_auth_failure)
    response: Any = client.post(
        "/api/attendance", json={"username": "u", "password": "p"}
    )
    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "auth_failed"


def test_attendance_no_data(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(main, "fetch_student_attendance", _stub_no_data)
    response: Any = client.post(
        "/api/attendance", json={"username": "u", "password": "p"}
    )
    assert response.status_code == 500
    assert response.json()["detail"]["code"] == "scraping_failed"


def test_process_attendance_task_no_data(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(main, "fetch_student_attendance", _stub_no_data)
    with pytest.raises(main.AttendanceScrapingError):
        asyncio.run(main.process_attendance_task("u", "p"))


def test_semesters_success(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(main, "PESUAttendanceScraper", _StubSemesterScraper)
    response: Any = client.post(
        "/api/semesters", json={"username": "u", "password": "p"}
    )
    assert response.status_code == 200
    assert response.json()["data"] == {"semesters": {"11": "Sem 1"}}


def test_semesters_failure(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(main, "PESUAttendanceScraper", _FailingSemesterScraper)
    response: Any = client.post(
        "/api/semesters", json={"username": "u", "password": "p"}
    )
    assert response.status_code == 500
    assert response.json()["detail"]["code"] == "semesters_failed"


def test_mapping_json(client: TestClient) -> None:
    response: Any = client.get("/mapping.json")
    assert response.status_code == 200
    assert "CONTROLLER_MODE" in response.json()


def test_static_js(client: TestClient) -> None:
    assert client.get("/chart.min.js").status_code == 200
    assert client.get("/i.js").status_code == 200


def test_openapi_lists_routes(client: TestClient) -> None:
    paths: Any = client.get("/openapi.json").json()["paths"]
    assert "/api/attendance" in paths
    assert "/api/semesters" in paths
    assert "/api/healthcheck" in paths
