"""Jobright posted-time helpers (standalone, not shared with jobs app)."""
import re
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

TZ = ZoneInfo("America/New_York")
SECONDS_24H = 86400


def slugify_keyword(keyword):
    return re.sub(r"[^a-z0-9]+", "-", keyword.lower()).strip("-")


def parse_publish_time(publish_time_str):
    if not publish_time_str:
        return None
    try:
        return int(datetime.strptime(publish_time_str.strip(), "%Y-%m-%d %H:%M:%S").replace(tzinfo=TZ).timestamp())
    except ValueError:
        return None


def is_within_24h_from_publish(publish_time_str, publish_desc=""):
    desc = (publish_desc or "").lower()
    if "day" in desc:
        m = re.search(r"(\d+)\s*day", desc)
        if m and int(m.group(1)) >= 2:
            return False
    if "week" in desc or "month" in desc:
        return False

    ts = parse_publish_time(publish_time_str)
    if ts is None:
        return False
    return int(time.time()) - ts <= SECONDS_24H


def format_posted_time(ts):
    if not ts:
        return "Recently"
    diff = max(0, int(time.time()) - int(ts))
    if diff > SECONDS_24H:
        return None

    post_dt = datetime.fromtimestamp(int(ts), tz=TZ)
    now_dt = datetime.fromtimestamp(int(time.time()), tz=TZ)
    time_str = post_dt.strftime("%I:%M %p").lstrip("0")

    if diff < 60:
        return f"Just now · Today {time_str}"
    if diff < 3600:
        m = diff // 60
        rel = f"{m} min ago"
        if post_dt.date() == now_dt.date():
            return f"{rel} · Today {time_str}"
        if post_dt.date() == (now_dt.date() - timedelta(days=1)):
            return f"{rel} · Yesterday {time_str}"
        return rel

    h = diff // 3600
    rel = f"{h} hour{'s' if h != 1 else ''} ago"
    if post_dt.date() == now_dt.date():
        return f"{rel} · Today {time_str}"
    if post_dt.date() == (now_dt.date() - timedelta(days=1)):
        return f"Yesterday · {time_str}"
    return f"{rel} · {post_dt.strftime('%b %d')} {time_str}"
