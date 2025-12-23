import os
import sys
import logging
import signal
import json
import asyncio
from threading import Thread
from dotenv import load_dotenv
import aiohttp
import telebot
from telebot.async_telebot import AsyncTeleBot

# Plotting libs (use non-interactive backend)
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

# Load .env.local if it exists, otherwise fall back to .env
from pathlib import Path

if Path(".env.local").exists():
    load_dotenv(".env.local")
else:
    load_dotenv()

# Configuration
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_PESU_USERNAME = os.getenv("TELEGRAM_PESU_USERNAME")
TELEGRAM_PESU_PASSWORD = os.getenv("TELEGRAM_PESU_PASSWORD")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
TELEGRAM_GENERATE_GRAPH = str(os.getenv("TELEGRAM_GENERATE_GRAPH", "true")).lower() in (
    "1",
    "true",
    "yes",
    "on",
)
API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:10000")
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()

os.makedirs("data", exist_ok=True)
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler()],
)
logger = logging.getLogger(__name__)

# Validate required configuration
if not TELEGRAM_BOT_TOKEN:
    logger.error("TELEGRAM_BOT_TOKEN is not set. Please add it to your .env file.")
    sys.exit(1)

# If TELEGRAM_CHAT_ID is configured, validate PESU credentials are also set
if TELEGRAM_CHAT_ID:
    if not TELEGRAM_PESU_USERNAME or not TELEGRAM_PESU_PASSWORD:
        logger.error(
            "TELEGRAM_CHAT_ID is set but TELEGRAM_PESU_USERNAME and/or TELEGRAM_PESU_PASSWORD are missing."
        )
        logger.error(
            "Please add both TELEGRAM_PESU_USERNAME and TELEGRAM_PESU_PASSWORD to your .env file."
        )
        sys.exit(1)

bot = telebot.TeleBot(TELEGRAM_BOT_TOKEN)


class AttendanceAPIClient:
    """Client for unified attendance API"""

    def __init__(self, base_url: str = API_BASE_URL):
        self.base_url = base_url.rstrip("/")
        self.attendance_endpoint = f"{self.base_url}/api/attendance"
        self.healthcheck_endpoint = f"{self.base_url}/api/healthcheck"

    async def fetch_attendance(self, username: str, password: str) -> dict:
        """Fetch attendance from unified API"""
        async with aiohttp.ClientSession() as session:
            try:
                async with session.post(
                    self.attendance_endpoint,
                    json={"username": username, "password": password},
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as response:
                    data = await response.json()
                    return data
            except asyncio.TimeoutError:
                logger.error(f"API request timeout to {self.attendance_endpoint}")
                return {
                    "success": False,
                    "code": "timeout",
                    "message": "API request timed out",
                    "error": {
                        "type": "TimeoutError",
                        "details": "API request took too long",
                    },
                }
            except Exception as e:
                logger.error(f"API request failed: {e}")
                return {
                    "success": False,
                    "code": "api_error",
                    "message": f"API request failed: {str(e)}",
                    "error": {"type": "RequestError", "details": str(e)},
                }

    async def check_health(self) -> bool:
        """Check if API is healthy"""
        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(
                    self.healthcheck_endpoint, timeout=aiohttp.ClientTimeout(total=5)
                ) as response:
                    data = await response.json()
                    return data.get("success", False)
            except Exception as e:
                logger.warning(f"Health check failed: {e}")
                return False

    @staticmethod
    def parse_attendance(api_response: dict) -> str:
        """Parse API response and format for display.

        Optional threshold (in percent) is used to compute 'skippable' classes per subject.
        """

        def _calc_bunkable(attended: int, total: int, threshold_pct: int) -> int:
            if total <= 0:
                return 0
            try:
                if (attended / total) * 100 < threshold_pct:
                    return 0
            except Exception:
                return 0
            max_bunk = 0
            while (attended / (total + max_bunk)) * 100 >= threshold_pct:
                max_bunk += 1
            return max_bunk - 1 if max_bunk > 0 else 0

        # allow optional threshold argument via api_response wrapper or default env
        threshold = (
            api_response.get("_meta", {}).get("threshold")
            if isinstance(api_response.get("_meta"), dict)
            else None
        )
        if threshold is None:
            try:
                threshold = int(os.getenv("BUNKABLE_THRESHOLD", "75"))
            except Exception:
                threshold = 75

        if not api_response.get("success"):
            error_details = api_response.get("error", {}).get(
                "details", "Unknown error"
            )
            return f"❌ Error: {error_details}"

        attendance_data = api_response.get("data", {}).get("attendance", [])
        if not attendance_data:
            return "No attendance data found"

        message = "📊 Your Attendance:\n\n"
        for item in attendance_data:
            subject = item.get("subject", "Unknown")
            raw_data = item.get("raw_data", "0/0")

            try:
                attended, total = map(int, raw_data.split("/"))
                percentage = (attended / total * 100) if total > 0 else 0
                skippable = _calc_bunkable(attended, total, threshold)
                message += f"• {subject}: {raw_data} ({percentage:.1f}% | Skippable: {skippable})\n"
            except (ValueError, ZeroDivisionError):
                message += f"• {subject}: {raw_data}\n"

        return message


def is_authorized(chat_id: int) -> bool:
    """Check if chat_id is authorized"""
    return TELEGRAM_CHAT_ID and str(chat_id) == str(TELEGRAM_CHAT_ID)


@bot.message_handler(commands=["start", "help"])
def send_welcome(message):
    """Send welcome message"""
    bot.reply_to(
        message,
        (
            "👋 *Welcome to PESU Attendance Bot!*\n\n"
            "📋 *Available Commands:*\n"
            "`/get` - Get your attendance\n"
            "`/ping` - Check if bot is alive\n"
            "`/help` - Show this message\n\n"
            "🔒 *Setup Instructions:*\n"
            "� *Privacy Notice:*\n"
            "The bot does *not store any user data*. Your credentials are only used to fetch attendance and are never saved.\n\n"
            "Source: https://github.com/polarhive/attend"
        ),
        parse_mode="Markdown",
    )


@bot.message_handler(commands=["ping"])
def send_pong(message):
    """Respond to ping"""
    bot.reply_to(message, "🏓 Pong!")


@bot.message_handler(commands=["get"])
def send_attendance_report(message):
    chat_id = message.chat.id
    tokens = message.text.split()
    args = tokens[1:]

    # Optional threshold as first argument
    threshold_override = None
    if args and args[0].isdigit():
        threshold_override = int(args[0])
        args = args[1:]

    if len(args) >= 2:
        # Inline credentials provided: do not check TELEGRAM_CHAT_ID
        username = args[0]
        password = args[1]
    else:
        # Use stored credentials; require authorized chat
        username = TELEGRAM_PESU_USERNAME
        password = TELEGRAM_PESU_PASSWORD
        if not is_authorized(chat_id):
            bot.reply_to(
                message,
                (
                    "⚠️ Your chat ID is not authorized to use stored credentials.\n"
                    "To proceed, either: use `/get <username> <password>` with credentials, or set `TELEGRAM_CHAT_ID` in the bot's environment to allow stored credentials."
                ),
            )
            return

        if not username or not password:
            bot.reply_to(
                message,
                (
                    "❌ PESU credentials not configured for stored use.\n"
                    "Either set `TELEGRAM_PESU_USERNAME` and `TELEGRAM_PESU_PASSWORD` in `.env`, or call `/get <username> <password>` to provide them inline."
                ),
            )
            return

    # Fetch attendance
    bot.reply_to(message, "⏳ Fetching your attendance data...")

    async def fetch_and_send():
        try:
            client = AttendanceAPIClient()
            api_response = await client.fetch_attendance(username, password)

            # Format response
            attendance_text = AttendanceAPIClient.parse_attendance(api_response)

            # If success, generate a stacked bar graph like the web frontend
            if api_response.get("success"):
                attendance_data = api_response.get("data", {}).get("attendance", [])
                if attendance_data:
                    if not TELEGRAM_GENERATE_GRAPH:
                        logger.info(
                            "Graph generation disabled via TELEGRAM_GENERATE_GRAPH; skipping graph for %s",
                            chat_id,
                        )
                    else:
                        current_threshold = (
                            threshold_override
                            if threshold_override is not None
                            else int(os.getenv("BUNKABLE_THRESHOLD", "75"))
                        )
                        subjects = []
                        attended = []
                        total = []
                        bunked = []
                        threshold_marks = []

                        for item in attendance_data:
                            subject = item.get("subject", "Unknown")
                            raw = item.get("raw_data", "0/0")
                            try:
                                a, t = map(int, raw.split("/"))
                            except Exception:
                                a, t = 0, 0
                            subjects.append(subject)
                            attended.append(a)
                            total.append(t)
                            bunked.append(max(t - a, 0))
                            threshold_marks.append(
                                int((current_threshold / 100) * t) if t > 0 else 0
                            )

                        try:
                            plt.figure(figsize=(12, 8))
                            x = np.arange(len(subjects))
                            plt.bar(x, attended, color="seagreen")
                            plt.bar(x, bunked, bottom=attended, color="firebrick")
                            for i in range(len(subjects)):
                                plt.text(
                                    x[i],
                                    threshold_marks[i] + 0.5,
                                    f"{current_threshold}%: {threshold_marks[i]}",
                                    ha="center",
                                    fontsize=9,
                                )
                            new_labels = [
                                f"{sub}\n{att}/{tot}"
                                for sub, att, tot in zip(subjects, attended, total)
                            ]
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
                                with open(graph_path, "rb") as photo:
                                    bot.send_photo(chat_id, photo)
                                try:
                                    os.remove(graph_path)
                                except Exception:
                                    pass
                        except Exception as e:
                            logger.error(f"Graph generation failed: {e}")

            # Send text summary
            bot.send_message(chat_id, attendance_text, parse_mode="Markdown")

            if api_response.get("success"):
                logger.info(f"Sent attendance to {chat_id}")
            else:
                logger.warning(
                    f"API error for {chat_id}: {api_response.get('error', {}).get('details')}"
                )

        except Exception as e:
            logger.error(f"Error fetching attendance: {e}")
            bot.send_message(chat_id, f"❌ Error: {str(e)}")

    # Run async task
    try:
        asyncio.run(fetch_and_send())
    except Exception as e:
        logger.error(f"Failed to fetch attendance: {e}")
        bot.reply_to(message, f"❌ Error fetching attendance: {str(e)}")


def is_valid_user(chat_id):
    return str(chat_id) == TELEGRAM_CHAT_ID


def shutdown_handler(sig, frame):
    """Handle graceful shutdown"""
    logger.info("Shutting down bot gracefully...")
    sys.exit(0)


signal.signal(signal.SIGINT, shutdown_handler)
signal.signal(signal.SIGTERM, shutdown_handler)

if __name__ == "__main__":
    if not TELEGRAM_BOT_TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN not set in environment")
        sys.exit(1)

    logger.info("Starting Telegram bot...")
    logger.info(f"API Base URL: {API_BASE_URL}")
    logger.info(f"Graph generation enabled: {TELEGRAM_GENERATE_GRAPH}")

    try:
        bot.infinity_polling(none_stop=True, long_polling_timeout=60)
    except KeyboardInterrupt:
        logger.info("Bot interrupted")
    except Exception as e:
        logger.error(f"Bot error: {e}")
        sys.exit(1)
