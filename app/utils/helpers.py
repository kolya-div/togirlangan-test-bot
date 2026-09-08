from datetime import datetime, timedelta, timezone


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def format_timedelta(td: timedelta) -> str:
    hours, remainder = divmod(int(td.total_seconds()), 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:02}:{minutes:02}:{seconds:02}"


def format_filename(name: str) -> str:
    return "".join(
        c for c in name if c.isalnum() or c in "._-"
    ).strip()