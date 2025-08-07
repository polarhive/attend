import re
import json
from pathlib import Path
from typing import Dict, List, Union, Any
from pydantic_settings import BaseSettings


class ConfigurationError(Exception):
    """Raised when configuration loading or validation fails."""

    pass


class MappingsConfig(BaseSettings):
    CONTROLLER_MODE: int
    ACTION_TYPE: int
    MENU_ID: int
    BATCH_CLASS_ID_MAPPING: Dict[str, Union[int, List[int]]]
    SUBJECT_MAPPING: Dict[str, str]

    def get_branch_config(self, srn: str) -> Dict[str, Any]:
        # Validate SRN format using comprehensive regex pattern
        pattern = (
            r"^PES(1UG23(CS|AM)|1UG24(CS|AM|BT|ME|EC)|"
            r"2UG23(CS|AM|EC)|2UG24(CS|AM|EC))\d{3}$"
        )
        match = re.match(pattern, srn)

        if not match:
            raise ValueError(
                f"Invalid SRN format: '{srn}'. Expected format: "
                "PES[1|2]UG[23|24][CS|AM|BT|ME|EC]XXX"
            )

        # Extract branch prefix from matched SRN
        branch_prefix = match.group(1)
        full_prefix = f"PES{branch_prefix}"

        # Retrieve batch class ID(s) for the branch
        batch_class_id = self.BATCH_CLASS_ID_MAPPING.get(full_prefix)

        if batch_class_id is None:
            available_branches = list(self.BATCH_CLASS_ID_MAPPING.keys())
            raise ValueError(
                f"Missing batch class ID for branch '{full_prefix}'. "
                f"Available branches: {available_branches}"
            )

        return {
            "controller_mode": self.CONTROLLER_MODE,
            "action_type": self.ACTION_TYPE,
            "menu_id": self.MENU_ID,
            "batchClassId": batch_class_id,
            "subject_mapping": self.SUBJECT_MAPPING,
        }


class AppSettings(BaseSettings):
    PORT: int = 8000
    LOG_LEVEL: str = "INFO"
    BUNKABLE_THRESHOLD: int = 75
    REQUEST_TIMEOUT_SECONDS: int = 5
    WEBSOCKET_PING_TIMEOUT: float = 15.0

    class Config:
        env_file = [".env", ".env.example"]
        env_file_encoding = "utf-8"
        case_sensitive = True


def load_mappings_config() -> MappingsConfig:
    config_path = Path(__file__).resolve().parent.parent.parent / "mapping.json"

    try:
        with config_path.open("r", encoding="utf-8") as file:
            config_data = json.load(file)
        return MappingsConfig(**config_data)
    except FileNotFoundError:
        raise ConfigurationError(
            f"Configuration file not found at: {config_path}. "
            "Please ensure mapping.json exists in the project root."
        )
    except json.JSONDecodeError as error:
        raise ConfigurationError(f"Invalid JSON format in configuration file: {error}")
    except Exception as error:
        raise ConfigurationError(f"Failed to load configuration: {error}")


def load_app_settings() -> AppSettings:
    try:
        return AppSettings()
    except Exception as error:
        raise ConfigurationError(f"Failed to load application settings: {error}")


# load config on module import
try:
    mappings = load_mappings_config()
    settings = load_app_settings()
except ConfigurationError as e:
    # Re-raise with additional context for easier debugging
    raise ConfigurationError(f"Failed to initialize configuration: {e}") from e
