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
# General settings
PORT=10000
BUNKABLE_THRESHOLD=75  # Attendance threshold in percentage
DEBUG_LEVEL=INFO
CONTROLLER_MODE=6407
ACTION_TYPE=8
MENU_ID=660

# For example, for SRNs starting with "PES2UG23CS"
PES2UG23CS_BATCH_CLASS_ID=2660
PES2UG23CS_SUBJECT_MAPPING=UE23CS241B:DAA,UE23CS242B:OS,UE23CS251B:MPCA,UE23CS252B:CN,UE23MA241B:LA,UZ23UZ221B:CIE

# For example, for SRNs starting with "PES2UG23AM"
PES2UG23AM_BATCH_CLASS_ID=2672
PES2UG23AM_SUBJECT_MAPPING=UE23CS241B:DAA,UE23CS242B:OS,UE23CS251B:MPCA,UE23CS252B:CN,UE23MA241B:LA,UZ23UZ221B:CIE
```

## Running the Application

```sh
python main.py
```

## Contributions

Feel free to open issues and PRs for improvements and feature requests.
