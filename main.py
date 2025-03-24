import os
import requests
import uvicorn
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, FileResponse
import logging
import matplotlib.pyplot as plt
import numpy as np
import base64
from io import BytesIO

# Load environment variables
load_dotenv()

# Set up logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# Environment variables
PESU_USERNAME = os.getenv("PESU_USERNAME")
PESU_PASSWORD = os.getenv("PESU_PASSWORD")
BATCH_CLASS_ID = os.getenv("BATCH_CLASS_ID", "2660")
CONTROLLER_MODE = os.getenv("CONTROLLER_MODE", "6407")
ACTION_TYPE = os.getenv("ACTION_TYPE", "8")
MENU_ID = os.getenv("MENU_ID", "660")
BUNKABLE_THRESHOLD = int(os.getenv("BUNKABLE_THRESHOLD", "75"))
SUBJECT_MAPPING = dict(item.split(":") for item in os.getenv("SUBJECT_MAPPING", "").split(","))
PORT = os.getenv("PORT", "8000")

app = FastAPI()

class AttendanceCalculator:
    @staticmethod
    def calculate_bunkable(total_classes, attended_classes, threshold):
        """
        Fixed logic to calculate the correct number of bunkable classes.
        """
        if total_classes == 0:
            return 0

        max_bunkable = 0
        while (attended_classes / (total_classes + max_bunkable)) * 100 >= threshold:
            max_bunkable += 1
        return max_bunkable - 1 if max_bunkable > 0 else 0

    @staticmethod
    def calculate_threshold_mark(total_classes, threshold):
        return int((threshold / 100) * total_classes)


class PESUAttendanceScraper:
    def __init__(self, username, password):
        self.session = requests.Session()
        self.base_url = "https://www.pesuacademy.com/Academy"
        self.username = username
        self.password = password

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
        logging.info("Fetching attendance")
        dashboard = self.session.get(f"{self.base_url}/s/studentProfilePESU")
        csrf_token = self.get_csrf_token(dashboard.text)
        attendance_url = f"{self.base_url}/s/studentProfilePESUAdmin"
        payload = {
            'controllerMode': CONTROLLER_MODE,
            'actionType': ACTION_TYPE,
            'batchClassId': BATCH_CLASS_ID,
            'menuId': MENU_ID,
            '_csrf': csrf_token
        }
        response = self.session.post(attendance_url, data=payload)
        if response.status_code != 200:
            raise Exception("Failed to fetch attendance")
        logging.info("Attendance fetched successfully")
        return self.parse_attendance(response.text)

    def parse_attendance(self, html):
        logging.info("Parsing attendance data")
        soup = BeautifulSoup(html, 'html.parser')
        table = soup.find('table', {'class': 'table'})
        if not table:
            raise Exception("Attendance table not found")
        attendance_data = []
        for row in table.find('tbody').find_all('tr'):
            columns = [cell.text.strip() for cell in row.find_all('td')]
            if len(columns) >= 3:
                attendance_data.append(columns)
        return attendance_data


def generate_graph(attendance_data, threshold):
    logging.info("Generating attendance graph")
    subjects, attended, total, bunked, threshold_marks = [], [], [], [], []

    for item in attendance_data:
        subject_name = SUBJECT_MAPPING.get(item[0], item[0])
        attended_classes, total_classes = map(int, item[2].split("/"))
        bunked.append(total_classes - attended_classes)
        subjects.append(subject_name)
        attended.append(attended_classes)
        total.append(total_classes)
        threshold_marks.append(AttendanceCalculator.calculate_threshold_mark(total_classes, threshold))

    plt.figure(figsize=(12, 8))
    x = np.arange(len(subjects))
    plt.bar(x, attended, color='seagreen')
    plt.bar(x, bunked, bottom=attended, color='firebrick')

    for i, subject in enumerate(subjects):
        plt.text(x[i], threshold_marks[i] + 1, f"{threshold}%: {threshold_marks[i]}", ha='center', fontsize=9)

    new_labels = [f"{sub}\n{att}/{tot}" for sub, att, tot in zip(subjects, attended, total)]
    plt.xticks(x, new_labels, rotation=45, ha="right")
    plt.xlabel("Subjects")
    plt.ylabel("Classes")
    plt.title(f"Attendance ({threshold}% Threshold)")
    plt.legend(["Attended", "Bunked"])
    plt.tight_layout()

    buf = BytesIO()
    plt.savefig(buf, format="png")
    plt.close()
    buf.seek(0)

    return base64.b64encode(buf.getvalue()).decode("utf-8")


@app.post("/attendance")
async def get_attendance(request: Request):
    data = await request.json()
    srn = data.get("srn")
    password = data.get("password")

    if not srn or not password:
        return JSONResponse(status_code=400, content={"detail": "Missing SRN or password"})

    try:
        scraper = PESUAttendanceScraper(srn, password)
        scraper.login()
        attendance_data = scraper.fetch_attendance()
        scraper.logout()

        graph = generate_graph(attendance_data, BUNKABLE_THRESHOLD)

        formatted_attendance = [
            {
                "subject": SUBJECT_MAPPING.get(item[0], item[0]),
                "attended": int(item[2].split("/")[0]),
                "total": int(item[2].split("/")[1]),
                "percentage": round((int(item[2].split("/")[0]) / int(item[2].split("/")[1])) * 100, 2),
                "bunkable": AttendanceCalculator.calculate_bunkable(
                    int(item[2].split("/")[1]),
                    int(item[2].split("/")[0]),
                    BUNKABLE_THRESHOLD
                )
            }
            for item in attendance_data
        ]

        return {
            "logs": "Attendance fetched successfully",
            "attendance": formatted_attendance,
            "graph": graph
        }

    except Exception as e:
        logging.error(f"Error occurred: {str(e)}")
        return JSONResponse(status_code=500, content={"detail": str(e)})


@app.get("/")
async def serve_index():
    return FileResponse("index.html")

@app.get("/healthcheck")
async def healthcheck():
    return {"message": "Pong"}

@app.get("/favicon.ico")
async def favicon():
    return FileResponse("favicon.ico")

if __name__ == "__main__":
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
