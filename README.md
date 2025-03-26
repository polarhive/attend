# PESU Attendance Tracker

Fetches attendance details from PESUAcademy, provides real-time logs, and supports multiple SRN formats and mappings.

## Setup

```sh
python -m venv .venv
source .venv/bin/activate  # On Windows use `venv\Scripts\activate`
pip install --upgrade pip
pip install -r requirements.txt
```

## Running the Application

```sh
python main.py
```

## Additing your branch

Update the `.env.example` file and open a PR

- Log in to [PESUAcademy](https://www.pesuacademy.com/Academy/s/studentProfilePESU).
- Open the developer tools by right-clicking on the page and selecting `Inspect Element` (Hotkey: `F12` or `CTRL+SHIFT+I`).
- Navigate to the `Network` tab and filter for all requests.
- Go to the attendance page and select your semester.
- Look for a network request to `/studentProfilePESUAdmin` and click on it.
- In the `Payload` or `Request` tab, locate the form data. 
- - It should look like: `controllerMode=6407&actionType=8&batchClassId=2660&menuId=660`
- - The `batchClassId` value `2660` is what you need to set in your `BATCH_CLASS_ID` environment variable.
- Define your `SUBJECT_MAPPING` in key-value pairs based on your subjects.

Example `.env` configuration:
```
# SRNs starting with "PES2UG23CS"
PES2UG23CS_BATCH_CLASS_ID=2660
PES2UG23CS_SUBJECT_MAPPING=UE23CS241B:DAA,UE23CS242B:OS,UE23CS251B:MPCA,UE23CS252B:CN,UE23MA241B:LA,UZ23UZ221B:CIE
```

## Contributions

Feel free to open issues and PRs for improvements and feature requests.
