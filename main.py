import os
import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.responses import RedirectResponse
import logging
import telebot
from datetime import datetime
from threading import Thread
import matplotlib.pyplot as plt
import signal
import sys
import numpy as np

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
TELEGRAM_BOT_USERNAME = os.getenv("TELEGRAM_BOT_USERNAME", "your_bot_username")

log_file = "data/pesu_bot.log"
os.makedirs("data", exist_ok=True)

logging.basicConfig(level=getattr(logging, DEBUG_LEVEL, logging.INFO), 
                    format="%(asctime)s - %(levelname)s - %(message)s", 
                    handlers=[logging.FileHandler(log_file), logging.StreamHandler()])
logger = logging.getLogger(__name__)

bot = telebot.TeleBot(TELEGRAM_BOT_TOKEN)
app = FastAPI()

# Additional app for redirect and healthcheck on port 3000
app_redirect = FastAPI()

class AttendanceCalculator:
    @staticmethod
    def calculate_bunkable(total_classes, attended_classes, threshold):
        max_bunkable = 0
        while ((attended_classes / (total_classes + max_bunkable)) * 100 >= threshold):
            max_bunkable += 1
        return max_bunkable - 1

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


@app.get('/attendance')
def get_attendance():
    return {"status": "API is running"}

def is_valid_user(chat_id):
    return str(chat_id) == CHAT_ID

@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    bot.reply_to(message, (
        "👋 *Welcome to PESU Attendance Bot!*\n"
        "Use `/get [threshold] [PESU_USERNAME PESU_PASSWORD]` to check your attendance.\n\n"
        "🔒 *Privacy Notice:* \n"
        "The bot does *not store any user data*. When you use the `/get` command, your credentials and attendance information are processed in memory and *never saved*.\n\n"
        "✅ You can self-host or verify the source code here: https://github.com/polarhive/attend"
    ), parse_mode="Markdown")

@bot.message_handler(commands=['ping'])
def send_pong(message):
    bot.reply_to(message, "Pong!")

@bot.message_handler(commands=['get'])
def send_attendance_report(message):
    chat_id = str(message.chat.id)
    tokens = message.text.split()
    args = tokens[1:]
    threshold_override = None
    username = None
    password = None

    if args and args[0].isdigit():
        threshold_override = int(args[0])
        args = args[1:]
    if len(args) >= 2:
        username = args[0]
        password = args[1]
    else:
        if chat_id == CHAT_ID:
            username = PESU_USERNAME
            password = PESU_PASSWORD
        else:
            bot.reply_to(message, "Invalid format. Use: /get [threshold] PESU_USERNAME PESU_PASSWORD")
            return

    current_threshold = threshold_override if threshold_override is not None else BUNKABLE_THRESHOLD
    bot.reply_to(message, "Fetching data...")
    try:
        scraper = PESUAttendanceScraper(username, password)
        scraper.login()
        data = scraper.fetch_attendance()
        scraper.logout()

        subjects, attended, total, bunked, threshold_marks = [], [], [], [], []
        response = "\U0001F4CA Your Attendance:\n"
        for item in data:
            subject_name = SUBJECT_MAPPING.get(item[0], item[0])
            attended_classes, total_classes = map(int, item[2].split("/"))
            bunkable = AttendanceCalculator.calculate_bunkable(total_classes, attended_classes, current_threshold)
            threshold_mark = AttendanceCalculator.calculate_threshold_mark(total_classes, current_threshold)
            percentage = (attended_classes / total_classes) * 100    
            subjects.append(subject_name)
            attended.append(attended_classes)
            total.append(total_classes)
            bunked.append(total_classes - attended_classes)
            threshold_marks.append(threshold_mark)
            response += f"{subject_name}: {item[2]} ({percentage:.1f}% | Bunkable: {bunkable})\n"

        logger.info("Generating attendance graph...")
        plt.figure(figsize=(12, 8))
        x = np.arange(len(subjects))
        plt.bar(x, attended, color='seagreen')
        plt.bar(x, bunked, bottom=attended, color='firebrick')
        for i, subject in enumerate(subjects):
            plt.text(x[i], threshold_marks[i] + 1, f"{current_threshold}%: {threshold_marks[i]}", ha='center', fontsize=9)
        new_labels = [f"{sub}\n{att}/{tot}" for sub, att, tot in zip(subjects, attended, total)]
        plt.xticks(x, new_labels, rotation=45, ha="right")
        plt.xlabel("Subjects")
        plt.ylabel("Classes")
        plt.title(f"Attendance ({current_threshold}% Threshold)")
        plt.legend(["Attended", "Bunked"])
        plt.tight_layout()
        graph_path = f"data/attendance_{chat_id}.png"
        plt.savefig(graph_path)
        plt.close()
        if os.path.exists(graph_path):
            with open(graph_path, 'rb') as photo:
                bot.send_photo(chat_id, photo)
            os.remove(graph_path)
        else:
            bot.send_message(chat_id, "Error: Graph could not be generated.")
        bot.send_message(chat_id, response)
    except Exception as e:
        logger.error(f"Error occurred: {e}")
        bot.reply_to(message, f"Error: {str(e)}")


@app_redirect.get('/')
def redirect_to_telegram():
    return RedirectResponse(url=f"https://t.me/{TELEGRAM_BOT_USERNAME}")

@app_redirect.get('/healthcheck')
def healthcheck():
    return "Pong!"

def start_fastapi():
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

def start_redirect_server():
    import uvicorn
    uvicorn.run(app_redirect, host="0.0.0.0", port=3000)

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
    Thread(target=start_redirect_server).start()
    while True:
        try:
            bot.polling(none_stop=True, long_polling_timeout=60)
        except Exception as e:
            logger.error(f"Bot crashed with error: {e}")
            restart_bot()
