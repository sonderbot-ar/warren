"""The fixed event taxonomy (M6, Decision 6), as data: one row per type, with its definition."""

import csv
from pathlib import Path

EVENT_TYPES_PATH = Path(__file__).parent / "event_types.csv"
NOT_ABOUT = "not_about_company"


def load_event_types(path: Path = EVENT_TYPES_PATH) -> dict[str, str]:
    with open(path, newline="", encoding="utf-8") as f:
        types = {r["event_type"]: r["definition"] for r in csv.DictReader(f)}
    if NOT_ABOUT not in types:
        raise ValueError(f"{path.name} must define {NOT_ABOUT}")
    return types
