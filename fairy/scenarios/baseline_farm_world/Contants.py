from datetime import datetime, timezone, timedelta


LOCAL_TIMEZONE = timezone(timedelta(hours=8))
DETAILED_BRIEFING = True


def local_timestamp(
    year: int,
    month: int,
    day: int,
    hour: int,
    minute: int = 0,
    second: int = 0,
) -> float:
    """Return an epoch timestamp for local farm time (UTC+8)."""
    return datetime(
        year, month, day, hour, minute, second, tzinfo=LOCAL_TIMEZONE
    ).timestamp()
