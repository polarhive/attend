import os
import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from datetime import datetime
import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)
load_dotenv()

class PESUAttendanceScraper:
    def __init__(self):
        self.session = requests.Session()
        self.base_url = "https://www.pesuacademy.com/Academy"
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.3',
            'X-Requested-With': 'XMLHttpRequest'
        }
        self.csrf_token = None

        # Load configurable variables from .env
        self.username = os.getenv('PESU_USERNAME')
        self.password = os.getenv('PESU_PASSWORD')
        self.bunkable_threshold = float(os.getenv('BUNKABLE_THRESHOLD', 75))
        self.batch_class_id = os.getenv('BATCH_CLASS_ID', '2660')
        self.controller_mode = os.getenv('CONTROLLER_MODE', '6407')
        self.action_type = os.getenv('ACTION_TYPE', '8')
        self.menu_id = os.getenv('MENU_ID', '660')

        if not self.username or not self.password:
            raise Exception("Username or password not found in .env file.")

    def get_csrf_token(self, html):
        soup = BeautifulSoup(html, 'html.parser')
        csrf_token = soup.find('input', {'name': '_csrf'})['value']
        logger.info("Extracted CSRF Token")
        return csrf_token

    def login(self):
        login_url = f"{self.base_url}/j_spring_security_check"
        login_page = f"{self.base_url}/"
        logger.info("Fetching login page...")
        response = self.session.get(login_page)
        self.csrf_token = self.get_csrf_token(response.text)
        
        login_data = {
            'j_username': self.username,
            'j_password': self.password,
            '_csrf': self.csrf_token
        }
        
        logger.info("Attempting login...")
        response = self.session.post(login_url, data=login_data, headers=self.headers)
        logger.info(f"Login response status code: {response.status_code}")
        
        if "Invalid username or password" in response.text:
            logger.error("Login failed. Check credentials.")
            raise Exception("Login failed: Invalid credentials")
        
        dashboard = self.session.get(f"{self.base_url}/s/studentProfilePESU")
        self.csrf_token = self.get_csrf_token(dashboard.text)

    def fetch_attendance(self):
        attendance_url = f"{self.base_url}/s/studentProfilePESUAdmin"
        
        payload = {
            'controllerMode': self.controller_mode,
            'actionType': self.action_type,
            'batchClassId': self.batch_class_id,
            'menuId': self.menu_id,
            '_csrf': self.csrf_token
        }
        logger.info("Prepared attendance payload")
        
        response = self.session.post(
            attendance_url,
            data=payload,
            headers={**self.headers, 'X-CSRF-Token': self.csrf_token}
        )
        logger.info(f"Attendance response status code: {response.status_code}")
        
        if response.status_code != 200:
            logger.error("Attendance request failed. Check payload or authentication.")
            raise Exception(f"Attendance request failed with status code {response.status_code}")
        
        return response.text

    def parse_attendance(self, html):
        logger.info("Parsing attendance data...")
        soup = BeautifulSoup(html, 'html.parser')
        table = soup.find('table', {'class': 'table'})
        
        if not table:
            logger.error("Attendance table not found in HTML.")
            raise Exception("Attendance table not found")
        
        headers = [th.text.strip() for th in table.find('thead').find_all('th')]
        rows = []
        
        for row in table.find('tbody').find_all('tr'):
            cells = [cell.text.strip() for cell in row.find_all('td')]
            rows.append(cells)
        
        logger.info("Successfully parsed attendance data")
        return headers, rows

    def calculate_bunkable(self, total_classes, attended_classes):
        """
        Calculate bunkable classes based on the threshold from .env
        """
        total_classes = int(total_classes.split('/')[1])
        attended_classes = int(attended_classes.split('/')[0])
        required_classes = int((self.bunkable_threshold / 100) * total_classes)
        bunkable_classes = attended_classes - required_classes
        return max(0, bunkable_classes)

    def save_to_csv(self, headers, data):
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"attendance_{timestamp}.csv"
        headers.append("Bunkable")
        
        with open(filename, 'w', encoding='utf-8') as f:
            f.write(','.join(headers) + '\n')
            for row in data:
                total_classes = row[2]
                attended_classes = row[2].split('/')[0]
                bunkable = self.calculate_bunkable(total_classes, attended_classes)
                row.append(str(bunkable))
                f.write(','.join(row) + '\n')
        
        logger.info(f"Attendance saved to {filename}")

    def run(self):
        try:
            logger.info("Starting scraper...")
            self.login()
            logger.info("Logged in successfully!")
            
            attendance_html = self.fetch_attendance()
            headers, data = self.parse_attendance(attendance_html)
            
            self.save_to_csv(headers, data)
            
        except Exception as e:
            logger.error(f"Error: {str(e)}")

if __name__ == "__main__":
    scraper = PESUAttendanceScraper()
    scraper.run()
