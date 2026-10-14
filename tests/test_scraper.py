"""Tests for scraper parsing helpers (no network)."""

# pyright: reportPrivateUsage=false

from __future__ import annotations

import asyncio
from http.cookies import SimpleCookie
from typing import Any, Self, cast

import aiohttp
import pytest

import main


def make_scraper() -> main.PESUAttendanceScraper:
    """Build a scraper instance without running `__init__` (no I/O)."""
    scraper = main.PESUAttendanceScraper.__new__(main.PESUAttendanceScraper)
    scraper.logger = None
    return scraper


def test_scraper_init_wires_mappings() -> None:
    scraper = main.PESUAttendanceScraper("PES2UG23CS001", "pw")
    assert scraper.controller_mode == main.mappings.CONTROLLER_MODE
    assert scraper.batch_class_ids is None
    assert scraper.auto_discovered_batch_ids is None
    assert scraper.branch_prefix == "PES2UG23CS"


def test_scraper_init_explicit_batch_id() -> None:
    scraper = main.PESUAttendanceScraper("PES2UG23CS001", "pw", batch_id=42)
    assert scraper.batch_class_ids == [42]


@pytest.mark.parametrize(
    "html",
    [
        '<html><body><input name="_csrf" value="tok-input"/></body></html>',
        '<html><head><meta name="csrf-token" content="tok-meta"/></head></html>',
        "<html><body><script>var _csrf = 'deadbeef12345678';</script></body></html>",
        "<html><body>ref 123e4567-e89b-12d3-a456-426614174000</body></html>",
    ],
)
def test_extract_csrf_token_variants(html: str) -> None:
    token = make_scraper()._extract_csrf_token(html)
    assert token


def test_extract_csrf_token_prefers_input() -> None:
    html = (
        '<html><head><meta name="_csrf" content="tok-meta"/></head>'
        '<body><input name="_csrf" value="tok-input"/></body></html>'
    )
    assert make_scraper()._extract_csrf_token(html) == "tok-input"


def test_extract_csrf_token_missing() -> None:
    with pytest.raises(main.AuthenticationError):
        make_scraper()._extract_csrf_token("<html><body>no token</body></html>")


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ('"123"', 123),
        ("batch-456", 456),
        (789, 789),
        (None, None),
        ("", None),
        ("abc", None),
    ],
)
def test_parse_batch_id(value: object, expected: int | None) -> None:
    assert main.PESUAttendanceScraper._parse_batch_id(value) == expected


def test_normalize_batch_ids() -> None:
    assert main.PESUAttendanceScraper._normalize_batch_ids(5) == ["5"]
    assert main.PESUAttendanceScraper._normalize_batch_ids([1, 2]) == ["1", "2"]


@pytest.mark.parametrize(
    ("row", "expected"),
    [
        (["CS101", "Intro", "10", "80%"], True),
        (["CS101", "Intro", "NA", "NA"], True),
        (["only-one-cell"], False),
        (["", "x", "1", "2"], False),
        (["   ", "x", "1", "2"], False),
    ],
)
def test_is_valid_attendance_record(row: list[str], expected: bool) -> None:
    assert make_scraper()._is_valid_attendance_record(row) is expected


def test_parse_attendance_table() -> None:
    html = (
        '<table class="table"><tbody>'
        "<tr><td>CS101</td><td>Intro</td><td>10</td><td>80%</td></tr>"
        "<tr><td></td><td>x</td><td>1</td><td>2</td></tr>"
        "</tbody></table>"
    )
    rows = make_scraper()._parse_attendance_table(html)
    assert rows == [["CS101", "Intro", "10", "80%"]]


def test_parse_attendance_table_missing() -> None:
    assert make_scraper()._parse_attendance_table("<html></html>") is None
    assert (
        make_scraper()._parse_attendance_table('<table class="table"></table>') is None
    )


LOGIN_PAGE = (
    "<html><body><form action='/j_spring_security_check'>"
    "<input type='hidden' name='_csrf' value='formtoken'/>"
    "<input name='j_username'/><input name='j_password'/>"
    "</form></body></html>"
)

PROFILE_PAGE = (
    "<html><body><a href='/logout'>logout</a>"
    "<input type='hidden' name='_csrf' value='profiletoken'/>"
    "</body></html>"
)

SEMESTERS_PAGE = (
    "<html><body><select>"
    "<option value='11'>Sem 1</option><option value='22'>Sem 2</option>"
    "</select></body></html>"
)

ADMIN_PAGE = (
    "<html><body><table class='table'><tbody>"
    "<tr><td>CS101</td><td>Intro</td><td>10</td><td>80%</td></tr>"
    "</tbody></table></body></html>"
)

LOGIN_FAILURE_PAGE = (
    "<html><body><form action='/j_spring_security_check'>"
    "<input name='j_username'/>invalid login, try again"
    "</form></body></html>"
)


class _FakeResponse:
    def __init__(
        self,
        *,
        status: int = 200,
        url: str = "",
        body: str = "",
        exc: BaseException | None = None,
    ) -> None:
        self.status = status
        self.url = url
        self._body = body
        self._exc = exc
        self.headers = {"content-type": "text/html"}

    async def __aenter__(self) -> Self:
        if self._exc is not None:
            raise self._exc
        return self

    async def __aexit__(self, *args: object) -> bool:
        return False

    def raise_for_status(self) -> None:
        return None

    async def text(self) -> str:
        return self._body


class _FakeCookieJar:
    def __init__(self) -> None:
        self._jar = SimpleCookie()

    def filter_cookies(self, url: object) -> SimpleCookie:
        del url
        return self._jar


class _FakeSession:
    def __init__(self, routes: list[tuple[str, str, _FakeResponse]]) -> None:
        self._routes = routes
        self.closed = False
        self.cookie_jar = _FakeCookieJar()
        self.requests: list[tuple[str, str]] = []

    def _match(self, method: str, url: str) -> _FakeResponse:
        self.requests.append((method, url))
        for route_method, marker, response in self._routes:
            if method == route_method and marker in url:
                return response
        raise AssertionError(f"unexpected request: {method} {url}")

    def get(self, url: str, **kwargs: Any) -> _FakeResponse:
        del kwargs
        return self._match("GET", url)

    def post(self, url: str, **kwargs: Any) -> _FakeResponse:
        del kwargs
        return self._match("POST", url)

    async def close(self) -> None:
        self.closed = True


def _success_session() -> _FakeSession:
    base = main.PESUAttendanceScraper.BASE_URL
    return _FakeSession(
        [
            (
                "POST",
                "j_spring_security_check",
                _FakeResponse(url=base, body=PROFILE_PAGE),
            ),
            (
                "POST",
                "studentProfilePESUAdmin",
                _FakeResponse(url=base, body=ADMIN_PAGE),
            ),
            (
                "GET",
                "getStudentSemestersPESU",
                _FakeResponse(url=base, body=SEMESTERS_PAGE),
            ),
            ("GET", "studentProfilePESU", _FakeResponse(url=base, body=PROFILE_PAGE)),
            ("GET", "/logout", _FakeResponse(url=base, body="ok")),
            ("GET", "/Academy/", _FakeResponse(url=base + "/", body=LOGIN_PAGE)),
        ]
    )


def _inject(scraper: main.PESUAttendanceScraper, session: _FakeSession) -> None:
    """Assign a fake session directly so `close()` exercises its real path."""
    scraper._session = cast("aiohttp.ClientSession", session)


def test_login_discovers_batch_ids() -> None:
    async def _flow() -> main.PESUAttendanceScraper:
        scraper = main.PESUAttendanceScraper("PES2UG23CS001", "pw")
        _inject(scraper, _success_session())
        await scraper.login()
        return scraper

    scraper = asyncio.run(_flow())
    assert scraper.batch_class_ids == [11, 22]
    assert scraper.auto_discovered_batch_ids == [11, 22]
    assert scraper.sem_texts == {11: "Sem 1", 22: "Sem 2"}


def test_full_scrape_flow() -> None:
    async def _flow() -> tuple[list[list[str]] | None, _FakeSession]:
        scraper = main.PESUAttendanceScraper("PES2UG23CS001", "pw")
        fake = _success_session()
        _inject(scraper, fake)
        await scraper.login()
        data = await scraper.scrape_attendance_data()
        await scraper.close()
        return data, fake

    data, fake = asyncio.run(_flow())
    assert data == [["CS101", "Intro", "10", "80%"]]
    assert any(
        method == "GET" and url.endswith("/logout") for method, url in fake.requests
    )
    assert fake.closed is True


def test_get_semester_options() -> None:
    async def _flow() -> dict[int, str] | None:
        scraper = main.PESUAttendanceScraper("PES2UG23CS001", "pw")
        _inject(scraper, _success_session())
        await scraper.login()
        return await scraper.get_semester_options()

    assert asyncio.run(_flow()) == {11: "Sem 1", 22: "Sem 2"}


def test_login_failure() -> None:
    async def _flow() -> None:
        scraper = main.PESUAttendanceScraper("u", "p")
        base = main.PESUAttendanceScraper.BASE_URL
        fake = _FakeSession(
            [
                (
                    "POST",
                    "j_spring_security_check",
                    _FakeResponse(url=base, body=LOGIN_FAILURE_PAGE),
                ),
                ("GET", "/Academy/", _FakeResponse(url=base + "/", body=LOGIN_PAGE)),
            ]
        )
        _inject(scraper, fake)
        with pytest.raises(main.AuthenticationError):
            await scraper.login()

    asyncio.run(_flow())


def test_close_without_session() -> None:
    async def _flow() -> None:
        scraper = main.PESUAttendanceScraper("u", "p")
        await scraper.close()

    asyncio.run(_flow())


def test_close_releases_session() -> None:
    async def _flow() -> bool:
        scraper = main.PESUAttendanceScraper("u", "p")
        fake = _FakeSession([("GET", "/logout", _FakeResponse(body="ok"))])
        _inject(scraper, fake)
        await scraper.close()
        return fake.closed

    assert asyncio.run(_flow()) is True


def test_login_timeout_is_authentication_error() -> None:
    async def _flow() -> None:
        scraper = main.PESUAttendanceScraper("u", "p")
        base = main.PESUAttendanceScraper.BASE_URL
        fake = _FakeSession(
            [
                (
                    "GET",
                    "/Academy/",
                    _FakeResponse(url=base + "/", exc=TimeoutError()),
                ),
            ]
        )
        _inject(scraper, fake)
        with pytest.raises(main.AuthenticationError, match="Network error"):
            await scraper.login()

    asyncio.run(_flow())


def test_batch_timeout_falls_through_to_next_batch() -> None:
    async def _flow() -> list[list[str]] | None:
        scraper = main.PESUAttendanceScraper("u", "p", batch_id=11)
        base = main.PESUAttendanceScraper.BASE_URL
        fake = _FakeSession(
            [
                (
                    "POST",
                    "studentProfilePESUAdmin",
                    _FakeResponse(url=base, exc=TimeoutError()),
                ),
            ]
        )
        _inject(scraper, fake)
        return await scraper._fetch_attendance_for_batch("11", "tok")

    assert asyncio.run(_flow()) is None
