#!/usr/bin/env python3
"""PESU Attendance Tracker

Run with environment toggles to choose which components start:
- ``ENABLE_BACKEND_API``: start the API (defaults to true).
- ``ENABLE_BACKEND_WEB``: mount and serve the static frontend (defaults to true).
- ``ENABLE_BACKEND_TELEGRAM``: launch the Telegram bot as a subprocess
  (defaults to false).

Examples:
    Run API and bot, but do not serve the frontend:
    .. code-block:: console
        $ export ENABLE_BACKEND_WEB=false
        $ export ENABLE_BACKEND_TELEGRAM=true
        $ uv run main.py
"""

from __future__ import annotations

import argparse
import atexit
import json
import logging
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast
from urllib.parse import urljoin

import aiohttp
import colorama
import uvicorn
from bs4 import BeautifulSoup, Tag
from colorama import Fore, Style
from dotenv import load_dotenv
from fastapi import APIRouter, FastAPI, HTTPException
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from yarl import URL

REQUEST_TIMEOUT_SECONDS_DEFAULT = 15
IMMUTABLE_JS_CACHE_CONTROL = "public, max-age=31536000, immutable"
FRONTEND_WEB_DIR = "frontend/web"
FRONTEND_DISABLED_DETAILS = (
    "Frontend disabled. Set ENABLE_BACKEND_WEB=true to enable serving the web frontend."
)

REPO_ROOT = Path(__file__).resolve().parent

__all__ = [
    "APIResponse",
    "AppSettings",
    "AttendanceRequest",
    "AttendanceScrapingError",
    "AuthenticationError",
    "ConfigurationError",
    "MappingsConfig",
    "MappingsData",
    "PESUAttendanceScraper",
    "SemesterRequest",
    "app",
    "app_log",
    "app_logger",
    "fetch_student_attendance",
    "format_attendance_data",
    "load_app_settings",
    "load_mappings_config",
    "mappings",
    "process_attendance_task",
    "run",
    "settings",
    "setup_logger",
]


class APIResponse:
    """Standardized API response envelope for all clients (web, bot, CLI)."""

    @staticmethod
    def success(
        data: Any, code: str = "success", message: str = "Operation successful"
    ) -> dict[str, Any]:
        """Build a standardized success payload.

        Args:
            data: JSON-serializable response payload.
            code: Machine-readable status code.
            message: Human-readable summary.

        Returns:
            Success envelope with ``success=True`` and a timestamp.
        """
        return {
            "success": True,
            "code": code,
            "message": message,
            "data": data,
            "timestamp": time.time(),
        }

    @staticmethod
    def error(
        error_type: str, details: str, code: str = "error", status_code: int = 400
    ) -> tuple[dict[str, Any], int]:
        """Build a standardized error payload with an HTTP status.

        Args:
            error_type: Short error category (e.g. ``"AuthenticationError"``).
            details: Human-readable explanation of the failure.
            code: Machine-readable error code.
            status_code: HTTP status code to return alongside the payload.

        Returns:
            Tuple of (error envelope, HTTP status code).
        """
        response = {
            "success": False,
            "code": code,
            "message": f"{error_type}: {details}",
            "error": {
                "type": error_type,
                "details": details,
            },
            "timestamp": time.time(),
        }
        return response, status_code


def http_error(
    error_type: str, details: str, code: str, status_code: int
) -> HTTPException:
    """Build an :class:`HTTPException` carrying a standardized error payload.

    Args:
        error_type: Short error category.
        details: Human-readable explanation of the failure.
        code: Machine-readable error code.
        status_code: HTTP status code for the response.

    Returns:
        Configured ``HTTPException`` whose ``detail`` holds the envelope.
    """
    payload, status = APIResponse.error(
        error_type=error_type, details=details, code=code, status_code=status_code
    )
    return HTTPException(status_code=status, detail=payload)


class ConfigurationError(Exception):
    """Raised when configuration loading or validation fails."""


@dataclass(frozen=True)
class MappingsData:
    """Resolved scraper mapping values for a single student branch.

    Attributes:
        controller_mode: Controller mode expected by the PESU admin endpoint.
        action_type: Action type expected by the PESU admin endpoint.
        menu_id: Menu id expected by the PESU admin endpoint.
        subject_mapping: Mapping of raw subject codes to display names.
    """

    controller_mode: int
    action_type: int
    menu_id: int
    subject_mapping: dict[str, str] = field(default_factory=dict[str, str])


class MappingsConfig:
    """Wrapper around the raw ``mapping.json`` contents.

    Args:
        config: Parsed JSON mapping of the ``mapping.json`` file.

    Raises:
        ConfigurationError: If a required key is missing or mistyped.
    """

    def __init__(self, config: dict[str, Any]) -> None:
        self.CONTROLLER_MODE: int = _require_int(config, "CONTROLLER_MODE")
        self.ACTION_TYPE: int = _require_int(config, "ACTION_TYPE")
        self.MENU_ID: int = _require_int(config, "MENU_ID")
        self.SUBJECT_MAPPING: dict[str, str] = _require_str_map(
            config, "SUBJECT_MAPPING"
        )

    def get_branch_config(self, srn: str) -> MappingsData:
        """Resolve the mapping values for a student SRN.

        Args:
            srn: Ignored. A single mapping applies to all branches. The
                parameter remains for a per-branch signature.

        Returns:
            Resolved :class:`MappingsData` for the branch.
        """
        return MappingsData(
            controller_mode=self.CONTROLLER_MODE,
            action_type=self.ACTION_TYPE,
            menu_id=self.MENU_ID,
            subject_mapping=self.SUBJECT_MAPPING,
        )


def _require_int(config: dict[str, Any], key: str) -> int:
    """Extract a required integer value from a raw config mapping.

    Args:
        config: Raw parsed JSON mapping.
        key: Key to look up.

    Returns:
        The integer value.

    Raises:
        ConfigurationError: If the key is missing or not an integer.
    """
    value = config.get(key)
    # NOTE: `bool` subclasses `int`, so exclude it explicitly.
    if isinstance(value, bool) or not isinstance(value, int):
        raise ConfigurationError(f"mapping.json must define integer {key!r}.")
    return value


def _require_str_map(config: dict[str, Any], key: str) -> dict[str, str]:
    """Extract an optional string-to-string mapping from a raw config mapping.

    Args:
        config: Raw parsed JSON mapping.
        key: Key to look up.

    Returns:
        The mapping with keys and values coerced via :func:`str`. The result
        is empty when the key is absent.

    Raises:
        ConfigurationError: If the key is present but not a mapping.
    """
    value: Any = config.get(key, {}) or {}
    if not isinstance(value, dict):
        raise ConfigurationError(f"mapping.json key {key!r} must be a mapping.")
    mapping = cast("dict[Any, Any]", value)
    return {str(item_key): str(item_value) for item_key, item_value in mapping.items()}


def _env_bool(name: str, default: str = "false") -> bool:
    """Parse a boolean environment variable.

    Args:
        name: Environment variable name.
        default: Fallback string value when the variable is unset.

    Returns:
        True for ``1``/``true``/``yes`` (case-insensitive), else False.
    """
    return os.getenv(name, default).lower() in ("1", "true", "yes")


class AppSettings:
    """Runtime settings sourced from environment variables.

    Attributes:
        PORT: Port the API server listens on.
        LOG_LEVEL: Logging verbosity name (e.g. ``"INFO"``).
        DEBUG: Whether uvicorn auto-reload is enabled.
        REQUEST_TIMEOUT_SECONDS: Reserved timeout budget for outbound calls.
        ENABLE_BACKEND_API: Whether to start the API server.
        ENABLE_BACKEND_WEB: Whether to serve the static frontend.
        ENABLE_BACKEND_TELEGRAM: Whether to launch the Telegram bot subprocess.
    """

    def __init__(self) -> None:
        try:
            if Path(".env.local").exists():
                load_dotenv(".env.local")
            else:
                load_dotenv()
        except Exception:  # noqa: BLE001, S110 - missing .env falls back to os.environ
            pass

        self.PORT: int = int(os.getenv("PORT", "10000"))
        self.LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
        self.DEBUG: bool = _env_bool("DEBUG", "false")
        self.REQUEST_TIMEOUT_SECONDS: int = int(
            os.getenv("REQUEST_TIMEOUT_SECONDS", "5")
        )
        self.ENABLE_BACKEND_API: bool = _env_bool("ENABLE_BACKEND_API", "true")
        self.ENABLE_BACKEND_WEB: bool = _env_bool("ENABLE_BACKEND_WEB", "true")
        self.ENABLE_BACKEND_TELEGRAM: bool = _env_bool(
            "ENABLE_BACKEND_TELEGRAM", "false"
        )


def load_mappings_config(config_path: Path | None = None) -> MappingsConfig:
    """Load and validate the ``mapping.json`` configuration file.

    Args:
        config_path: Explicit path to ``mapping.json``. Defaults to
            ``<repo>/frontend/web/mapping.json``.

    Returns:
        Parsed :class:`MappingsConfig`.

    Raises:
        ConfigurationError: If the file is missing, is not valid JSON, or
            cannot be read.
    """
    path = config_path or (REPO_ROOT / FRONTEND_WEB_DIR / "mapping.json")

    try:
        if not path.exists():
            raise ConfigurationError(f"mapping.json file not found at: {path}.")

        try:
            with path.open("r", encoding="utf-8") as handle:
                config_data = json.load(handle)
        except json.JSONDecodeError as error:
            raise ConfigurationError(
                f"Invalid JSON format in configuration file: {error}"
            ) from error

        return MappingsConfig(config_data)

    except ConfigurationError:
        raise
    except Exception as error:
        raise ConfigurationError(f"Failed to load configuration: {error}") from error


def load_app_settings() -> AppSettings:
    """Load application settings from the environment.

    Returns:
        Populated :class:`AppSettings`.

    Raises:
        ConfigurationError: If settings cannot be constructed.
    """
    try:
        return AppSettings()
    except Exception as error:
        raise ConfigurationError(
            f"Failed to load application settings: {error}"
        ) from error


class TextFormatter(logging.Formatter):
    """Fixed-format log lines: UTC timestamp, level, logger name, message.

    Args:
        color: Wrap the level name and message in ANSI colors. Enable color
            for TTY sinks only. Never enable it for piped or collected output.
    """

    def __init__(self, *, color: bool) -> None:
        super().__init__(
            "%(asctime)s %(levelname)-7s %(name)s: %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%SZ",
        )
        self.converter = time.gmtime
        self._color = color

    def format(self, record: logging.LogRecord) -> str:
        """Format a record, optionally colorized, without mutating it.

        Args:
            record: Log record to format.

        Returns:
            Formatted log line.
        """
        if not self._color:
            return super().format(record)
        if record.levelno == logging.DEBUG:
            color = Fore.CYAN
        elif record.levelno == logging.INFO:
            color = Fore.GREEN
        elif record.levelno == logging.WARNING:
            color = Fore.YELLOW
        elif record.levelno == logging.ERROR:
            color = Fore.RED
        else:
            color = Fore.WHITE
        # Copy the record so repeated formatting does not stack color codes.
        record = logging.makeLogRecord(record.__dict__.copy())
        record.levelname = f"{color}{record.levelname}{Style.RESET_ALL}"
        record.msg = f"{color}{record.getMessage()}{Style.RESET_ALL}"
        record.args = ()
        return super().format(record)


class JsonFormatter(logging.Formatter):
    """Single-line JSON log records for collectors and production sinks."""

    def format(self, record: logging.LogRecord) -> str:
        """Serialize a record to a JSON object with UTC timestamp.

        Args:
            record: Log record to format.

        Returns:
            JSON-encoded log line. Carries an ``event`` field when the
            record was emitted with one (see :func:`app_log`), and an
            ``exc`` field when exception info is attached.
        """
        payload: dict[str, Any] = {
            "ts": datetime.now(UTC)
            .isoformat(timespec="milliseconds")
            .replace("+00:00", "Z"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        event = getattr(record, "event", None)
        if event is not None:
            payload["event"] = event
        if record.exc_info is not None and record.exc_info[0] is not None:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def _select_log_format() -> tuple[bool, bool]:
    """Decide the log sink format from ``LOG_FORMAT`` and the stderr TTY state.

    Returns:
        Tuple of (use_json, use_color). ``LOG_FORMAT=json`` forces JSON.
        ``LOG_FORMAT=text`` forces plain text. ``LOG_FORMAT=auto``
        (default) uses JSON off-TTY and colorized text on TTY. Color is
        never selected for non-TTY sinks.
    """
    mode = os.getenv("LOG_FORMAT", "auto").lower()
    use_json = mode == "json" or (mode == "auto" and not sys.stderr.isatty())
    use_color = not use_json and mode != "text" and sys.stderr.isatty()
    return use_json, use_color


def setup_logger(
    name: str | None = None,
    level: str | None = None,
) -> logging.Logger:
    """Configure and return the application logger.

    Every line carries a UTC ISO-8601 timestamp, level, logger name, and
    message. Format selection: ``LOG_FORMAT=json`` forces JSON lines.
    ``LOG_FORMAT=text`` forces human-readable lines.
    ``LOG_FORMAT=auto`` (default) uses JSON when the sink is not a TTY and
    colorized text otherwise. Colors are never emitted to non-TTY sinks.

    Args:
        name: Logger name. Defaults to ``"attend"``.
        level: Log level name (e.g. ``"DEBUG"``). Defaults to ``LOG_LEVEL``.

    Returns:
        Logger with exactly one stderr handler. Propagation is disabled.

    Raises:
        ValueError: If the level name is unknown.
    """
    log_level = (level or os.getenv("LOG_LEVEL", "INFO")).upper()
    logger = logging.getLogger(name if name is not None else "attend")
    logger.setLevel(log_level)

    # Clear existing handlers to avoid duplicates on reload.
    if logger.hasHandlers():
        logger.handlers.clear()

    stream = sys.stderr
    use_json, use_color = _select_log_format()
    if use_color and os.name == "nt":
        colorama.init()

    handler = logging.StreamHandler(stream)
    handler.setFormatter(
        JsonFormatter() if use_json else TextFormatter(color=use_color)
    )
    logger.addHandler(handler)

    # Prevent propagation to root to avoid duplicate logs.
    logger.propagate = False

    return logger


class AuthenticationError(Exception):
    """Raised when authentication with PESU Academy fails."""


class AttendanceScrapingError(Exception):
    """Raised when attendance data scraping encounters an error."""


class PESUAttendanceScraper:
    """Scrapes attendance data from PESU Academy for a single student.

    Args:
        username: PESU Academy username (SRN).
        password: PESU Academy password.
        batch_id: Optional explicit batch class id. When omitted, batch ids
            are auto-discovered from the semesters endpoint at runtime.
        mappings: Optional pre-loaded :class:`MappingsConfig`. Falls back to
            the module-level ``mappings`` for backwards compatibility.
        logger: Optional logger used for debug/info output.
    """

    BASE_URL = "https://www.pesuacademy.com/Academy"

    def __init__(
        self,
        username: str,
        password: str,
        batch_id: int | None = None,
        mappings: MappingsConfig | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        # The HTTP session is created lazily on first use so instances can be
        # constructed outside a running event loop.
        self._session: aiohttp.ClientSession | None = None
        self.username = username
        self.password = password
        self.logger = logger

        config = mappings if mappings is not None else globals().get("mappings")
        if config is None:  # pragma: no cover - defensive fallback
            config = load_mappings_config()

        try:
            branch_config = config.get_branch_config(username)
            self.controller_mode = branch_config.controller_mode
            self.action_type = branch_config.action_type
            self.menu_id = branch_config.menu_id
            self.subject_mapping = branch_config.subject_mapping

            self.batch_class_ids: int | list[int] | None = None
            if batch_id is not None:
                self.batch_class_ids = [batch_id]

            self._auto_discovered_batch_ids: list[int] | None = None
            self.sem_texts: dict[int, str] | None = None

            # SRN prefix for log messages; the full SRN is never logged.
            self.branch_prefix = username[:10]

        except ValueError as error:
            raise ConfigurationError(f"Configuration error: {error}") from error

    @property
    def auto_discovered_batch_ids(self) -> list[int] | None:
        """Batch ids auto-discovered from the semesters endpoint, if any.

        Returns:
            Discovered batch ids, or None when discovery has not run or
            found nothing.
        """
        return self._auto_discovered_batch_ids

    def _log_debug(self, message: str) -> None:
        """Record message at DEBUG. Do nothing when no logger is set."""
        if self.logger is not None:
            self.logger.debug(message)

    def _log_info(self, message: str) -> None:
        """Record message at INFO. Do nothing when no logger is set."""
        if self.logger is not None:
            self.logger.info(message)

    def _log_warning(self, message: str) -> None:
        """Record message at WARNING. Do nothing when no logger is set."""
        if self.logger is not None:
            self.logger.warning(message)

    def _log_error(self, message: str) -> None:
        """Record message at ERROR. Do nothing when no logger is set."""
        if self.logger is not None:
            self.logger.error(message)

    def _extract_csrf_token(self, html_content: str) -> str:
        """Extract the CSRF token from a PESU Academy HTML page.

        The token is searched in several locations, in order:

        - ``<input name="_csrf" value="...">``
        - ``<meta name="_csrf|csrf-token|csrf" content="...">``
        - Inline JS assignments such as ``_csrf = 'uuid'``.
        - Any UUID-like string as a last resort.

        Args:
            html_content: Raw HTML of the page.

        Returns:
            The extracted CSRF token.

        Raises:
            AuthenticationError: If no token can be found.
        """
        soup = BeautifulSoup(html_content, "html.parser")

        csrf_input = soup.find("input", {"name": "_csrf"})
        if csrf_input and csrf_input.get("value"):
            token = csrf_input.get("value")
            assert isinstance(token, str)
            return token

        for meta_name in ("_csrf", "csrf-token", "csrf"):
            meta = soup.find("meta", {"name": meta_name})
            if meta and meta.get("content"):
                token = meta.get("content")
                assert isinstance(token, str)
                return token

        match = re.search(
            r"_csrf['\"]?\s*[:=]\s*['\"]([0-9a-fA-F-]{8,})['\"]", html_content
        )
        if match:
            return match.group(1)

        fallback = re.search(
            r"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})",
            html_content,
            re.IGNORECASE,
        )
        if fallback:
            return fallback.group(1)

        raise AuthenticationError("CSRF token not found in response")

    def _session_csrf(self) -> str | None:
        """Return the CSRF token stored in session cookies, if any.

        Returns:
            Cookie CSRF token or None when absent.
        """
        cookies = self._cookie_dict()
        return cookies.get("XSRF-TOKEN") or cookies.get("CSRF-TOKEN")

    async def _get_session(self) -> aiohttp.ClientSession:
        """Return the shared HTTP session, creating it lazily on first use.

        Returns:
            The active :class:`aiohttp.ClientSession`.
        """
        if self._session is None or self._session.closed:
            # Accept header required to receive the standard login pages.
            self._session = aiohttp.ClientSession(
                headers={
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                },
                timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT_SECONDS_DEFAULT),
            )
        return self._session

    def _cookie_dict(self) -> dict[str, str]:
        """Return the session cookies as a plain mapping.

        Returns:
            Cookie name to value mapping (empty when no session exists yet).
        """
        if self._session is None:
            return {}
        jar = self._session.cookie_jar.filter_cookies(URL(self.BASE_URL))
        return {name: morsel.value for name, morsel in jar.items()}

    async def login(self) -> None:
        """Authenticate with PESU Academy and prepare the session.

        Discovers batch class ids from the semesters endpoint when none were
        provided explicitly.

        Raises:
            AuthenticationError: If any step of the login flow fails.
        """
        self._log_info("Initiating authentication process")

        try:
            session = await self._get_session()
            login_page_url = f"{self.BASE_URL}/"
            async with session.get(login_page_url) as landing_response:
                landing_response.raise_for_status()
                landing_html = await landing_response.text()
                landing_url = str(landing_response.url)

            soup = BeautifulSoup(landing_html, "html.parser")
            form: Tag | None = None
            for candidate in soup.find_all("form"):
                if candidate.find("input", {"name": "j_username"}) or candidate.find(
                    "input", {"name": "username"}
                ):
                    form = candidate
                    break

            action = (
                form.get("action")
                if form is not None and form.get("action")
                else "/j_spring_security_check"
            )
            assert isinstance(action, str)
            if action.startswith("http"):
                login_url = action
            else:
                login_url = urljoin(self.BASE_URL + "/", action.lstrip("/"))

            form_inputs: dict[str, str] = {}
            if form is not None:
                for field_input in form.find_all("input"):
                    raw_name = field_input.get("name")
                    if not raw_name or raw_name in ("j_username", "j_password"):
                        continue
                    # BeautifulSoup types attribute values loosely, so coerce them to str.
                    form_inputs[str(raw_name)] = str(field_input.get("value", ""))

            form_csrf = form_inputs.get("_csrf")
            page_csrf: str | None = None
            try:
                page_csrf = self._extract_csrf_token(landing_html)
            except AuthenticationError:
                page_csrf = None

            if form_csrf:
                csrf_token: str | None = form_csrf
                csrf_source = "form"
            elif page_csrf:
                csrf_token = page_csrf
                csrf_source = "html"
            else:
                csrf_token = self._session_csrf()
                csrf_source = "cookie" if csrf_token else None

            if not csrf_token:
                raise AuthenticationError(
                    "Missing CSRF token (no form, html token or cookie)"
                )

            login_payload = {
                **form_inputs,
                "_csrf": csrf_token,
                "j_username": self.username,
                "j_password": self.password,
            }

            headers = {
                "Content-Type": "application/x-www-form-urlencoded",
                "Origin": "https://www.pesuacademy.com",
                "Referer": landing_url,
                "Sec-GPC": "1",
            }

            self._log_debug(f"Posting to {login_url} with csrf source={csrf_source}")
            async with session.post(
                login_url, data=login_payload, headers=headers
            ) as response:
                login_status = response.status
                login_url_final = str(response.url)
                login_body = await response.text()

            self._log_debug(f"Login POST status={login_status} url={login_url_final}")
            self._log_debug(f"Session cookies after login: {self._cookie_dict()}")

            fallback_html = await self._fetch_https_fallback_html(login_url_final)
            final_body = (
                fallback_html if fallback_html is not None else login_body
            ) or ""
            final_body = final_body.lower()
            if (
                "j_username" in final_body
                or "j_spring_security_check" in final_body
                or ("invalid" in final_body and "login" in final_body)
            ):
                raise AuthenticationError(
                    "Authentication failed: login page or error detected after POST"
                )

            try:
                csrf_after = await self._prepare_profile_context(
                    initial_html=fallback_html
                    if fallback_html is not None
                    else login_body
                )
            except AuthenticationError:
                csrf_after = self._session_csrf()

            self._log_info("Authentication successful")
            await self._ensure_batch_ids(csrf_after)

        except (TimeoutError, aiohttp.ClientError) as error:
            raise AuthenticationError(
                f"Network error during authentication: {error}"
            ) from error
        except AuthenticationError:
            raise
        except Exception as error:
            raise AuthenticationError(f"Authentication failed: {error}") from error

    async def _fetch_https_fallback_html(self, url: str) -> str | None:
        """Fetch an ``http://`` landing URL over ``https://``.

        The server redirects some landing URLs to ``http``; the ``http``
        variant 404s.

        Args:
            url: URL of the initial response.

        Returns:
            The HTTPS response body when its status is below 400,
            otherwise None.
        """
        if not url.startswith("http://"):
            return None
        try:
            session = await self._get_session()
            alt = "https://" + url.split("://", 1)[1]
            self._log_debug(f"Retrying landing URL with https: {alt}")
            async with session.get(alt) as landing_response:
                self._log_debug(
                    f"Landing fetch status: {landing_response.status} "
                    f"url={landing_response.url}"
                )
                if landing_response.status < 400:
                    return await landing_response.text()
        except (TimeoutError, aiohttp.ClientError):
            pass
        return None

    async def _ensure_batch_ids(self, csrf_token: str | None) -> None:
        """Auto-discover batch class ids when none are configured.

        Args:
            csrf_token: CSRF token for the semesters endpoint. Discovery is
                skipped silently when falsy.
        """
        if self.batch_class_ids or not csrf_token:
            return
        try:
            ids, texts = await self._fetch_semester_batch_ids(csrf_token)
            if ids:
                self._auto_discovered_batch_ids = ids
                self.sem_texts = texts
                self.batch_class_ids = ids if len(ids) > 1 else ids[0]
                self._log_info(
                    f"Auto-discovered batchClassId(s): {self.batch_class_ids}"
                )
        except Exception as error:  # noqa: BLE001 - failure leaves batch_class_ids unset
            self._log_debug(f"Auto-discovery of batchClassId failed: {error}")

    async def logout(self) -> None:
        """Request server-side session termination.

        :mod:`aiohttp` and timeout failures are logged at WARNING instead
        of propagating.
        """
        try:
            session = await self._get_session()
            async with session.get(f"{self.BASE_URL}/logout"):
                pass
            self._log_info("Session terminated successfully")
        except (TimeoutError, aiohttp.ClientError) as error:
            self._log_warning(f"Error during logout: {error}")

    async def close(self) -> None:
        """Log out, then close the HTTP session and detach it.

        The session reference is detached even if logout fails. Network
        and timeout failures do not propagate beyond :meth:`logout`.
        Anything else propagates after detachment.
        """
        try:
            if self._session is not None:
                await self.logout()
        finally:
            session, self._session = self._session, None
            if session is not None and not session.closed:
                await session.close()

    async def _prepare_profile_context(self, initial_html: str | None = None) -> str:
        """Prepare the student profile context on the server.

        Args:
            initial_html: Optional already-fetched profile page body to
                reuse, avoiding an extra network call.

        Returns:
            CSRF token to use for subsequent AJAX requests.

        Raises:
            AuthenticationError: If no CSRF token is available.
        """
        profile_url = f"{self.BASE_URL}/s/studentProfilePESU"
        session = await self._get_session()

        if initial_html is not None:
            html = initial_html
        else:
            try:
                async with session.get(profile_url) as response:
                    response.raise_for_status()
                    html = await response.text()
            except aiohttp.ClientResponseError as error:
                cookies = self._cookie_dict()
                if "JSESSIONID" in cookies or "SESSION" in cookies:
                    self._log_debug(
                        "Fetching profile returned error but session cookie is "
                        "present. Retrying once."
                    )
                    async with session.get(profile_url) as response:
                        response.raise_for_status()
                        html = await response.text()
                else:
                    raise AuthenticationError(
                        f"Failed to prepare profile context: {error}"
                    ) from error

        try:
            html_csrf: str | None = self._extract_csrf_token(html)
        except AuthenticationError:
            html_csrf = None

        csrf_token = html_csrf or self._session_csrf()
        if not csrf_token:
            raise AuthenticationError(
                "Missing CSRF token before fetching profile. "
                "Expected an HTML or cookie-based token."
            )

        headers = {
            "X-Requested-With": "XMLHttpRequest",
            "X-CSRF-Token": csrf_token,
            "Content-Type": "application/x-www-form-urlencoded",
            "Referer": profile_url,
        }

        try:
            async with session.get(
                f"{self.BASE_URL}/s/studentProfile/getStudentSemestersPESU",
                params={"_": int(time.time() * 1000)},
                headers=headers,
            ) as semesters_response:
                semesters_response.raise_for_status()
        except (TimeoutError, aiohttp.ClientError):
            self._log_debug("Semesters fetch failed. Continuing anyway.")

        return csrf_token

    async def get_semester_options(self) -> dict[int, str] | None:
        """Fetch available semesters as an id-to-label mapping.

        Requires an authenticated session. Call :meth:`login` first.

        Returns:
            Mapping of batch id to semester label, or None when unavailable.
        """
        _, texts = await self._fetch_semester_batch_ids(
            await self._prepare_profile_context()
        )
        return texts

    async def _fetch_semester_batch_ids(
        self, csrf_token: str
    ) -> tuple[list[int] | None, dict[int, str] | None]:
        """Fetch semester options and extract batch class ids.

        Args:
            csrf_token: CSRF token for the semesters endpoint.

        Returns:
            Tuple of (batch id list or None, id-to-label mapping or None).
            The response may be HTML ``<option>`` tags or a JSON list.
        """
        url = f"{self.BASE_URL}/s/studentProfile/getStudentSemestersPESU"
        headers = {
            "X-Requested-With": "XMLHttpRequest",
            "X-CSRF-Token": csrf_token,
            "Content-Type": "application/x-www-form-urlencoded",
            "Referer": f"{self.BASE_URL}/s/studentProfilePESU",
        }
        try:
            session = await self._get_session()
            async with session.get(
                url,
                params={"_": int(time.time() * 1000)},
                headers=headers,
            ) as response:
                response.raise_for_status()
                self._log_debug(
                    "Semester response content-type: "
                    f"{response.headers.get('content-type')}"
                )
                body = await response.text()
            soup = BeautifulSoup(body, "html.parser")
            options = soup.find_all("option")
            self._log_debug(f"Found {len(options)} option tags in semester response")
            values: list[int] = []
            texts: dict[int, str] = {}
            if options:
                for opt in options:
                    val = opt.get("value")
                    text = opt.get_text(strip=True)
                    self._log_debug(f"Option value: {val}, text: {text}")
                    batch_id = self._parse_batch_id(val)
                    if batch_id is not None:
                        values.append(batch_id)
                        texts[batch_id] = text
            else:
                # The endpoint sometimes returns JSON instead of HTML.
                try:
                    payload: Any = json.loads(body)
                    self._log_debug(f"Parsed semester payload as JSON: {payload}")
                    if isinstance(payload, list):
                        entries = cast("list[Any]", payload)
                        for item in entries:
                            if not isinstance(item, dict):
                                continue
                            entry = cast("dict[Any, Any]", item)
                            batch_id = self._parse_batch_id(entry.get("value"))
                            if batch_id is not None:
                                values.append(batch_id)
                                texts[batch_id] = str(
                                    entry.get("text", entry.get("label", ""))
                                )
                except ValueError as error:
                    self._log_debug(
                        f"Could not parse semester payload as JSON: {error}"
                    )
            self._log_debug(f"Available semesters: {texts}")
            return (values if values else None, texts if texts else None)
        except (TimeoutError, aiohttp.ClientError) as error:
            self._log_debug(f"Failed to fetch semester batch ids: {error}")
            return (None, None)

    @staticmethod
    def _parse_batch_id(value: Any) -> int | None:
        """Extract a numeric batch id from an option value.

        Args:
            value: Raw option value (may contain quotes or prefixes).

        Returns:
            Parsed integer id, or None when the value has no digits.
        """
        if value is None:
            return None
        digits = "".join(filter(str.isdigit, str(value)))
        if not digits:
            return None
        try:
            return int(digits)
        except ValueError:
            return None

    async def scrape_attendance_data(self) -> list[list[str]] | None:
        """Scrape attendance rows across all known batch class ids.

        Returns:
            List of raw table rows (each a list of cell strings), or None
            when no data could be retrieved.

        Raises:
            AttendanceScrapingError: If scraping fails unexpectedly.
        """
        self._log_debug(
            f"Starting attendance data scraping for branch: {self.branch_prefix}"
        )

        try:
            csrf_token = await self._prepare_profile_context()
            await self._ensure_batch_ids(csrf_token)

            if not self.batch_class_ids:
                self._log_warning(
                    "No batchClassId configured and auto-discovery failed. "
                    "Cannot fetch attendance."
                )
                return None

            for batch_id in self._normalize_batch_ids(self.batch_class_ids):
                attendance_data = await self._fetch_attendance_for_batch(
                    batch_id, csrf_token
                )
                if attendance_data:
                    self._log_info(
                        "Successfully retrieved attendance data for "
                        f"batch ID: {batch_id}"
                    )
                    return attendance_data

            self._log_warning(
                "No attendance data found for any configured batch class ID"
            )
            return None

        except Exception as error:
            raise AttendanceScrapingError(
                f"Failed to scrape attendance data: {error}"
            ) from error

    @staticmethod
    def _normalize_batch_ids(batch_ids: int | list[int]) -> list[str]:
        """Normalize configured batch ids to a list of strings.

        Args:
            batch_ids: Single id or list of ids.

        Returns:
            List of stringified batch ids.
        """
        if isinstance(batch_ids, list):
            return [str(batch_id) for batch_id in batch_ids]
        return [str(batch_ids)]

    async def _fetch_attendance_for_batch(
        self, batch_id: str, csrf_token: str
    ) -> list[list[str]] | None:
        """Fetch and parse the attendance table for one batch id.

        Args:
            batch_id: Batch class id to query.
            csrf_token: CSRF token for the admin endpoint.

        Returns:
            Parsed attendance rows, or None on HTTP/network failure.
        """
        attendance_url = f"{self.BASE_URL}/s/studentProfilePESUAdmin"

        request_payload = {
            "controllerMode": self.controller_mode,
            "actionType": self.action_type,
            "menuId": self.menu_id,
            "batchClassId": batch_id,
            "_csrf": csrf_token,
        }

        headers = {
            "X-Requested-With": "XMLHttpRequest",
            "X-CSRF-Token": csrf_token,
            "Content-Type": "application/x-www-form-urlencoded",
            "Referer": f"{self.BASE_URL}/s/studentProfilePESU",
        }

        try:
            session = await self._get_session()
            async with session.post(
                attendance_url, data=request_payload, headers=headers
            ) as response:
                if response.status != 200:
                    response_url = str(response.url)
                    self._log_debug(
                        f"Attendance POST status={response.status} url={response_url}"
                    )
                    self._log_debug(f"Session cookies: {self._cookie_dict()}")
                    # Retry over HTTPS when the server redirected to plain HTTP.
                    try:
                        if response_url.startswith("http://"):
                            alt = "https://" + response_url.split("://", 1)[1]
                            self._log_debug(
                                f"Retrying attendance URL with https: {alt}"
                            )
                            async with session.post(
                                alt, data=request_payload, headers=headers
                            ) as alt_response:
                                if alt_response.status == 200:
                                    return self._parse_attendance_table(
                                        await alt_response.text()
                                    )
                    except (TimeoutError, aiohttp.ClientError):
                        pass

                    self._log_error(
                        f"HTTP {response.status} error for batch ID {batch_id}"
                    )
                    return None

                return self._parse_attendance_table(await response.text())

        except (TimeoutError, aiohttp.ClientError) as error:
            self._log_error(
                f"Network error fetching data for batch ID {batch_id}: {error}"
            )
            return None

    def _parse_attendance_table(self, html_content: str) -> list[list[str]] | None:
        """Parse the attendance HTML table into raw rows.

        Args:
            html_content: Raw HTML of the admin endpoint response.

        Returns:
            List of valid attendance rows, or None when no table/rows exist.
        """
        soup = BeautifulSoup(html_content, "html.parser")
        attendance_table = soup.find("table", {"class": "table"})

        if not attendance_table:
            self._log_warning("No attendance table found in response")
            return None

        table_body = attendance_table.find("tbody")
        if not table_body:
            self._log_warning("No table body found in attendance table")
            return None

        attendance_records: list[list[str]] = []
        for row in table_body.find_all("tr"):
            row_data = self._extract_row_data(row)
            if row_data and self._is_valid_attendance_record(row_data):
                attendance_records.append(row_data)

        return attendance_records if attendance_records else None

    @staticmethod
    def _extract_row_data(table_row: Tag) -> list[str]:
        """Extract stripped cell texts from a table row.

        Args:
            table_row: BeautifulSoup ``<tr>`` tag.

        Returns:
            List of cell texts.
        """
        return [cell.get_text(strip=True) for cell in table_row.find_all("td")]

    def _is_valid_attendance_record(self, row_data: list[str]) -> bool:
        """Predicate: row holds a usable attendance record.

        Rows with ``'NA'`` numeric columns satisfy the predicate. Only rows
        with fewer than 2 cells or an empty subject code do not.

        Args:
            row_data: Raw row cells.

        Returns:
            True when the row has a non-empty subject code.
        """
        if len(row_data) < 2:
            return False

        if not row_data[0] or not row_data[0].strip():
            return False

        if len(row_data) > 2 and row_data[2].strip().upper() == "NA":
            self._log_debug(
                f"Attendance entry contains 'NA' but will be included: {row_data}"
            )

        return True


async def fetch_student_attendance(
    username: str,
    password: str,
    batch_id: int | None = None,
) -> tuple[list[list[str]] | None, PESUAttendanceScraper]:
    """Fetch attendance rows for a student, returning the scraper for context.

    Args:
        username: PESU Academy username (SRN).
        password: PESU Academy password.
        batch_id: Optional explicit batch class id.

    Returns:
        Tuple of (attendance rows or None, configured scraper). The scraper
        exposes auto-discovered batch ids and the subject mapping.
    """
    scraper = PESUAttendanceScraper(username, password, batch_id)

    try:
        await scraper.login()
        return await scraper.scrape_attendance_data(), scraper
    finally:
        await scraper.close()


class AttendanceRequest(BaseModel):
    """Validated request body for ``POST /api/attendance``.

    Attributes:
        username: PESU Academy username (SRN).
        password: PESU Academy password.
        batch_id: Optional explicit batch class id.
    """

    username: str = Field(min_length=1, description="PESU Academy username (SRN)")
    password: str = Field(min_length=1, description="PESU Academy password")
    batch_id: int | None = Field(default=None, description="Explicit batch class id")


class SemesterRequest(BaseModel):
    """Validated request body for ``POST /api/semesters``.

    Attributes:
        username: PESU Academy username (SRN).
        password: PESU Academy password.
    """

    username: str = Field(min_length=1, description="PESU Academy username (SRN)")
    password: str = Field(min_length=1, description="PESU Academy password")


class AttendanceRecord(BaseModel):
    """Formatted attendance entry for a single subject.

    Attributes:
        subject: Display name of the subject.
        course_name: Raw course name from PESU Academy, if available.
        total_classes: Total classes held, or None when reported as ``NA``.
        percentage: Attendance percentage, or None when reported as ``NA``.
        raw_data: Raw total-classes cell value from the scraped table.
    """

    subject: str
    course_name: str | None = None
    total_classes: int | None = None
    percentage: float | None = None
    raw_data: str | None = None


def _coerce_int(value: str | None) -> int | None:
    """Coerce a scraped cell to int, mapping ``'NA'`` to None.

    Args:
        value: Raw cell text.

    Returns:
        Parsed integer or None when absent/unparseable.
    """
    if not value:
        return None
    text = value.strip()
    if text.upper() == "NA":
        return None
    match = re.search(r"(\d+)", text)
    return int(match.group(1)) if match else None


def _coerce_float(value: str | None) -> float | None:
    """Coerce a scraped cell to float, mapping ``'NA'`` to None.

    Args:
        value: Raw cell text (may include a ``%`` suffix).

    Returns:
        Parsed float or None when absent/unparseable.
    """
    if not value:
        return None
    text = value.strip().replace("%", "")
    if text.upper() == "NA":
        return None
    try:
        return float(text)
    except ValueError:
        match = re.search(r"(\d+(?:\.\d+)?)", text)
        return float(match.group(1)) if match else None


def format_attendance_data(
    attendance_data: list[list[str]], subject_mapping: dict[str, str]
) -> list[dict[str, Any]]:
    """Normalize raw scraped rows into client-friendly dictionaries.

    Args:
        attendance_data: Raw rows from :meth:`PESUAttendanceScraper.scrape_attendance_data`.
        subject_mapping: Mapping of raw subject codes to display names.

    Returns:
        List of formatted attendance dicts with ``subject``, ``course_name``,
        ``total_classes``, ``percentage`` and ``raw_data`` keys.
    """
    formatted_attendance: list[dict[str, Any]] = []

    for item in attendance_data:
        if len(item) < 1:
            continue

        subject_code = item[0]
        course_name = item[1] if len(item) > 1 else None
        raw_total = item[2] if len(item) > 2 else None
        raw_percentage = item[3] if len(item) > 3 else None

        total_classes = _coerce_int(raw_total)
        percentage = _coerce_float(raw_percentage)

        if (
            total_classes is None
            and isinstance(raw_total, str)
            and raw_total.strip().upper() == "NA"
        ):
            app_logger.debug(
                f"Normalized 'NA' total_classes for subject {subject_code}"
            )

        formatted_attendance.append(
            AttendanceRecord(
                subject=subject_mapping.get(subject_code, subject_code),
                course_name=course_name,
                total_classes=total_classes,
                percentage=percentage,
                raw_data=raw_total,
            ).model_dump()
        )

    return formatted_attendance


async def process_attendance_task(
    username: str, password: str, batch_id: int | None = None
) -> dict[str, Any]:
    """Fetch, format and return attendance data for a student.

    Fully asynchronous end to end. Safe to await directly from async routes.

    Args:
        username: PESU Academy username (SRN).
        password: PESU Academy password.
        batch_id: Optional explicit batch class id.

    Returns:
        Result dict with ``status``, ``attendance`` and optionally
        ``discovered_batch_ids``.

    Raises:
        AuthenticationError: If login fails.
        AttendanceScrapingError: If no attendance data is retrieved.
    """
    try:
        app_log(
            "fetch.start", f"Starting attendance processing for SRN: {username[:10]}"
        )

        attendance_data, used_scraper = await fetch_student_attendance(
            username, password, batch_id
        )

        if not attendance_data:
            raise AttendanceScrapingError("No attendance data retrieved")

        app_log("fetch.formatting", "Formatting attendance data")

        formatted_attendance = format_attendance_data(
            attendance_data, used_scraper.subject_mapping
        )

        result: dict[str, Any] = {
            "status": "complete",
            "attendance": formatted_attendance,
        }

        if used_scraper.auto_discovered_batch_ids:
            result["discovered_batch_ids"] = [
                str(batch_id) for batch_id in used_scraper.auto_discovered_batch_ids
            ]

        app_log("fetch.complete", "Attendance processing completed successfully")

        return result

    except (AuthenticationError, AttendanceScrapingError) as error:
        app_log(
            "error.attendance_processing",
            f"Attendance processing error: {error}",
            "error",
        )
        raise
    except Exception as error:
        app_log(
            "error.unexpected", f"Unexpected error during processing: {error}", "error"
        )
        raise


# Initialize configuration and logger at import time so serverless
# environments (e.g. Vercel's `main:app`) work without a factory call.
try:
    mappings = load_mappings_config()
    settings = load_app_settings()
    app_logger = setup_logger()

    def app_log(key: str, message: str | None = None, level: str = "info") -> None:
        """Record an event-keyed log line.

        Emits ``[key] message`` at the given level and attaches
        ``event=key`` to the record so structured sinks index it.

        Args:
            key: Machine-readable event key (e.g. ``"fetch.start"``).
            message: Human-readable detail. Defaults to the key itself.
            level: One of ``"debug"``, ``"warning"``, ``"error"`` or ``"info"``.
                Unknown values fall back to ``"info"``.
        """
        msg = f"[{key}] {message or key}"
        extra = {"event": key}
        if level == "debug":
            app_logger.debug(msg, extra=extra)
        elif level == "warning":
            app_logger.warning(msg, extra=extra)
        elif level == "error":
            app_logger.error(msg, extra=extra)
        else:
            app_logger.info(msg, extra=extra)

except ConfigurationError as error:
    raise ConfigurationError(f"Failed to initialize configuration: {error}") from error

app = FastAPI(
    title="PESU Academy Attendance Tracker",
    description="Fetch and analyze student attendance data from PESUAcademy",
    version="1.0.0",
)
app.add_middleware(GZipMiddleware, minimum_size=1000)
router = APIRouter()


def _build_sha() -> str:
    """Short commit SHA of the running build.

    Returns:
        First 7 characters of ``VERCEL_GIT_COMMIT_SHA``, or ``"local"``
        outside Vercel.
    """
    return (os.getenv("VERCEL_GIT_COMMIT_SHA") or "local")[:7]


@router.get("/healthcheck")
async def healthcheck() -> dict[str, Any]:
    """Report service health.

    Returns:
        Success envelope with ``{"status": "healthy"}``. Carries the
        running build SHA so deployments are fingerprinted.
    """
    return APIResponse.success(
        data={"status": "healthy", "build": _build_sha()},
        code="healthcheck_ok",
        message="Service is healthy and operational",
    )


@router.post("/attendance")
async def get_attendance(payload: AttendanceRequest) -> dict[str, Any]:
    """Fetch formatted attendance for a student.

    Natively async: the scrape pipeline uses non-blocking I/O throughout.

    Args:
        payload: Validated attendance request body.

    Returns:
        Success envelope wrapping the attendance result.

    Raises:
        HTTPException: 401 on auth failure, 500 on config/scraping errors.
    """
    try:
        result = await process_attendance_task(
            payload.username, payload.password, payload.batch_id
        )

        return APIResponse.success(
            data=result,
            code="attendance_retrieved",
            message=f"Attendance data retrieved for {payload.username}",
        )

    except ConfigurationError as error:
        app_log("error.config", f"Configuration error: {error}", "error")
        raise http_error("ConfigurationError", str(error), "config_error", 500)
    except AuthenticationError as error:
        app_log("auth.failed", f"Authentication failed: {error}", "warning")
        raise http_error("AuthenticationError", str(error), "auth_failed", 401)
    except AttendanceScrapingError as error:
        app_log("error.scraping", f"Scraping error: {error}", "error")
        raise http_error("ScrapingError", str(error), "scraping_failed", 500)
    except Exception as error:  # noqa: BLE001 - intentional catch-all mapping to 500
        app_log("error.unexpected", f"Unexpected error: {error}", "error")
        raise http_error("UnexpectedError", str(error), "internal_error", 500)


@router.post("/semesters")
async def get_semesters(payload: SemesterRequest) -> dict[str, Any]:
    """List available semesters (batch ids) for a student.

    Natively async: the scraper uses non-blocking I/O throughout.

    Args:
        payload: Validated semester request body.

    Returns:
        Success envelope wrapping ``{"semesters": ...}``.

    Raises:
        HTTPException: 500 when semester discovery fails.
    """
    try:
        scraper = PESUAttendanceScraper(payload.username, payload.password)
        try:
            await scraper.login()
            texts = await scraper.get_semester_options()
            return APIResponse.success(
                data={"semesters": texts},
                code="semesters_retrieved",
                message=f"Available semesters retrieved for {payload.username}",
            )
        finally:
            await scraper.close()

    except Exception as error:  # noqa: BLE001 - intentional catch-all mapping to 500
        app_log(
            "semester.fetch_error",
            f"Error fetching semesters for {payload.username}: {error}",
            "error",
        )
        raise http_error("SemesterError", str(error), "semesters_failed", 500)


app.include_router(router, prefix="/api")


@app.get("/mapping.json", include_in_schema=False)
async def serve_mapping_json() -> JSONResponse:
    """Serve the authoritative ``mapping.json`` for frontend requests.

    Returns:
        JSON response with the mapping contents, or a standardized error
        payload when the file is missing or invalid.
    """
    config_path = REPO_ROOT / FRONTEND_WEB_DIR / "mapping.json"
    try:
        with config_path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        return JSONResponse(content=data, status_code=200)
    except FileNotFoundError:
        payload, status_code = APIResponse.error(
            error_type="NotFound",
            details="mapping.json not found at 'frontend/web/mapping.json'",
            code="mapping_missing",
            status_code=404,
        )
        return JSONResponse(content=payload, status_code=status_code)
    except json.JSONDecodeError as error:
        payload, status_code = APIResponse.error(
            error_type="ConfigError",
            details=f"Invalid mapping.json: {error}",
            code="mapping_invalid",
            status_code=500,
        )
        return JSONResponse(content=payload, status_code=status_code)


def _cached_js_response(filename: str) -> FileResponse:
    """Build a long-cached JavaScript file response.

    Args:
        filename: File name under ``frontend/web``.

    Returns:
        File response with immutable caching headers.

    Raises:
        HTTPException: 404 when the file does not exist.
    """
    file_path = REPO_ROOT / FRONTEND_WEB_DIR / filename
    if not file_path.exists():
        raise HTTPException(status_code=404, detail=f"{filename} not found")

    return FileResponse(
        path=file_path,
        media_type="application/javascript",
        headers={"Cache-Control": IMMUTABLE_JS_CACHE_CONTROL},
    )


@app.get("/chart.min.js", include_in_schema=False)
async def serve_chart_js() -> FileResponse:
    """Serve the cached Chart.js bundle.

    Returns:
        Immutable-cached JavaScript response.
    """
    return _cached_js_response("chart.min.js")


@app.get("/i.js", include_in_schema=False)
async def serve_i_js() -> FileResponse:
    """Serve the cached ``i.js`` bundle.

    Returns:
        Immutable-cached JavaScript response.
    """
    return _cached_js_response("i.js")


if settings.ENABLE_BACKEND_WEB:
    app.mount(
        "/",
        StaticFiles(directory=REPO_ROOT / FRONTEND_WEB_DIR, html=True),
        name="frontend",
    )
else:
    app_log(
        "config.frontend_disabled",
        "Frontend static files mount disabled (ENABLE_BACKEND_WEB=false)",
    )

    @app.get("/", include_in_schema=False)
    async def frontend_disabled_root() -> JSONResponse:
        """Explain that the web frontend is disabled.

        Returns:
            Standardized ``FeatureDisabled`` error payload (404).
        """
        payload, status_code = APIResponse.error(
            error_type="FeatureDisabled",
            details=FRONTEND_DISABLED_DETAILS,
            code="frontend_disabled",
            status_code=404,
        )
        return JSONResponse(content=payload, status_code=status_code)

    @app.get("/{full_path:path}", include_in_schema=False)
    async def frontend_disabled_catchall(full_path: str) -> JSONResponse:
        """Catch all non-API paths when the frontend is disabled.

        Args:
            full_path: Unmatched request path.

        Returns:
            ``NotFound`` for reserved API/doc paths, otherwise a
            ``FeatureDisabled`` error payload.
        """
        if full_path.startswith(("api", "docs", "openapi.json", "redoc")):
            payload, status_code = APIResponse.error(
                error_type="NotFound",
                details=f"Path '/{full_path}' not found",
                code="not_found",
                status_code=404,
            )
            return JSONResponse(content=payload, status_code=status_code)

        payload, status_code = APIResponse.error(
            error_type="FeatureDisabled",
            details=FRONTEND_DISABLED_DETAILS,
            code="frontend_disabled",
            status_code=404,
        )
        return JSONResponse(content=payload, status_code=status_code)


def _launch_telegram_bot() -> subprocess.Popen[bytes] | None:
    """Launch the Telegram bot as a detached subprocess when enabled.

    Returns:
        The bot subprocess handle, or None when the bot is disabled or its
        script is missing. Exits the process when the token is misconfigured.
    """
    if not settings.ENABLE_BACKEND_TELEGRAM:
        return None

    telegram_bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not telegram_bot_token:
        print(
            "ERROR: ENABLE_BACKEND_TELEGRAM is enabled but TELEGRAM_BOT_TOKEN "
            "is not set in .env"
        )
        print(
            "Please add TELEGRAM_BOT_TOKEN to your .env file or disable the Telegram bot."
        )
        sys.exit(1)

    tg_bot_path = REPO_ROOT / "frontend" / "telegram" / "tg_bot.py"
    if not tg_bot_path.exists():
        print(f"Telegram bot file not found at: {tg_bot_path}, skipping bot start")
        return None

    bot_proc = subprocess.Popen(
        [sys.executable, str(tg_bot_path)],
        env=os.environ.copy(),
        start_new_session=True,
    )

    def _terminate_bot() -> None:
        _terminate_process(bot_proc)

    atexit.register(_terminate_bot)
    print(f"Started telegram bot subprocess (pid={bot_proc.pid})")
    return bot_proc


def _terminate_process(proc: subprocess.Popen[bytes] | None) -> None:
    """Terminate a subprocess gracefully, escalating to kill on failure.

    Args:
        proc: Subprocess handle or None (no-op).
    """
    if proc is None or proc.poll() is not None:
        return
    try:
        proc.terminate()
        proc.wait(timeout=5)
    except (OSError, subprocess.SubprocessError):
        try:
            proc.kill()
        except (OSError, subprocess.SubprocessError):
            pass


def _wait_for_bot(bot_proc: subprocess.Popen[bytes] | None) -> None:
    """Block until the bot-only subprocess exits.

    Args:
        bot_proc: Bot subprocess handle or None (no-op).
    """
    if bot_proc is None:
        return
    print("Running in bot-only mode. Press Ctrl+C to exit.")
    try:
        bot_proc.wait()
    except KeyboardInterrupt:
        print("\nShutting down...")


def _uvicorn_log_config() -> dict[str, Any]:
    """Build the uvicorn logging config using the application formatters.

    Args:
        None.

    Returns:
        ``logging.config.dictConfig`` mapping that routes the ``uvicorn``,
        ``uvicorn.error`` and ``uvicorn.access`` loggers through the same
        sink format selected by :func:`_select_log_format`.
    """
    use_json, use_color = _select_log_format()
    level = os.getenv("LOG_LEVEL", "INFO").upper()
    formatter: dict[str, Any] = (
        {"()": "main.JsonFormatter"}
        if use_json
        else {"()": "main.TextFormatter", "color": use_color}
    )
    return {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {"app": formatter},
        "handlers": {
            "app": {
                "class": "logging.StreamHandler",
                "stream": "ext://sys.stderr",
                "formatter": "app",
            },
        },
        "loggers": {
            "uvicorn": {"handlers": ["app"], "level": level, "propagate": False},
            "uvicorn.error": {
                "handlers": ["app"],
                "level": level,
                "propagate": False,
            },
            "uvicorn.access": {
                "handlers": ["app"],
                "level": level,
                "propagate": False,
            },
        },
    }


def run(argv: list[str] | None = None) -> None:
    """Run the application server and optional Telegram bot subprocess.

    Args:
        argv: CLI argument list. Parsed and ignored. No flags are defined.
    """
    parser = argparse.ArgumentParser()
    parser.parse_args(argv)

    bot_proc: subprocess.Popen[bytes] | None = None
    try:
        bot_proc = _launch_telegram_bot()

        if settings.ENABLE_BACKEND_API:
            if settings.ENABLE_BACKEND_WEB:
                print(f"Starting web + API server on port {settings.PORT}...")
            else:
                print(
                    f"Starting API server (frontend disabled) on port {settings.PORT}..."
                )
            uvicorn.run(
                "main:app",
                host="0.0.0.0",
                port=settings.PORT,
                reload=settings.DEBUG,
                log_config=_uvicorn_log_config(),
            )
        else:
            print("API server disabled (ENABLE_BACKEND_API set to false)")
            _wait_for_bot(bot_proc)
    finally:
        _terminate_process(bot_proc)


if __name__ == "__main__":
    run()
