"""Project settings: paths, keys and the node-to-model map (Structure Guide Decision 1).

Keys are read here and nowhere else: from the environment for cloud runs, from .env for local runs.
"""

import os
from dataclasses import dataclass
from datetime import date
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


def anthropic_api_key() -> str:
    """The Anthropic key for the LLM steps (M6). The value is never printed or logged."""
    value = os.environ.get("ANTHROPIC_API_KEY", "").strip().strip('"')
    if not value:
        raise ConfigError(
            "ANTHROPIC_API_KEY is not set. Create a key at console.anthropic.com (API keys), then "
            "put ANTHROPIC_API_KEY=... in .env for local runs, or add it to the cloud "
            "environment's variables."
        )
    return value


@dataclass(frozen=True)
class NodeModel:
    model: str
    training_cutoff: date | None  # from the model card; None until checked (M6 Step 8)


# one model per LLM node (Decision 1); the model id is stored on every call
NODE_MODELS: dict[str, NodeModel] = {
    "extract_events": NodeModel("claude-haiku-5-5", None),
    "check_headlines": NodeModel("claude-haiku-5-5", None),
    "propose_shocks": NodeModel("claude-sonnet-5-5", None),
}


def node_model(node: str) -> NodeModel:
    try:
        return NODE_MODELS[node]
    except KeyError:
        raise ConfigError(f"no model configured for LLM node {node!r}") from None
