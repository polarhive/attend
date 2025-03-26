# PESU Attendance Tracker

Fetches attendance details from PESUAcademy, provides real-time logs, and supports multiple SRN formats and mappings.

## Setup

```sh
python -m venv .venv
source .venv/bin/activate  # On Windows use `venv\Scripts\activate`
pip install --upgrade pip
pip install -r requirements.txt
```

### Environment Configuration

1. Copy the example environment file:

```sh
cp .env.example .env
```

2. Add subjects for your branch: PES2UG23CS tested so-far

```
PORT=8000
BUNKABLE_THRESHOLD=75
DEBUG_LEVEL=INFO

# For example, for SRNs starting with "PES2UG23CS"
PES2UG23CS_CONTROLLER_MODE=6407
PES2UG23CS_ACTION_TYPE=8
PES2UG23CS_MENU_ID=660
PES2UG23CS_SUBJECT_MAPPING=UE23CS241B:DAA,UE23CS242B:OS,UE23CS251B:MPCA,UE23CS252B:CN,UE23MA241B:LA,UZ23UZ221B:CIE

# For example, for SRNs starting with "PES2UG23AM"
PES2UG23AM_CONTROLLER_MODE=?
PES2UG23AM_ACTION_TYPE=?
PES2UG23AM_MENU_ID=?
PES2UG23AM_SUBJECT_MAPPING=UE23CS241B:DAA,UE23CS242B:OS,UE23CS251B:MPCA,UE23CS252B:CN,UE23MA241B:LA,UZ23UZ221B:CIE
```

## Running the Application

```sh
python main.py
```

## Contributions

Feel free to open issues and PRs for improvements and feature requests.
