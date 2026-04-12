"""Site-wide time formatting — everything user-facing is IST (Asia/Kolkata)."""

from datetime import datetime, timezone, timedelta
from typing import Optional

IST = timezone(timedelta(hours=5, minutes=30))

FMT_DATETIME = "%b %d, %Y %H:%M IST"
FMT_SHORT = "%b %d, %H:%M IST"
FMT_DATE = "%b %d, %Y"
FMT_MONTH_YEAR = "%b %Y"
FMT_FULL_MONTH_YEAR = "%B %Y"
FMT_DAY = "%Y-%m-%d"


def to_ist(dt: Optional[datetime]) -> Optional[datetime]:
    """Convert a naive-UTC or aware datetime to IST."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(IST)


def fmt_ist(dt: Optional[datetime], fmt: str = FMT_SHORT, default: str = "—") -> str:
    """Format a datetime in IST. Returns `default` if dt is None."""
    ist = to_ist(dt)
    return ist.strftime(fmt) if ist else default


def iso_utc_z(dt: Optional[datetime]) -> Optional[str]:
    """Serialize a naive-UTC datetime to an ISO string with trailing Z for JS parsing."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
