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

### Adding your batch/SRN

Fork this repo, update [`frontend/web/mapping.json`](https://github.com/polarhive/attend/blob/main/frontend/web/mapping.json) to open a PR.

1. Open your Browser's Developer Tools: (Right-Click → Inspect Element / `F12` / `Ctrl+Shift+I`) and go to the Network tab (show all requests).
2. Sign-in to [PESUAcademy](https://www.pesuacademy.com/Academy/s/studentProfilePESU)
3. Open the attendance page and select your semester.
4. Find the request to `/studentProfilePESUAdmin` and view it.
5. Look at your Payload/Request section, then look at form data for `controllerMode=6407&actionType=8&batchClassId=2660&menuId=660`
6. Note the `batchClassId` value (ex: `2660`), this is your `BATCH_CLASS_ID` key that you need to add to `mapping.json`
7. Optionally, add `SUBJECT_MAPPING` for your subjects.
8. Save the changes to [`frontend/web/mapping.json`](https://github.com/polarhive/attend/blob/main/frontend/web/mapping.json) and submit a pull request.


## Contributions

Feel free to open issues and PRs for improvements and feature requests.
