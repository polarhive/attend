import os
import json
import requests
from bs4 import BeautifulSoup
from backend.engine.stream import app_logger

with open("mapping.json", "r") as file:
    CONFIG = json.load(file)

def get_branch_config(username):
    prefix = username[:10] 
    return {
        "controller_mode": CONFIG["CONTROLLER_MODE"],
        "action_type": CONFIG["ACTION_TYPE"],
        "menu_id": CONFIG["MENU_ID"],
        "batchClassId": CONFIG["BATCH_CLASS_ID_MAPPING"].get(prefix, []),
        "subject_mapping": CONFIG["SUBJECT_MAPPING"],
        "branch_prefix": prefix
    }

class PESUAttendanceScraper:
    def __init__(self, username, password):
        self.session = requests.Session()
        self.base_url = "https://www.pesuacademy.com/Academy"
        self.username = username
        self.password = password

        config = get_branch_config(username)
        self.controller_mode = config["controller_mode"]
        self.action_type = config["action_type"]
        self.menu_id = config["menu_id"]
        self.batchClassId = config["batchClassId"]
        self.subject_mapping = config["subject_mapping"]
        self.branch_prefix = config["branch_prefix"]  # Store the branch prefix

    def get_csrf_token(self, html):
        soup = BeautifulSoup(html, 'html.parser')
        csrf_input = soup.find('input', {'name': '_csrf'})
        if not csrf_input:
            raise Exception("CSRF token not found")
        return csrf_input['value']

    def login(self):
        app_logger.info("Attempting to log in")
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

    def logout(self):
        self.session.get(f"{self.base_url}/logout")
        app_logger.info("Logged out successfully")

    def fetch_attendance(self):
        app_logger.info(f"Fetching attendance for branch: {self.branch_prefix}")
        dashboard = self.session.get(f"{self.base_url}/s/studentProfilePESU")
        csrf_token = self.get_csrf_token(dashboard.text)
        attendance_url = f"{self.base_url}/s/studentProfilePESUAdmin"
        
        batch_ids = self.batchClassId if isinstance(self.batchClassId, list) else [self.batchClassId]
        
        for batch_id in batch_ids:
            payload = {
                'controllerMode': self.controller_mode,
                'actionType': self.action_type,
                'menuId': self.menu_id,
                'batchClassId': batch_id,
                '_csrf': csrf_token
            }
            response = self.session.post(attendance_url, data=payload)
            
            if response.status_code != 200:
                app_logger.error(f"Failed to fetch attendance for ID {batch_id}, HTTP status: {response.status_code}")
                continue
            
            attendance_data = self.parse_attendance(response.text)
            if attendance_data:
                app_logger.info(f"Attendance fetched successfully for ID {batch_id}")
                return attendance_data
            
        app_logger.warning("Empty attendance data after trying all batchClassId options")
        return None


    def parse_attendance(self, html):
        soup = BeautifulSoup(html, 'html.parser')
        table = soup.find('table', {'class': 'table'})
        if not table:
            app_logger.warning("Attendance table not found in the response")
            return None
        attendance_data = []
        for row in table.find('tbody').find_all('tr'):
            columns = [cell.text.strip() for cell in row.find_all('td')]
            if len(columns) >= 3:
                if columns[2] == "NA":
                    app_logger.warning(f"Skipping invalid attendance entry: {columns}")
                    continue
                attendance_data.append(columns)
        return attendance_data if attendance_data else None

