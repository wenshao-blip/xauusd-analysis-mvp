"""Three fixed Beijing-time research sessions. No trading operations live here."""
from datetime import timedelta, timezone

BJ_OFFSET = timedelta(hours=8)
SLOTS = ((8, 30, 'asia'), (15, 0, 'europe'), (20, 0, 'us'))
LABELS = {'asia': '亚洲报告', 'europe': '欧洲报告', 'us': '美国报告'}
HORIZON = timedelta(hours=4)


def due(now, grace_minutes=10):
    """Return the active slot only during its bounded launch window."""
    local = now.astimezone(timezone(BJ_OFFSET))
    if local.weekday() >= 5:
        return None
    for hour, minute, name in SLOTS:
        start = local.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if start <= local < start + timedelta(minutes=grace_minutes):
            return name, start
    return None


def slot_name(now):
    item = due(now)
    return item[0] if item else None
