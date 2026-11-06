"""Time arguments for management Oracle calls without changing duration."""


def oracle_time_arguments(seconds: int | float) -> dict[str, int | float]:
    """Express positive whole days as days=N; preserve precise partial days."""
    if seconds > 0 and seconds % 86400 == 0:
        return {"days": int(seconds // 86400)}
    return {"seconds": seconds}
