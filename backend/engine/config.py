import json
import os
import re

CONFIG_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../mapping.json"))
with open(CONFIG_PATH, "r") as file:
    config_data = json.load(file)

CONTROLLER_MODE = config_data["CONTROLLER_MODE"]
ACTION_TYPE = config_data["ACTION_TYPE"]
MENU_ID = config_data["MENU_ID"]
BATCH_CLASS_ID_MAPPING = config_data["BATCH_CLASS_ID_MAPPING"]
SUBJECT_MAPPING = config_data["SUBJECT_MAPPING"]

def get_branch_config(srn: str) -> dict:
    match = re.match(r"^(PES\d+[A-Z]{2}+\d+[A-Z]{2})", srn)
    if not match:
        raise ValueError("Invalid SRN format: branch prefix not found")

    branch_prefix = match.group(1)
    batch_class_id = BATCH_CLASS_ID_MAPPING.get(branch_prefix)

    if batch_class_id is None:
        raise ValueError(f"Missing batch class ID for {branch_prefix}")

    return {
        "controller_mode": CONTROLLER_MODE,
        "action_type": ACTION_TYPE,
        "menu_id": MENU_ID,
        "batchClassId": batch_class_id,
        "subject_mapping": SUBJECT_MAPPING
    }
