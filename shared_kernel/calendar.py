"""The case calendar's day-end rule, shared by every data source.

A record counts on an as-of date if it was known before 24:00 New York time on that date. News
sightings (M5), market downloads and filing downloads (M7) all use this one rule, so it lives in
the kernel rather than in any one source's adapter (Decision 11, guardrail 1). The cut-off is
New York midnight, not the 16:00 close: a run between the close and midnight downloads again.
"""

from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

CASE_TZ = ZoneInfo("America/New_York")  # the case calendar, a named setting (guardrail 3)


def known_by(as_of: date, tz: ZoneInfo = CASE_TZ) -> datetime:
    """The UTC instant at which `as_of` ends in the case calendar: what is known before counts."""
    return datetime.combine(as_of + timedelta(days=1), time(0), tzinfo=tz).astimezone(UTC)
