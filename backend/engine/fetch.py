import os
import json
import re
import logging
import requests
from bs4 import BeautifulSoup
from backend.engine.config import get_branch_config

class PESUAttendanceScraper:
    def __init__(self, username, password):
        self.session = requests.Session()
        self.base_url = "https://www.pesuacademy.com/Academy"
        self.username = username
        self.password = password

        # Use the branch-specific configuration (must match exactly the SRN prefix)
        config = get_branch_config(username)
        self.controller_mode = config["controller_mode"]
        self.action_type = config["action_type"]
        self.batchClassId = config["batchClassId"]
        self.menu_id = config["menu_id"]
        self.subject_mapping = config["subject_mapping"]

    def get_csrf_token(self, html):
        soup = BeautifulSoup(html, 'html.parser')
        csrf_input = soup.find('input', {'name': '_csrf'})
        if not csrf_input:
            raise Exception("CSRF token not found")
        return csrf_input['value']

    def login(self):
        logging.info("Attempting to log in")
        login_page = f"{self.base_url}/"
        login_url = f"{self.base_url}/j_spring_security_check"
        response = self.session.get(login_page)
        csrf_token = self.get_csrf_token(response.text)
        payload = {
            'j_username': self.username,
            'j_password': self.password,
            '_csrf': csrf_token
        }
        login_response = self.session.post(login_url, data=payload)
        if "Invalid username or password" in login_response.text:
            raise Exception("Login failed: Invalid credentials")
        logging.info("Login successful")

    def logout(self):
        logging.info("Logging out")
        self.session.get(f"{self.base_url}/logout")

    def fetch_attendance(self):
        logging.info(f"Fetching attendance for batchClassId: {self.batchClassId}")
        dashboard = self.session.get(f"{self.base_url}/s/studentProfilePESU")
        csrf_token = self.get_csrf_token(dashboard.text)
        attendance_url = f"{self.base_url}/s/studentProfilePESUAdmin"
        payload = {
            'controllerMode': self.controller_mode,
            'actionType': self.action_type,
            'menuId': self.menu_id,
            'batchClassId': self.batchClassId,
            '_csrf': csrf_token
        }
        response = self.session.post(attendance_url, data=payload)
        if response.status_code != 200:
            logging.error("Failed to fetch attendance, HTTP status: " + str(response.status_code))
            return None
        logging.info("Attendance fetched successfully")
        return self.parse_attendance(response.text)

    def parse_attendance(self, html):
        logging.info("Parsing attendance data")
        soup = BeautifulSoup(html, 'html.parser')
        table = soup.find('table', {'class': 'table'})
        if not table:
            logging.warning("Attendance table not found in the response")
            return None
        attendance_data = []
        for row in table.find('tbody').find_all('tr'):
            columns = [cell.text.strip() for cell in row.find_all('td')]
            if len(columns) >= 3:
                attendance_data.append(columns)
        return attendance_data if attendance_data else None  # Ensure we don't return an empty list

def fetch_attendance_with_retry(scraper: PESUAttendanceScraper):
    attendance_data = scraper.fetch_attendance()

    if not attendance_data and scraper.username.startswith("PES2UG24"):
        logging.warning("Empty attendance data, retrying with next batchClassIds...")

        if isinstance(scraper.batchClassId, list) and scraper.batchClassId:
            for batch_id in scraper.batchClassId:
                logging.info(f"Retrying with batchClassId: {batch_id}")
                scraper.batchClassId = batch_id
                attendance_data = scraper.fetch_attendance()
                if attendance_data:
                    break

        else:
            logging.warning("batchClassId is not a list or is empty, retrying with batchClassId + 1...")
            if isinstance(scraper.batchClassId, int):  # Ensure it's an integer before incrementing
                scraper.batchClassId += 1
                attendance_data = scraper.fetch_attendance()

    return attendance_data
