#!/usr/bin/env python3
"""
Main entrypoint for the PESU Attendance Tracker.

Run with environment toggles to choose which components start:
 - ENABLE_BACKEND_API: start API (defaults to true)
 - ENABLE_BACKEND_WEB: mount & serve static frontend (defaults to true)
 - ENABLE_BACKEND_TELEGRAM: launch the telegram bot as a subprocess (defaults to false)

Examples:
    # Run API and bot, but do not serve frontend
    export ENABLE_BACKEND_WEB=false
    export ENABLE_BACKEND_TELEGRAM=true
    uv run main.py
"""
import os
import re
import json
import logging
import time
from pathlib import Path
from typing import Dict, List, Optional, Union, Any

import uvicorn
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin
from fastapi import FastAPI, APIRouter, HTTPException, status, Body
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse
from dataclasses import dataclass
import subprocess
import atexit
import sys


class APIResponse:
    """Standardized API response wrapper for all clients (web, bot, CLI, etc.)"""

    @staticmethod
    def success(
        data: Any, code: str = "success", message: str = "Operation successful"
    ) -> Dict[str, Any]:
        """Return standardized success response"""
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
    ) -> tuple[Dict[str, Any], int]:
        """Return standardized error response with HTTP status"""
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


# ============================================================================
# CONFIGURATION AND SETTINGS
# ============================================================================


class ConfigurationError(Exception):
    """Raised when configuration loading or validation fails."""

    pass


@dataclass
class MappingsData:
    controller_mode: int
    action_type: int
    menu_id: int
    batchClassId: Optional[Union[int, List[int]]]
    subject_mapping: Dict[str, str]


class MappingsConfig:
    def __init__(self, config: Dict[str, Any]):
        self.CONTROLLER_MODE = config.get("CONTROLLER_MODE")
        self.ACTION_TYPE = config.get("ACTION_TYPE")
        self.MENU_ID = config.get("MENU_ID")
        self.BATCH_CLASS_ID_MAPPING = config.get("BATCH_CLASS_ID_MAPPING", {})
        self.SUBJECT_MAPPING = config.get("SUBJECT_MAPPING", {})

    def get_branch_config(self, srn: str) -> MappingsData:
        # Build a dynamic regex from configured batch keys so SRN validation
        # stays in sync with `BATCH_CLASS_ID_MAPPING` in mapping.json.
        keys = list(self.BATCH_CLASS_ID_MAPPING.keys())

        # Normalize keys to remove leading 'PES' for pattern building
        normalized = []
        for k in keys:
            if k.startswith("PES"):
                normalized.append(k[3:])
            else:
                normalized.append(k)

        # Group by batch prefix (first 5 chars, e.g. '2UG23') and collect branches
        groups = {}
        for token in normalized:
            batch = token[:5]
            branch = token[5:]
            groups.setdefault(batch, set())
            if branch:
                groups[batch].add(branch)

        parts = []
        for batch, branch_set in groups.items():
            if not branch_set:
                parts.append(batch)
            else:
                branches = sorted(branch_set)
                if len(branches) == 1:
                    parts.append(f"{batch}{branches[0]}")
                else:
                    parts.append(f"{batch}(?:{'|'.join(branches)})")

        # If no mappings were configured, skip strict SRN validation and
        # allow runtime discovery of batchClassId after authentication.
        if not parts:
            # No configured parts to validate against — proceed permissively.
            pattern = None
        else:
            pattern = rf"^PES(?:{'|'.join(parts)})\d{{3}}$"
            # Only enforce validation when we have a meaningful pattern.
            if not re.match(pattern, srn):
                try:
                    app_logger.debug(
                        f"SRN '{srn}' does not match configured validation pattern; proceeding permissively"
                    )
                except Exception:
                    pass
                # Do not raise; allow lookup to proceed and rely on runtime discovery.

        # Determine the exact mapping key by checking which configured key the SRN starts with
        full_prefix = None
        for k in keys:
            if srn.startswith(k):
                full_prefix = k
                break

        # If the mapping key is not present or its configured value is missing,
        # do not raise an error here. We will attempt to discover the
        # appropriate batchClassId dynamically after authentication.
        if full_prefix is None:
            batch_class_id = None
        else:
            batch_class_id = self.BATCH_CLASS_ID_MAPPING.get(full_prefix)

        return MappingsData(
            controller_mode=self.CONTROLLER_MODE,
            action_type=self.ACTION_TYPE,
            menu_id=self.MENU_ID,
            batchClassId=batch_class_id,
            subject_mapping=self.SUBJECT_MAPPING,
        )


class AppSettings:
    def __init__(self):
        try:
            from dotenv import load_dotenv
            from pathlib import Path

            # Load .env.local if it exists, otherwise fall back to .env
            if Path(".env.local").exists():
                load_dotenv(".env.local")
            else:
                load_dotenv()
        except Exception:
            pass

        self.PORT = int(os.getenv("PORT", 10000))
        self.LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
        self.DEBUG = os.getenv("DEBUG", "False").lower() in ("1", "true", "yes")
        self.REQUEST_TIMEOUT_SECONDS = int(os.getenv("REQUEST_TIMEOUT_SECONDS", 5))
        # Backend feature toggles
        self.ENABLE_BACKEND_API = os.getenv("ENABLE_BACKEND_API", "true").lower() in (
            "1",
            "true",
            "yes",
        )
        self.ENABLE_BACKEND_WEB = os.getenv("ENABLE_BACKEND_WEB", "true").lower() in (
            "1",
            "true",
            "yes",
        )
        self.ENABLE_BACKEND_TELEGRAM = os.getenv(
            "ENABLE_BACKEND_TELEGRAM", "false"
        ).lower() in ("1", "true", "yes")


def load_mappings_config() -> MappingsConfig:
    repo_root = Path(__file__).resolve().parent
    web_config = repo_root / "frontend" / "web" / "mapping.json"

    try:
        if not web_config.exists():
            raise ConfigurationError(f"mapping.json file not found at: {web_config}.")

        try:
            with web_config.open("r", encoding="utf-8") as f:
                config_data = json.load(f)
        except json.JSONDecodeError as error:
            raise ConfigurationError(
                f"Invalid JSON format in configuration file: {error}"
            )

        return MappingsConfig(config_data)

    except ConfigurationError:
        raise
    except Exception as error:
        raise ConfigurationError(f"Failed to load configuration: {error}")


def load_app_settings() -> AppSettings:
    try:
        return AppSettings()
    except Exception as error:
        raise ConfigurationError(f"Failed to load application settings: {error}")


# ============================================================================
# LOGGING SETUP
# ============================================================================


def setup_logger(name=None, level=None, format_str=None):
    """Set up a logger with console output."""
    log_level = os.getenv("LOG_LEVEL", "INFO").upper()
    default_format = "%(asctime)s - %(levelname)s - %(message)s"

    logger = logging.getLogger(name)
    logger.setLevel(level or log_level)

    # Clear existing handlers to avoid duplicates
    if logger.hasHandlers():
        logger.handlers.clear()

    # Add console handler
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(logging.Formatter(format_str or default_format))
    logger.addHandler(console_handler)

    # Prevent propagation to root to avoid duplicate logs
    logger.propagate = False

    return logger


# ============================================================================
# PESU ACADEMY SCRAPER
# ============================================================================


class AuthenticationError(Exception):
    """Raised when authentication with PESU Academy fails."""

    pass


class AttendanceScrapingError(Exception):
    """Raised when attendance data scraping encounters an error."""

    pass


class PESUAttendanceScraper:
    BASE_URL = "https://www.pesuacademy.com/Academy"

    def __init__(self, username: str, password: str) -> None:
        self.session = requests.Session()
        # Provide browser-like defaults so the site responds with the same CSRF & cookies
        self.session.headers.update(
            {
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            }
        )
        self.username = username
        self.password = password

        try:
            # Load and configure branch-specific settings using new config system
            branch_config = mappings.get_branch_config(username)
            self.controller_mode = branch_config.controller_mode
            self.action_type = branch_config.action_type
            self.menu_id = branch_config.menu_id
            self.batch_class_ids = branch_config.batchClassId
            self.subject_mapping = branch_config.subject_mapping

            # Track whether batchClassId(s) were auto-discovered at runtime and
            # an optional suggestion message to ask the user to open a PR.
            self._auto_discovered_batch_ids: Optional[List[str]] = None
            self._pr_suggestion: Optional[str] = None

            # Extract branch prefix from username for logging
            # Derive a human-friendly branch prefix for logging by matching the
            # configured mapping keys (fall back to a slice of username).
            full_prefix = None
            for k in mappings.BATCH_CLASS_ID_MAPPING.keys():
                if username.startswith(k):
                    full_prefix = k
                    break

            if full_prefix:
                # strip leading 'PES' for compact display (e.g. '2UG23CS')
                self.branch_prefix = full_prefix[3:]
            else:
                self.branch_prefix = username[:10]

        except ValueError as e:
            raise ConfigurationError(f"Configuration error: {e}")

    def _extract_csrf_token(self, html_content: str) -> str:
        """
        Extract CSRF token from several possible locations:
        - <input name="_csrf" value="...">
        - <meta name="_csrf" content="..."> or common meta tokens
        - inline JS patterns or UUID-like tokens
        """
        soup = BeautifulSoup(html_content, "html.parser")

        # 1) standard hidden input
        csrf_input = soup.find("input", {"name": "_csrf"})
        if csrf_input and csrf_input.get("value"):
            return csrf_input.get("value")  # type: ignore

        # 2) meta tags
        for meta_name in ("_csrf", "csrf-token", "csrf"):
            m = soup.find("meta", {"name": meta_name})
            if m and m.get("content"):
                return m.get("content")  # type: ignore

        # 3) JS inline assignment e.g. _csrf = 'uuid' or "_csrf":"uuid"
        m = re.search(
            r"_csrf['\"]?\s*[:=]\s*['\"]([0-9a-fA-F-]{8,})['\"]", html_content
        )
        if m:
            return m.group(1)

        # 4) fallback: any UUID in page (common CSRF format observed)
        m2 = re.search(
            r"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})",
            html_content,
            re.I,
        )
        if m2:
            return m2.group(1)

        raise AuthenticationError("CSRF token not found in response")

    def login(self) -> None:
        app_logger.info("Initiating authentication process")

        try:
            # GET initial page (login landing) and gather cookies + form
            login_page_url = f"{self.BASE_URL}/"
            r0 = self.session.get(login_page_url, allow_redirects=True, timeout=15)
            r0.raise_for_status()

            soup = BeautifulSoup(r0.text, "html.parser")
            # Find the login form (heuristic: form containing j_username or username field)
            form = None
            for f in soup.find_all("form"):
                if f.find("input", {"name": "j_username"}) or f.find(
                    "input", {"name": "username"}
                ):
                    form = f
                    break

            action = None
            if form and form.get("action"):
                action = form.get("action")
            else:
                action = "/j_spring_security_check"

            if action.startswith("http"):
                login_url = action
            else:
                login_url = urljoin(self.BASE_URL + "/", action.lstrip("/"))

            # Gather form hidden inputs (preserve any extra required fields)
            form_inputs = {}
            if form:
                for inp in form.find_all("input"):
                    name = inp.get("name")
                    if not name:
                        continue
                    if name in ("j_username", "j_password"):
                        continue
                    form_inputs[name] = inp.get("value", "")

            # Determine CSRF to use for login (form value > page token > cookie > existing)
            form_csrf = form_inputs.get("_csrf")
            page_csrf = None
            try:
                page_csrf = self._extract_csrf_token(r0.text)
            except AuthenticationError:
                page_csrf = None

            if form_csrf:
                csrf_token = form_csrf
                csrf_source = "form"
            elif page_csrf:
                csrf_token = page_csrf
                csrf_source = "html"
            else:
                # cookie-based fallback
                csrf_token = self.session.cookies.get(
                    "XSRF-TOKEN"
                ) or self.session.cookies.get("CSRF-TOKEN")
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
                "Referer": r0.url,
                "Sec-GPC": "1",
            }

            app_logger.debug(f"Posting to {login_url} with csrf source={csrf_source}")
            resp = self.session.post(
                login_url,
                data=login_payload,
                headers=headers,
                allow_redirects=True,
                timeout=15,
            )

            app_logger.debug(
                f"Login POST status={getattr(resp, 'status_code', None)} url={getattr(resp, 'url', None)}"
            )
            app_logger.debug(
                f"Session cookies after login: {self.session.cookies.get_dict()}"
            )

            # Heuristic: server sometimes redirects to http landing (which returns 404); if final url uses http, try https equivalent
            final_resp = resp
            try:
                if getattr(resp, "url", "").startswith("http://"):
                    alt = "https://" + resp.url.split("://", 1)[1]
                    app_logger.debug(f"Retrying landing URL with https: {alt}")
                    landing_resp = self.session.get(
                        alt, allow_redirects=True, timeout=15
                    )
                    app_logger.debug(
                        f"Landing fetch status: {getattr(landing_resp, 'status_code', None)} url={getattr(landing_resp, 'url', None)}"
                    )
                    if landing_resp.status_code < 400:
                        final_resp = landing_resp
            except Exception:
                pass

            # Basic detection of failed login via presence of login form or error messages
            final_body = (final_resp.text or "").lower()
            if (
                "j_username" in final_body
                or "j_spring_security_check" in final_body
                or ("invalid" in final_body and "login" in final_body)
            ):
                raise AuthenticationError(
                    "Authentication failed: login page or error detected after POST"
                )

            # Prepare profile context and obtain a ready-to-use CSRF token (reuse final response to avoid extra GET)
            try:
                csrf_after = self._prepare_profile_context(initial_response=final_resp)
            except AuthenticationError:
                # Fall back to cookie if preparation failed
                csrf_after = self.session.cookies.get(
                    "XSRF-TOKEN"
                ) or self.session.cookies.get("CSRF-TOKEN")

            app_logger.info("Authentication successful")

            # If batch class IDs are not configured, attempt to auto-discover them
            # from the semesters endpoint used by the profile page.
            if not self.batch_class_ids:
                try:
                    fetched = self._fetch_semester_batch_ids(csrf_after)
                    if fetched:
                        # Record that these were auto-discovered so the API can
                        # surface a helpful suggestion to the user.
                        self._auto_discovered_batch_ids = fetched

                        # Use a single value when only one option is found, else keep the list
                        self.batch_class_ids = (
                            fetched if len(fetched) > 1 else fetched[0]
                        )

                        # Build a concise PR suggestion message that includes the
                        # SRN prefix (username with trailing digits removed) and the
                        # discovered batchClassId(s).
                        try:
                            prefix = re.sub(r"\d+$", "", self.username)
                            ids = ",".join(fetched)
                            msg = (
                                f"Auto-discovered batchClassId(s) for SRN prefix '{prefix}': {ids}. "
                                "Consider opening a PR to add this mapping to 'frontend/web/mapping.json' under 'BATCH_CLASS_ID_MAPPING'."
                            )
                            self._pr_suggestion = msg
                        except Exception:
                            self._pr_suggestion = (
                                f"Auto-discovered batchClassId(s): {fetched}. "
                                "Consider opening a PR to add this mapping to 'frontend/web/mapping.json'."
                            )

                        app_logger.info(
                            f"Auto-discovered batchClassId(s): {self.batch_class_ids}"
                        )
                        app_logger.info(self._pr_suggestion)
                except Exception as e:
                    app_logger.debug(f"Auto-discovery of batchClassId failed: {e}")

        except requests.RequestException as e:
            raise AuthenticationError(f"Network error during authentication: {e}")
        except Exception as e:
            raise AuthenticationError(f"Authentication failed: {e}")

    def _validate_authentication(self) -> None:
        profile_url = f"{self.BASE_URL}/s/studentProfilePESU"
        try:
            profile_response = self.session.get(
                profile_url, allow_redirects=True, timeout=15
            )
            app_logger.debug(
                f"Validate profile fetch status={profile_response.status_code} url={profile_response.url}"
            )

            if profile_response.status_code == 200:
                body = profile_response.text.lower()
                # Heuristics for successful login
                if (
                    "studentprofile" in body
                    or "logout" in body
                    or "/a/0" in profile_response.url
                ):
                    return
                # Detect login form indicating failed auth
                if re.search(r'name=["\']j_username["\']', body):
                    raise AuthenticationError(
                        "Authentication failed: login form detected after login"
                    )
                raise AuthenticationError(
                    "Authentication failed: unexpected profile response"
                )
            elif profile_response.status_code in (301, 302):
                raise AuthenticationError("Authentication failed: redirected to login")
            else:
                raise AuthenticationError(
                    f"Authentication failed: HTTP {profile_response.status_code}"
                )

        except requests.RequestException as e:
            raise AuthenticationError(f"Failed to validate authentication: {e}")

    def logout(self) -> None:
        try:
            logout_url = f"{self.BASE_URL}/logout"
            self.session.get(logout_url)
            app_logger.info("Session terminated successfully")
        except requests.RequestException as e:
            app_logger.warning(f"Error during logout: {e}")

    def _prepare_profile_context(
        self, initial_response: Optional[requests.Response] = None
    ) -> str:
        """
        Perform the minimal sequence of requests that prepare the student profile context on the server.
        If `initial_response` is provided (e.g., the final response after login), it will be reused to
        extract CSRF and avoid an extra profile GET. Returns the CSRF token to use for subsequent AJAX requests.
        """
        profile_url = f"{self.BASE_URL}/s/studentProfilePESU"

        # Reuse provided response to avoid an extra network call
        if initial_response is not None:
            r = initial_response
        else:
            try:
                r = self.session.get(profile_url, allow_redirects=True, timeout=15)
                r.raise_for_status()
            except requests.exceptions.HTTPError as e:
                cookies = self.session.cookies.get_dict()
                if "JSESSIONID" in cookies or "SESSION" in cookies:
                    app_logger.debug(
                        "Fetching profile returned error but session cookie present; retrying once"
                    )
                    r = self.session.get(profile_url, allow_redirects=True, timeout=15)
                    r.raise_for_status()
                else:
                    raise

        # Prefer HTML token found on the page, then cookie
        try:
            html_csrf = self._extract_csrf_token(r.text)
        except AuthenticationError:
            html_csrf = None

        cookie_csrf = self.session.cookies.get(
            "XSRF-TOKEN"
        ) or self.session.cookies.get("CSRF-TOKEN")

        if html_csrf:
            csrf_token = html_csrf
        elif cookie_csrf:
            csrf_token = cookie_csrf
        else:
            raise AuthenticationError(
                "Missing CSRF token before fetching profile; expected an HTML or cookie-based token."
            )

        # Prepare headers for AJAX-like requests
        headers = {
            "X-Requested-With": "XMLHttpRequest",
            "X-CSRF-Token": csrf_token,
            "Content-Type": "application/x-www-form-urlencoded",
            "Referer": profile_url,
        }

        # Make a single best-effort preparatory request (semesters); avoid the heavier admin endpoint to reduce requests
        try:
            r_sem = self.session.get(
                f"{self.BASE_URL}/a/studentProfilePESU/getStudentSemestersPESU",
                params={"_": int(time.time() * 1000)},
                headers=headers,
                timeout=15,
            )
            r_sem.raise_for_status()
        except Exception:
            app_logger.debug("Semesters fetch failed; continuing anyway")

        return csrf_token

    def _fetch_semester_batch_ids(self, csrf_token: str) -> Optional[List[str]]:
        """
        Fetch semester options and return a list of `value` attributes found in
        the <option> tags (e.g., batchClassId values). Returns None if nothing
        can be discovered.
        """
        url = f"{self.BASE_URL}/a/studentProfilePESU/getStudentSemestersPESU"
        headers = {
            "X-Requested-With": "XMLHttpRequest",
            "X-CSRF-Token": csrf_token,
            "Content-Type": "application/x-www-form-urlencoded",
            "Referer": f"{self.BASE_URL}/s/studentProfilePESU",
        }
        try:
            resp = self.session.get(
                url, params={"_": int(time.time() * 1000)}, headers=headers, timeout=15
            )
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "html.parser")
            options = soup.find_all("option")
            values: List[str] = []
            for opt in options:
                val = opt.get("value")
                if val and re.search(r"\d+", val):
                    values.append(val)
            return values if values else None
        except requests.RequestException as e:
            app_logger.debug(f"Failed to fetch semester batch ids: {e}")
            return None

    def scrape_attendance_data(self) -> Optional[List[List[str]]]:
        app_logger.info(
            f"Starting attendance data scraping for branch: {self.branch_prefix}"
        )

        try:
            # Ensure the profile context is prepared and get a CSRF token
            csrf_token = self._prepare_profile_context()

            # If batch class IDs are not configured (None/empty), attempt to fetch them
            if not self.batch_class_ids:
                fetched = self._fetch_semester_batch_ids(csrf_token)
                if fetched:
                    # Record auto-discovery and build suggestion message
                    self._auto_discovered_batch_ids = fetched
                    self.batch_class_ids = fetched if len(fetched) > 1 else fetched[0]
                    try:
                        prefix = re.sub(r"\d+$", "", self.username)
                        ids = ",".join(fetched)
                        msg = (
                            f"Auto-discovered batchClassId(s) for SRN prefix '{prefix}': {ids}. "
                            "Consider opening a PR to add this mapping to 'frontend/web/mapping.json' under 'BATCH_CLASS_ID_MAPPING'."
                        )
                        self._pr_suggestion = msg
                        app_logger.info(
                            f"Auto-discovered batchClassId(s) during scraping: {self.batch_class_ids}"
                        )
                        app_logger.info(self._pr_suggestion)
                    except Exception:
                        try:
                            app_logger.info(
                                f"Auto-discovered batchClassId(s) during scraping: {self.batch_class_ids}"
                            )
                        except Exception:
                            pass
                else:
                    app_logger.warning(
                        "No batchClassId configured and auto-discovery failed; cannot fetch attendance"
                    )
                    return None

            # Try each batch class ID until we get valid data
            batch_ids = self._normalize_batch_ids(self.batch_class_ids)

            for batch_id in batch_ids:
                attendance_data = self._fetch_attendance_for_batch(batch_id, csrf_token)

                if attendance_data:
                    app_logger.info(
                        f"Successfully retrieved attendance data for "
                        f"batch ID: {batch_id}"
                    )
                    return attendance_data

            app_logger.warning(
                "No attendance data found for any configured batch class ID"
            )
            return None

        except Exception as e:
            raise AttendanceScrapingError(f"Failed to scrape attendance data: {e}")

    def _normalize_batch_ids(self, batch_ids: Union[int, List[int]]) -> List[str]:
        if isinstance(batch_ids, list):
            return [str(bid) for bid in batch_ids]
        return [str(batch_ids)]

    def _fetch_attendance_for_batch(
        self, batch_id: str, csrf_token: str
    ) -> Optional[List[List[str]]]:
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
            response = self.session.post(
                attendance_url, data=request_payload, headers=headers, timeout=15
            )

            # If we are redirected to sessionExpired or an HTTP 4xx occurs, log cookies & try https fallback
            if response.status_code != 200:
                app_logger.debug(
                    f"Attendance POST status={response.status_code} url={response.url}"
                )
                cookies = self.session.cookies.get_dict()
                app_logger.debug(f"Session cookies: {cookies}")
                # If server redirected to an http URL that returns 404, try https equivalent
                try:
                    if getattr(response, "url", "").startswith("http://"):
                        alt = "https://" + response.url.split("://", 1)[1]
                        app_logger.debug(f"Retrying attendance URL with https: {alt}")
                        alt_resp = self.session.post(
                            alt, data=request_payload, headers=headers, timeout=15
                        )
                        if alt_resp.status_code == 200:
                            return self._parse_attendance_table(alt_resp.text)
                except Exception:
                    pass

                app_logger.error(
                    f"HTTP {response.status_code} error for batch ID {batch_id}"
                )
                return None

            return self._parse_attendance_table(response.text)

        except requests.RequestException as e:
            app_logger.error(
                f"Network error fetching data for batch ID {batch_id}: {e}"
            )
            return None

    def _parse_attendance_table(self, html_content: str) -> Optional[List[List[str]]]:
        soup = BeautifulSoup(html_content, "html.parser")
        attendance_table = soup.find("table", {"class": "table"})

        if not attendance_table:
            app_logger.warning("No attendance table found in response")
            return None

        table_body = attendance_table.find("tbody")  # type: ignore
        if not table_body:
            app_logger.warning("No table body found in attendance table")
            return None

        attendance_records = []

        for row in table_body.find_all("tr"):  # type: ignore
            row_data = self._extract_row_data(row)

            if row_data and self._is_valid_attendance_record(row_data):
                attendance_records.append(row_data)

        return attendance_records if attendance_records else None

    def _extract_row_data(self, table_row) -> List[str]:
        return [cell.get_text(strip=True) for cell in table_row.find_all("td")]

    def _is_valid_attendance_record(self, row_data: List[str]) -> bool:
        # Require at least a subject code/name; allow NA values in numeric columns
        if len(row_data) < 2:
            return False

        # Reject rows with empty subject/course code
        if not row_data[0] or not row_data[0].strip():
            return False

        # If the numeric column(s) are 'NA' we still consider this a valid record
        if (
            len(row_data) > 2
            and isinstance(row_data[2], str)
            and row_data[2].strip().upper() == "NA"
        ):
            app_logger.debug(
                f"Attendance entry contains 'NA' but will be included: {row_data}"
            )

        return True


def fetch_student_attendance(
    username: str, password: str
) -> tuple[Optional[List[List[str]]], PESUAttendanceScraper]:
    """Convenience function that returns (attendance_data, scraper) for external usage.

    The returned scraper may contain an informational suggestion if batchClassId(s)
    were auto-discovered during login or scraping.
    """
    scraper = PESUAttendanceScraper(username, password)

    try:
        scraper.login()
        return scraper.scrape_attendance_data(), scraper
    finally:
        scraper.logout()


# ============================================================================
# API MODELS AND ROUTES
# ============================================================================

AttendanceRequest = Dict[str, Any]
AttendanceResponse = Dict[str, Any]


async def process_attendance_task(username: str, password: str) -> Dict[str, Any]:
    """Process attendance data and return results synchronously."""
    # Initialize scraper as None to handle edge cases
    scraper: Optional[PESUAttendanceScraper] = None

    try:
        app_logger.info(f"Starting attendance processing for SRN: {username[:10]}")

        # Initialize scraper for subject mapping access (for client-friendly labels)
        # Fetch attendance data using convenience function which also returns the scraper
        attendance_data, used_scraper = fetch_student_attendance(username, password)

        if not attendance_data:
            raise AttendanceScrapingError("No attendance data retrieved")

        app_logger.info("Formatting attendance data")

        # Format attendance data for client consumption using the returned scraper's subject mapping
        formatted_attendance = _format_attendance_data(
            attendance_data, used_scraper.subject_mapping
        )

        result = {
            "status": "complete",
            "attendance": formatted_attendance,
        }

        # If we auto-discovered batchClassIds, add a helpful suggestion to the result
        if getattr(used_scraper, "_pr_suggestion", None):
            result["suggestions"] = [used_scraper._pr_suggestion]
            try:
                app_logger.info(f"Suggestion for user: {used_scraper._pr_suggestion}")
            except Exception:
                pass

        app_logger.info("Attendance processing completed successfully")

        return result

    except (AuthenticationError, AttendanceScrapingError) as e:
        # Handle specific scraping errors with detailed logging
        error_msg = f"Attendance processing error: {str(e)}"
        app_logger.error(error_msg)
        raise

    except Exception as e:
        # Handle unexpected errors with comprehensive logging
        error_msg = f"Unexpected error during processing: {str(e)}"
        app_logger.error(error_msg)
        raise


def _format_attendance_data(
    attendance_data: List[List[str]], subject_mapping: Dict[str, str]
) -> List[Dict[str, Any]]:
    formatted_attendance: List[Dict[str, Any]] = []

    for item in attendance_data:
        # Require at least subject code/name
        if len(item) < 1:
            continue

        subject_code = item[0]
        course_name = item[1] if len(item) > 1 else None
        raw_total = item[2] if len(item) > 2 else None
        raw_percentage = item[3] if len(item) > 3 else None

        # Normalize 'NA' to None and attempt to coerce numeric values
        def normalize_int(val: Optional[str]) -> Optional[int]:
            if not val:
                return None
            v = val.strip()
            if v.upper() == "NA":
                return None
            m = re.search(r"(\d+)", v)
            return int(m.group(1)) if m else None

        def normalize_float(val: Optional[str]) -> Optional[float]:
            if not val:
                return None
            v = val.strip().replace("%", "")
            if v.upper() == "NA":
                return None
            try:
                return float(v)
            except Exception:
                m = re.search(r"(\d+(?:\.\d+)?)", v)
                return float(m.group(1)) if m else None

        total_classes = normalize_int(raw_total)
        percentage = normalize_float(raw_percentage)

        if (
            total_classes is None
            and raw_total
            and isinstance(raw_total, str)
            and raw_total.strip().upper() == "NA"
        ):
            app_logger.debug(
                f"Normalized 'NA' total_classes for subject {subject_code}"
            )

        formatted_attendance.append(
            {
                "subject": subject_mapping.get(subject_code, subject_code),
                "course_name": course_name,
                "total_classes": total_classes,
                "percentage": percentage,
                "raw_data": raw_total,
            }
        )

    return formatted_attendance


# ============================================================================
# FASTAPI APPLICATION SETUP
# ============================================================================

# Initialize configuration and logger
try:
    mappings = load_mappings_config()
    settings = load_app_settings()
    app_logger = setup_logger()
except ConfigurationError as e:
    # Re-raise with additional context for easier debugging
    raise ConfigurationError(f"Failed to initialize configuration: {e}") from e

# Initialize FastAPI app and router
app = FastAPI(
    title="PESU Academy Attendance Tracker",
    description="Fetch and analyze student attendance data from PESUAcademy",
    version="1.0.0",
)
router = APIRouter()


@router.get("/healthcheck")
async def healthcheck() -> Dict[str, Any]:
    return APIResponse.success(
        data={"status": "healthy"},
        code="healthcheck_ok",
        message="Service is healthy and operational",
    )


@router.post("/attendance")
async def get_attendance(request: dict = Body(...)) -> dict:
    try:
        # Process attendance data
        username = request.get("username")
        password = request.get("password")
        if not username or not password:
            response, status_code = APIResponse.error(
                error_type="ValidationError",
                details="username and password are required",
                code="missing_credentials",
                status_code=400,
            )
            raise HTTPException(status_code=status_code, detail=response)

        result = await process_attendance_task(username, password)

        return APIResponse.success(
            data=result,
            code="attendance_retrieved",
            message=f"Attendance data retrieved for {username}",
        )

    except ConfigurationError as error:
        app_logger.error(f"Configuration error: {error}")
        response, status_code = APIResponse.error(
            error_type="ConfigurationError",
            details=str(error),
            code="config_error",
            status_code=500,
        )
        raise HTTPException(status_code=status_code, detail=response)

    except AuthenticationError as error:
        app_logger.warning(f"Authentication failed: {error}")
        response, status_code = APIResponse.error(
            error_type="AuthenticationError",
            details=str(error),
            code="auth_failed",
            status_code=401,
        )
        raise HTTPException(status_code=status_code, detail=response)

    except AttendanceScrapingError as error:
        app_logger.error(f"Scraping error: {error}")
        response, status_code = APIResponse.error(
            error_type="ScrapingError",
            details=str(error),
            code="scraping_failed",
            status_code=500,
        )
        raise HTTPException(status_code=status_code, detail=response)

    except Exception as error:
        app_logger.error(f"Unexpected error: {error}")
        response, status_code = APIResponse.error(
            error_type="UnexpectedError",
            details=str(error),
            code="internal_error",
            status_code=500,
        )
        raise HTTPException(status_code=status_code, detail=response)


# Include API routes and mount static files
app.include_router(router, prefix="/api")


# Serve single authoritative mapping.json from repo root for frontend requests
@app.get("/mapping.json", include_in_schema=False)
async def serve_mapping_json():
    repo_root = Path(__file__).resolve().parent
    config_path = repo_root / "frontend" / "web" / "mapping.json"
    try:
        with config_path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        return JSONResponse(content=data, status_code=200)
    except FileNotFoundError:
        payload, status_code = APIResponse.error(
            error_type="NotFound",
            details="mapping.json not found at 'frontend/web/mapping.json'",
            code="mapping_missing",
            status_code=404,
        )
        return JSONResponse(content=payload, status_code=status_code)
    except json.JSONDecodeError as e:
        payload, status_code = APIResponse.error(
            error_type="ConfigError",
            details=f"Invalid mapping.json: {e}",
            code="mapping_invalid",
            status_code=500,
        )
        return JSONResponse(content=payload, status_code=status_code)


if settings.ENABLE_BACKEND_WEB:
    app.mount("/", StaticFiles(directory="frontend/web", html=True), name="frontend")
else:
    app_logger.info("Frontend static files mount disabled (ENABLE_BACKEND_WEB=false)")

    # Provide helpful root response when frontend static files are disabled
    @app.get("/", include_in_schema=False)
    async def frontend_disabled_root():
        response_payload, status_code = APIResponse.error(
            error_type="FeatureDisabled",
            details="Frontend disabled. Set ENABLE_BACKEND_WEB=true to enable serving the web frontend.",
            code="frontend_disabled",
            status_code=404,
        )
        return JSONResponse(content=response_payload, status_code=status_code)

    @app.get("/{full_path:path}", include_in_schema=False)
    async def frontend_disabled_catchall(full_path: str):
        if (
            full_path.startswith("api")
            or full_path.startswith("docs")
            or full_path.startswith("openapi.json")
            or full_path.startswith("redoc")
        ):
            response_payload, status_code = APIResponse.error(
                error_type="NotFound",
                details=f"Path '/{full_path}' not found",
                code="not_found",
                status_code=404,
            )
            return JSONResponse(content=response_payload, status_code=status_code)

        response_payload, status_code = APIResponse.error(
            error_type="FeatureDisabled",
            details="Frontend disabled. Set ENABLE_BACKEND_WEB=true to enable serving the web frontend.",
            code="frontend_disabled",
            status_code=404,
        )
        return JSONResponse(content=response_payload, status_code=status_code)


if __name__ == "__main__":
    # Optionally start the Telegram bot as a separate subprocess.
    # Set ENABLE_BACKEND_TELEGRAM=1 (or true) in the environment to enable.
    bot_proc = None
    try:
        if settings.ENABLE_BACKEND_TELEGRAM:
            telegram_bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
            if not telegram_bot_token:
                print(
                    "ERROR: ENABLE_BACKEND_TELEGRAM is enabled but TELEGRAM_BOT_TOKEN is not set in .env"
                )
                print(
                    "Please add TELEGRAM_BOT_TOKEN to your .env file or disable the Telegram bot."
                )
                sys.exit(1)

            tg_bot_path = (
                Path(__file__).resolve().parent / "frontend" / "telegram" / "tg_bot.py"
            )
            if tg_bot_path.exists():
                cmd = [sys.executable, str(tg_bot_path)]
                env = os.environ.copy()
                bot_proc = subprocess.Popen(cmd, env=env, start_new_session=True)

                def _terminate_bot():
                    try:
                        if bot_proc and bot_proc.poll() is None:
                            bot_proc.terminate()
                            bot_proc.wait(timeout=5)
                    except Exception:
                        try:
                            bot_proc.kill()
                        except Exception:
                            pass

                atexit.register(_terminate_bot)
                print(f"Started telegram bot subprocess (pid={bot_proc.pid})")
            else:
                print(
                    f"Telegram bot file not found at: {tg_bot_path}, skipping bot start"
                )

        # Optionally start the web server.
        # Set ENABLE_BACKEND_WEB=1 (or true) in the environment to enable.
        if settings.ENABLE_BACKEND_API:
            if settings.ENABLE_BACKEND_WEB:
                print(f"Starting web + API server on port {settings.PORT}...")
            else:
                print(
                    f"Starting API server (frontend disabled) on port {settings.PORT}..."
                )
            uvicorn.run(
                "main:app", host="0.0.0.0", port=settings.PORT, reload=settings.DEBUG
            )
        else:
            print("API server disabled (ENABLE_BACKEND_API set to false)")
            if bot_proc:
                print("Running in bot-only mode. Press Ctrl+C to exit.")
                try:
                    bot_proc.wait()
                except KeyboardInterrupt:
                    print("\nShutting down...")
            # Keep the process alive if only running the bot
            if bot_proc:
                print("Running in bot-only mode. Press Ctrl+C to exit.")
                try:
                    bot_proc.wait()
                except KeyboardInterrupt:
                    print("\nShutting down...")
    finally:
        # Ensure subprocess is cleaned up on exit
        if bot_proc and bot_proc.poll() is None:
            try:
                bot_proc.terminate()
                bot_proc.wait(timeout=5)
            except Exception:
                try:
                    bot_proc.kill()
                except Exception:
                    pass
