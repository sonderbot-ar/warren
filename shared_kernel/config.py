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


# Cloud sessions reserve ANTHROPIC_API_KEY for Claude Code's own sign-in, so Warren's key goes in
# under its own name there; a local .env may use either (backlog #95)
ANTHROPIC_KEY_NAMES = ("WARREN_ANTHROPIC_API_KEY", "ANTHROPIC_API_KEY")
ANTHROPIC_API_URL = "https://api.anthropic.com"


def anthropic_api_key() -> str:
    """The Anthropic key for the LLM steps (M6), first of ANTHROPIC_KEY_NAMES that is set.

    The value is never printed or logged."""
    for name in ANTHROPIC_KEY_NAMES:
        value = os.environ.get(name, "").strip().strip('"')
        if value:
            return value
    raise ConfigError(
        "No Anthropic key: set WARREN_ANTHROPIC_API_KEY (or ANTHROPIC_API_KEY). Create a key at "
        "console.anthropic.com (API keys), then put it in .env for local runs, or add "
        "WARREN_ANTHROPIC_API_KEY to the cloud environment's variables (the cloud keeps "
        "ANTHROPIC_API_KEY for Claude Code's own sign-in)."
    )


def anthropic_base_url() -> str:
    """Where Warren's model calls go: WARREN_ANTHROPIC_BASE_URL, else Anthropic's public API.

    Never the ambient ANTHROPIC_BASE_URL, which a Claude Code session sets for itself and which
    the SDK would otherwise follow with Warren's key (backlog #95)."""
    return os.environ.get("WARREN_ANTHROPIC_BASE_URL", "").strip() or ANTHROPIC_API_URL


@dataclass(frozen=True)
class NodeModel:
    model: str
    training_cutoff: date | None  # from the model card; None until checked (M6 Step 8)
    effort: str = "low"  # how hard the model thinks: low, medium, high (M6 Step 8)


# Training data cutoffs from Anthropic's models overview
# (platform.claude.com/docs/en/models/overview, read oct.31.2026): "Jun 2026" for both, month
# only, so the first of the month is stored; every Phase 1 case is dated 2025 or earlier, so each
# is before either cutoff (M6 Step 8)
HAIKU_5_5_CUTOFF = date(2026, 6, 1)
SONNET_5_5_CUTOFF = date(2026, 6, 1)

# one model per LLM node (Decision 1); the model id is stored on every call
NODE_MODELS: dict[str, NodeModel] = {
    "extract_events": NodeModel("claude-haiku-5-5", HAIKU_5_5_CUTOFF),
    "check_headlines": NodeModel("claude-haiku-5-5", HAIKU_5_5_CUTOFF),
    "propose_shocks": NodeModel("claude-sonnet-5-5", SONNET_5_5_CUTOFF, effort="medium"),
}


def model_effort(model: str) -> str:
    """The effort for a model, from the node that uses it (one effort per model)."""
    efforts = {m.effort for m in NODE_MODELS.values() if m.model == model}
    if len(efforts) != 1:
        raise ConfigError(f"model {model!r} needs exactly one effort, has {sorted(efforts)}")
    return efforts.pop()


def node_model(node: str) -> NodeModel:
    try:
        return NODE_MODELS[node]
    except KeyError:
        raise ConfigError(f"no model configured for LLM node {node!r}") from None
