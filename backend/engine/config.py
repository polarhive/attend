import os
import re

def parse_subject_mapping(mapping_str: str) -> dict:
    mapping = {}
    if mapping_str:
        for item in mapping_str.split(","):
            if ":" in item:
                key, value = item.split(":", 1)
                mapping[key.strip()] = value.strip()
    return mapping

def get_branch_config(srn: str) -> dict:
    # First 9 characters, e.g. "PES2UG23CS"
    srn = srn.upper()
    match = re.match(r"^(PES\d+[A-Z]+\d+[A-Z]{2})", srn)
    if not match:
        raise ValueError("Invalid SRN format: branch prefix not found")
    branch_prefix = match.group(1)
    
    controller_mode = os.getenv(f"CONTROLLER_MODE", "6407")
    action_type = os.getenv(f"ACTION_TYPE", "8")
    menu_id = os.getenv(f"MENU_ID", "660")

    # stuff that changes based on branch
    batchClassId = os.getenv(f"{branch_prefix}_BATCH_CLASS_ID", "")
    subject_mapping_str = os.getenv(f"{branch_prefix}_SUBJECT_MAPPING", "")

    if not all([controller_mode, action_type, menu_id, subject_mapping_str]):
        raise ValueError(f"Missing branch-specific configuration for {branch_prefix}")

    return {
        "controller_mode": controller_mode,
        "action_type": action_type,
        "menu_id": menu_id,
        "batchClassId": batchClassId,
        "subject_mapping": parse_subject_mapping(subject_mapping_str)
    }
