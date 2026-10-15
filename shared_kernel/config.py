"""Project settings: paths and values loaded from .env.

Model and API-key configuration is deliberately absent until Structure Guide Decision 1 is settled.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

# absolute paths to the project and its git-ignored data folder
PROJECT_ROOT = Path(__file__).parent.parent
DATA_DIR = PROJECT_ROOT / "data"
DB_PATH = DATA_DIR / "warren.db"
RAW_EDGAR_DIR = DATA_DIR / "raw" / "edgar"
REPORTS_DIR = DATA_DIR / "reports"

# real environment variables win over .env, so tests and CI can override anything
load_dotenv(PROJECT_ROOT / ".env", override=False)

PLACEHOLDER_USER_AGENT = "Your Name your.email@example.com"


class ConfigError(RuntimeError):
    """A required setting is missing or still holds its placeholder value."""


def sec_user_agent() -> str:
    """SEC requires a descriptive User-Agent (name and contact email) on every request."""
    value = os.environ.get("SEC_USER_AGENT", "").strip().strip('"')
    if not value or value == PLACEHOLDER_USER_AGENT or "@" not in value:
        raise ConfigError(
            'SEC_USER_AGENT must be set in .env as "Your Name your.email@example.com" '
            "(SEC rejects requests without a contact email)."
        )
    return value
