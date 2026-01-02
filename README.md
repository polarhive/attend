# PESU Attendance Tracker

> [polarhive.net/attend](https://polarhive.net/attend)

Fetches attendance details from PESUAcademy, provides real-time logs, and supports multiple SRN formats and mappings.

![Cron job status](https://api.cron-job.org/jobs/5967927/b0792bab02dda80d/status-7.svg)

## Getting Started

Download [uv](https://docs.astral.sh/uv/getting-started/installation)

```sh
uv run main.py
```

### API

```bash
curl -X POST https://attendanceisallyouneed.vercel.app/api/attendance \
  -H "Content-Type: application/json" \
  -d '{"username": "PES2UG23CS001", "password": "your_password"}'
```

## Contributions

Feel free to open issues and PRs for improvements and feature requests.
