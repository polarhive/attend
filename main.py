import os
import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from fastapi import FastAPI
import logging
import telebot
from datetime import datetime
from threading import Thread
import matplotlib.pyplot as plt

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
PESU_USERNAME = os.getenv("PESU_USERNAME")
PESU_PASSWORD = os.getenv("PESU_PASSWORD")

bot = telebot.TeleBot(TELEGRAM_BOT_TOKEN)
app = FastAPI()

SUBJECT_MAPPING = {
    'UE23CS241B': 'DAA',
    'UE23CS242B': 'OS',
    'UE23CS251B': 'MPCA',
    'UE23CS252B': 'CN',
    'UE23MA241B': 'LA',
    'UZ23UZ221B': 'CIE'
}

class PESUAttendanceScraper:
    def __init__(self):
        self.session = requests.Session()
        self.base_url = "https://www.pesuacademy.com/Academy"
        self.username = PESU_USERNAME
        self.password = PESU_PASSWORD
        self.csrf_token = None

    def get_csrf_token(self, html):
        soup = BeautifulSoup(html, 'html.parser')
        csrf_input = soup.find('input', {'name': '_csrf'})
        if csrf_input:
            return csrf_input['value']
        raise Exception("CSRF token not found")

    def login(self):
        login_page = f"{self.base_url}/"
        login_url = f"{self.base_url}/j_spring_security_check"
        response = self.session.get(login_page)
        self.csrf_token = self.get_csrf_token(response.text)

        payload = {
            'j_username': self.username,
            'j_password': self.password,
            '_csrf': self.csrf_token
        }

        login_response = self.session.post(login_url, data=payload)

        if "Invalid username or password" in login_response.text:
            raise Exception("Login failed: Invalid credentials")

    def logout(self):
        logout_url = f"{self.base_url}/logout"
        self.session.get(logout_url)

    def fetch_attendance(self):
        dashboard = self.session.get(f"{self.base_url}/s/studentProfilePESU")
        self.csrf_token = self.get_csrf_token(dashboard.text)

        attendance_url = f"{self.base_url}/s/studentProfilePESUAdmin"
        payload = {
            'controllerMode': '6407',
            'actionType': '8',
            'batchClassId': '2660',
            'menuId': '660',
            '_csrf': self.csrf_token
        }

        response = self.session.post(attendance_url, data=payload)

        if response.status_code != 200:
            raise Exception("Failed to fetch attendance")

        return self.parse_attendance(response.text)

    def parse_attendance(self, html):
        soup = BeautifulSoup(html, 'html.parser')
        table = soup.find('table', {'class': 'table'})

        if not table:
            raise Exception("Attendance table not found")

        attendance_data = []
        for row in table.find('tbody').find_all('tr'):
            columns = [cell.text.strip() for cell in row.find_all('td')]
            attendance_data.append(columns)

        return attendance_data

    def calculate_bunkable(self, total_classes, attended_classes, threshold=75):
        total_classes = int(total_classes)
        attended_classes = int(attended_classes)

        max_bunkable = 0
        while True:
            if ((attended_classes / (total_classes + max_bunkable)) * 100) < threshold:
                break
            max_bunkable += 1

        return max_bunkable - 1

@app.get('/attendance')
def get_attendance():
    return {"status": "API is running"}

@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    bot.reply_to(message, "Welcome to PESU Attendance Bot!\nUse /get to check your attendance and visualize bunkable classes.")

@bot.message_handler(commands=['get'])
def send_attendance(message):
    try:
        scraper = PESUAttendanceScraper()
        scraper.login()
        data = scraper.fetch_attendance()
        scraper.logout()

        subjects = []
        attended = []
        total = []
        bunked = []
        response = "📊 Your Attendance:\n"

        for item in data:
            subject_name = SUBJECT_MAPPING.get(item[0], item[0])
            attended_classes, total_classes = map(int, item[2].split("/"))
            bunkable = scraper.calculate_bunkable(total_classes, attended_classes)
            percentage = (attended_classes / total_classes) * 100

            subjects.append(subject_name)
            attended.append(attended_classes)
            total.append(total_classes)
            bunked.append(total_classes - attended_classes)

            response += f"{subject_name}: {item[2]} ({percentage:.1f}% | Bunkable: {bunkable})\n"

        import matplotlib
        matplotlib.use('Agg')

        plt.figure(figsize=(12, 8))

        for i, subject in enumerate(subjects):
            plt.bar(f"{subject}\n{attended[i]}/{total[i]}", attended[i], color='seagreen', label='Attended' if i == 0 else "")
            plt.bar(f"{subject}\n{attended[i]}/{total[i]}", bunked[i], bottom=attended[i], color='firebrick', label='Bunked' if i == 0 else "")

        plt.xlabel("Subjects")
        plt.ylabel("Classes")
        plt.title("Attendance and Bunkable Classes")
        plt.xticks(rotation=45, ha="right")
        plt.legend()

        os.makedirs("data", exist_ok=True)
        graph_path = f"data/attendance_{message.chat.id}_{datetime.now().strftime('%Y%m%d%H%M%S')}.png"

        plt.tight_layout()
        plt.savefig(graph_path)
        plt.close()

        with open(graph_path, 'rb') as photo:
            bot.send_photo(message.chat.id, photo)

        bot.reply_to(message, response)

    except Exception as e:
        bot.reply_to(message, f"❌ Error: {str(e)}")

def start_fastapi():
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

if __name__ == '__main__':
    logger.info("Starting FastAPI and Telegram bot...")

    Thread(target=start_fastapi).start()
    bot.polling()
