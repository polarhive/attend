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
    def success(data: Any, code: str = "success", message: str = "Operation successful") -> Dict[str, Any]:
        """Return standardized success response"""
        return {
            "success": True,
            "code": code,
            "message": message,
            "data": data,
            "timestamp": time.time(),
        }
    
    @staticmethod
    def error(error_type: str, details: str, code: str = "error", status_code: int = 400) -> tuple[Dict[str, Any], int]:
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
    batchClassId: Union[int, List[int]]
    subject_mapping: Dict[str, str]


class MappingsConfig:
    def __init__(self, config: Dict[str, Any]):
        self.CONTROLLER_MODE = config.get("CONTROLLER_MODE")
        self.ACTION_TYPE = config.get("ACTION_TYPE")
        self.MENU_ID = config.get("MENU_ID")
        self.BATCH_CLASS_ID_MAPPING = config.get("BATCH_CLASS_ID_MAPPING", {})
        self.SUBJECT_MAPPING = config.get("SUBJECT_MAPPING", {})

    def get_branch_config(self, srn: str) -> MappingsData:
        # Validate SRN format using comprehensive regex pattern
        pattern = r"^PES(2UG23(CS|AM|EC)|2UG24(CS|AM|EC)|2UG25CS)\d{3}$"
        match = re.match(pattern, srn)

        if not match:
            raise ValueError(f"Invalid SRN format: '{srn}'")

        branch_prefix = match.group(1)
        full_prefix = f"PES{branch_prefix}"

        batch_class_id = self.BATCH_CLASS_ID_MAPPING.get(full_prefix)
        if batch_class_id is None:
            available_branches = list(self.BATCH_CLASS_ID_MAPPING.keys())
            raise ValueError(
                f"Missing batch class ID for branch '{full_prefix}'. Available: {available_branches}"
            )

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
            load_dotenv()
        except Exception:
            pass

        self.PORT = int(os.getenv("PORT", 10000))
        self.LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
        self.DEBUG = os.getenv("DEBUG", "False").lower() in ("1", "true", "yes")
        self.REQUEST_TIMEOUT_SECONDS = int(os.getenv("REQUEST_TIMEOUT_SECONDS", 5))
        # Backend feature toggles
        self.ENABLE_BACKEND_API = os.getenv("ENABLE_BACKEND_API", "true").lower() in ("1", "true", "yes")
        self.ENABLE_BACKEND_WEB = os.getenv("ENABLE_BACKEND_WEB", "true").lower() in ("1", "true", "yes")
        self.ENABLE_BACKEND_TELEGRAM = os.getenv("ENABLE_BACKEND_TELEGRAM", "false").lower() in ("1", "true", "yes")


def load_mappings_config() -> MappingsConfig:
    config_path = Path(__file__).resolve().parent / "mapping.json"

    try:
        with config_path.open("r", encoding="utf-8") as file:
            config_data = json.load(file)
        return MappingsConfig(config_data)
    except FileNotFoundError:
        raise ConfigurationError(f"Configuration file not found at: {config_path}.")
    except json.JSONDecodeError as error:
        raise ConfigurationError(f"Invalid JSON format in configuration file: {error}")
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

            # Extract branch prefix from username for logging
            pattern = (
                r"^PES(2UG23(CS|AM|EC)|2UG24(CS|AM|EC)|2UG25CS)\d{3}$"
            )
            match = re.match(pattern, username)
            self.branch_prefix = match.group(1) if match else username[:10]

        except ValueError as e:
            raise ConfigurationError(f"Configuration error: {e}")

    def _extract_csrf_token(self, html_content: str) -> str:
        soup = BeautifulSoup(html_content, "html.parser")
        csrf_input = soup.find("input", {"name": "_csrf"})

        if not csrf_input or not csrf_input.get("value"):  # type: ignore
            raise AuthenticationError("CSRF token not found in response")

        return csrf_input.get("value")  # type: ignore

    def login(self) -> None:
        app_logger.info("Initiating authentication process")

        try:
            # Get login page and extract CSRF token
            login_page_url = f"{self.BASE_URL}/"
            response = self.session.get(login_page_url)
            response.raise_for_status()

            csrf_token = self._extract_csrf_token(response.text)

            # Prepare and submit login credentials
            login_url = f"{self.BASE_URL}/j_spring_security_check"
            login_payload = {
                "j_username": self.username,
                "j_password": self.password,
                "_csrf": csrf_token,
            }

            login_response = self.session.post(login_url, data=login_payload)
            login_response.raise_for_status()

            # Validate successful authentication
            self._validate_authentication()

            app_logger.info("Authentication successful")

        except requests.RequestException as e:
            raise AuthenticationError(f"Network error during authentication: {e}")
        except Exception as e:
            raise AuthenticationError(f"Authentication failed: {e}")

    def _validate_authentication(self) -> None:
        profile_url = f"{self.BASE_URL}/s/studentProfilePESU"

        try:
            # Check if we can access protected profile page without redirect
            profile_response = self.session.get(profile_url, allow_redirects=False)

            # If we get a redirect, authentication failed
            if profile_response.status_code in (302, 301):
                redirect_location = profile_response.headers.get("Location")
                if redirect_location:
                    raise AuthenticationError(
                        "Authentication failed: Invalid credentials"
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

    def scrape_attendance_data(self) -> Optional[List[List[str]]]:
        app_logger.info(
            f"Starting attendance data scraping for branch: {self.branch_prefix}"
        )

        try:
            # Get fresh CSRF token for attendance requests
            dashboard_url = f"{self.BASE_URL}/s/studentProfilePESU"
            dashboard_response = self.session.get(dashboard_url)
            dashboard_response.raise_for_status()

            csrf_token = self._extract_csrf_token(dashboard_response.text)

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

        try:
            response = self.session.post(attendance_url, data=request_payload)

            if response.status_code != 200:
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
        # Check minimum required columns and exclude invalid entries
        if len(row_data) < 3:
            return False

        # Skip records marked as "NA" (not applicable)
        if len(row_data) > 2 and row_data[2] == "NA":
            app_logger.debug(f"Skipping invalid attendance entry: {row_data}")
            return False

        return True


def fetch_student_attendance(username: str, password: str) -> Optional[List[List[str]]]:
    """Convenience function for external usage"""
    scraper = PESUAttendanceScraper(username, password)

    try:
        scraper.login()
        return scraper.scrape_attendance_data()
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

        # Initialize scraper for subject mapping access
        scraper = PESUAttendanceScraper(username, password)

        # Fetch attendance data using convenience function
        attendance_data = fetch_student_attendance(username, password)

        if not attendance_data:
            raise AttendanceScrapingError("No attendance data retrieved")

        app_logger.info("Formatting attendance data")

        # Format attendance data for client consumption
        formatted_attendance = _format_attendance_data(
            attendance_data, scraper.subject_mapping
        )

        app_logger.info("Attendance processing completed successfully")

        return {
            "status": "complete",
            "attendance": formatted_attendance,
        }

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
        # Send raw data to client - let JS handle validation and calculations
        if len(item) >= 3:  # Basic check for minimum fields
            formatted_attendance.append(
                {
                    "subject": subject_mapping.get(item[0], item[0]),
                    "raw_data": item[2],
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
    version="1.0.0"
)
router = APIRouter()


@router.get("/healthcheck")
async def healthcheck() -> Dict[str, Any]:
    return APIResponse.success(
        data={"status": "healthy"},
        code="healthcheck_ok",
        message="Service is healthy and operational"
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
                status_code=400
            )
            raise HTTPException(status_code=status_code, detail=response)

        result = await process_attendance_task(username, password)

        return APIResponse.success(
            data=result,
            code="attendance_retrieved",
            message=f"Attendance data retrieved for {username}"
        )

    except ConfigurationError as error:
        app_logger.error(f"Configuration error: {error}")
        response, status_code = APIResponse.error(
            error_type="ConfigurationError",
            details=str(error),
            code="config_error",
            status_code=500
        )
        raise HTTPException(status_code=status_code, detail=response)
    
    except AuthenticationError as error:
        app_logger.warning(f"Authentication failed: {error}")
        response, status_code = APIResponse.error(
            error_type="AuthenticationError",
            details=str(error),
            code="auth_failed",
            status_code=401
        )
        raise HTTPException(status_code=status_code, detail=response)
    
    except AttendanceScrapingError as error:
        app_logger.error(f"Scraping error: {error}")
        response, status_code = APIResponse.error(
            error_type="ScrapingError",
            details=str(error),
            code="scraping_failed",
            status_code=500
        )
        raise HTTPException(status_code=status_code, detail=response)
    
    except Exception as error:
        app_logger.error(f"Unexpected error: {error}")
        response, status_code = APIResponse.error(
            error_type="UnexpectedError",
            details=str(error),
            code="internal_error",
            status_code=500
        )
        raise HTTPException(status_code=status_code, detail=response)


# Include API routes and mount static files
app.include_router(router, prefix="/api")
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
        # Do not override API routes - they are defined under /api prefix and take precedence.
        if full_path.startswith("api") or full_path.startswith("docs") or full_path.startswith("openapi.json") or full_path.startswith("redoc"):
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
            tg_bot_path = Path(__file__).resolve().parent / "frontend" / "telegram" / "tg_bot.py"
            if tg_bot_path.exists():
                cmd = [sys.executable, str(tg_bot_path)]
                # Inherit current environment so .env and other vars propagate
                env = os.environ.copy()
                # Start bot subprocess in its own session so signals don't immediately kill both
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
                print(f"Telegram bot file not found at: {tg_bot_path}, skipping bot start")

        # Optionally start the web server.
        # Set ENABLE_BACKEND_WEB=1 (or true) in the environment to enable.
        if settings.ENABLE_BACKEND_API:
            if settings.ENABLE_BACKEND_WEB:
                print(f"Starting web + API server on port {settings.PORT}...")
            else:
                print(f"Starting API server (frontend disabled) on port {settings.PORT}...")
            uvicorn.run("main:app", host="0.0.0.0", port=settings.PORT, reload=settings.DEBUG)
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
