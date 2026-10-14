# PESU Attendance Tracker

> [polarhive.net/attend](https://polarhive.net/attend)

Fetches attendance details from PESUAcademy, provides real-time logs, and supports multiple SRN formats and mappings.

![Cron job status](https://api.cron-job.org/jobs/5967927/b0792bab02dda80d/status-7.svg)

## Getting Started

Download [uv](https://docs.astral.sh/uv/getting-started/installation).
Copy `.env.example` to `.env` and fill in values.

```sh
uv run main.py
```

### API

```bash
curl -X POST https://attendanceisallyouneed.vercel.app/api/attendance \
  -H "Content-Type: application/json" \
  -d '{"username": "PES2UG23CS001", "password": "your_password"}'
```

- `POST /api/attendance` body `{username, password, batch_id?}`.
  Returns formatted attendance.
- `POST /api/semesters` body `{username, password}`. Returns available
  semesters.
- `GET /api/healthcheck` returns service status.

## Deploy

- Vercel: `api/index.py` re-exports the app, and the static frontend
  deploys as files. `vercel.json` holds the full configuration.
- The Telegram bot needs an always-on host and cannot run on Vercel. Set
  `TELEGRAM_BOT_TOKEN` with `ENABLE_BACKEND_TELEGRAM=true`, or run
  `frontend/telegram/tg_bot.py` directly.

## Contributions

Feel free to open issues and PRs for improvements and feature requests.
