from typing import List, Optional, Union

import requests
from bs4 import BeautifulSoup

from backend.engine.stream import app_logger
from backend.core import mappings, ConfigurationError


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
            self.controller_mode = branch_config["controller_mode"]
            self.action_type = branch_config["action_type"]
            self.menu_id = branch_config["menu_id"]
            self.batch_class_ids = branch_config["batchClassId"]
            self.subject_mapping = branch_config["subject_mapping"]

            # Extract branch prefix from username for logging
            import re

            pattern = (
                r"^PES(1UG23(CS|AM)|1UG24(CS|AM|BT|ME|EC)|"
                r"2UG23(CS|AM|EC)|2UG24(CS|AM|EC))\d{3}$"
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

    def _normalize_batch_ids(self, batch_ids: Union[str, List[str]]) -> List[str]:
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


# Convenience function for external usage
def fetch_student_attendance(username: str, password: str) -> Optional[List[List[str]]]:
    scraper = PESUAttendanceScraper(username, password)

    try:
        scraper.login()
        return scraper.scrape_attendance_data()
    finally:
        scraper.logout()
