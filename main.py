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
import signal
import sys

load_dotenv()
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
PESU_USERNAME = os.getenv("PESU_USERNAME")
PESU_PASSWORD = os.getenv("PESU_PASSWORD")
BATCH_CLASS_ID = os.getenv("BATCH_CLASS_ID", "2660")
CONTROLLER_MODE = os.getenv("CONTROLLER_MODE", "6407")
ACTION_TYPE = os.getenv("ACTION_TYPE", "8")
MENU_ID = os.getenv("MENU_ID", "660")
CHAT_ID = os.getenv("CHAT_ID")
DEBUG_LEVEL = os.getenv("DEBUG_LEVEL", "INFO").upper()
BUNKABLE_THRESHOLD = int(os.getenv("BUNKABLE_THRESHOLD", "75"))
SUBJECT_MAPPING = dict(item.split(":") for item in os.getenv("SUBJECT_MAPPING", "").split(","))

log_file = "data/pesu_bot.log"
os.makedirs("data", exist_ok=True)

logging.basicConfig(level=getattr(logging, DEBUG_LEVEL, logging.INFO), format="%(asctime)s - %(levelname)s - %(message)s", handlers=[
    logging.FileHandler(log_file),
    logging.StreamHandler()
])
logger = logging.getLogger(__name__)

bot = telebot.TeleBot(TELEGRAM_BOT_TOKEN)
app = FastAPI()


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
        logger.info(f"Logging into PESU Academy with user: {self.username}")
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
        logger.info("Logging out of PESU Academy...")
        self.session.get(f"{self.base_url}/logout")

    def fetch_attendance(self):
        logger.info("Fetching attendance data...")
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

        return self.parse_attendance(response.text)

    def parse_attendance(self, html):
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

    def calculate_bunkable(self, total_classes, attended_classes, threshold=75):
        max_bunkable = 0
        while ((attended_classes / (total_classes + max_bunkable)) * 100) >= threshold:
            max_bunkable += 1
        return max_bunkable - 1

    def calculate_75_percent_mark(self, total_classes, threshold=75):
        return int((threshold / 100) * total_classes)


@app.get('/attendance')
def get_attendance():
    return {"status": "API is running"}


def is_valid_user(chat_id):
    return str(chat_id) == CHAT_ID


@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    bot.reply_to(message, "Welcome to PESU Attendance Bot!\nUse /get PESU_USERNAME PESU_PASSWORD to check your attendance.")


@bot.message_handler(commands=['ping'])
def send_pong(message):
    bot.reply_to(message, "Pong!")


@bot.message_handler(commands=['get'])
def send_attendance_report(message):
    chat_id = str(message.chat.id)

    if chat_id == CHAT_ID:
        username = PESU_USERNAME
        password = PESU_PASSWORD
    else:
        try:
            _, username, password = message.text.split(" ", 2)
        except ValueError:
            bot.reply_to(message, "Invalid format. Use: /get PESU_USERNAME PESU_PASSWORD")
            return

    bot.reply_to(message, "Fetching data...")

    try:
        scraper = PESUAttendanceScraper(username, password)
        scraper.login()
        data = scraper.fetch_attendance()
        scraper.logout()

        subjects, attended, total, bunked, seventy_five_marks = [], [], [], [], []
        response = "\U0001F4CA Your Attendance:\n"

        for item in data:
            subject_name = SUBJECT_MAPPING.get(item[0], item[0])
            attended_classes, total_classes = map(int, item[2].split("/"))
            bunkable = scraper.calculate_bunkable(total_classes, attended_classes, BUNKABLE_THRESHOLD)
            percentage = (attended_classes / total_classes) * 100
            seventy_five_mark = scraper.calculate_75_percent_mark(total_classes, BUNKABLE_THRESHOLD)

            subjects.append(subject_name)
            attended.append(attended_classes)
            total.append(total_classes)
            bunked.append(total_classes - attended_classes)
            seventy_five_marks.append(seventy_five_mark)

            response += f"{subject_name}: {item[2]} ({percentage:.1f}% | Bunkable: {bunkable})\n"

        logger.info("Generating attendance graph...")
        plt.figure(figsize=(12, 8))

        for i, subject in enumerate(subjects):
            plt.bar(f"{subject}\n{attended[i]}/{total[i]}", attended[i], color='seagreen', label='Attended' if i == 0 else "")
            plt.bar(f"{subject}\n{attended[i]}/{total[i]}", bunked[i], bottom=attended[i], color='firebrick', label='Bunked' if i == 0 else "")
            plt.text(i, seventy_five_marks[i] + 1, f"75%: {seventy_five_marks[i]}", ha='center', fontsize=9)

        plt.xlabel("Subjects")
        plt.ylabel("Classes")
        plt.title(f"Attendance (75% Threshold)")
        plt.xticks(rotation=45, ha="right")
        plt.legend(["Attended", "Bunked"])
        plt.tight_layout()

        graph_path = f"data/attendance_{CHAT_ID}.png"
        plt.savefig(graph_path)
        plt.close()

        logger.info("Sending attendance graph...")
        with open(graph_path, 'rb') as photo:
            bot.send_photo(CHAT_ID, photo)

        bot.send_message(chat_id, response)

    except Exception as e:
        logger.error(f"Error occurred: {e}")
        bot.reply_to(message, f"Error: {str(e)}")


def start_fastapi():
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)


def restart_bot():
    logger.error("Restarting bot...")
    os.execv(sys.executable, ['python'] + sys.argv)


def shutdown_handler(sig, frame):
    logger.info("Shutting down bot gracefully...")
    sys.exit(0)


signal.signal(signal.SIGINT, shutdown_handler)
signal.signal(signal.SIGTERM, shutdown_handler)

if __name__ == '__main__':
    logger.info("Starting FastAPI and Telegram bot...")
    Thread(target=start_fastapi).start()
    while True:
        try:
            bot.polling(none_stop=True, long_polling_timeout=60)
        except Exception as e:
            logger.error(f"Bot crashed with error: {e}")
            restart_bot()
