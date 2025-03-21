# Attendance Bot

A Telegram bot that retrieves attendance details from PESUAcademy and provides a daily summary.

## Setup

```sh
python -m venv .venv
source .venv/bin/activate  # On Windows use `venv\Scripts\activate`
pip install --upgrade pip
pip install -r requirements.txt
```

## Usage

```sh
cp .env.example .env
# Populate .env with SRN, PASSWORD & TELEGRAM_BOT_TOKEN
python main.py
```

### Hosting the Backend (VPS/Render/etc.)

Create a systemd service file at `~/.config/systemd/user/pesu-attendance-bot.service`:

```
[Unit]
Description=PESU Attendance Bot
After=network-online.target

[Service]
Type=simple
WorkingDirectory=/home/user/.local/repos/atten
ExecStart=/home/user/.local/repos/atten/.venv/bin/python3 /home/user/.local/repos/atten/main.py
Restart=always
RestartSec=5
EnvironmentFile=/home/user/.local/repos/atten/.env

[Install]
WantedBy=default.target
```

```sh
systemctl --user daemon-reexec
systemctl --user enable pesu-attendance-bot.service --now
```

