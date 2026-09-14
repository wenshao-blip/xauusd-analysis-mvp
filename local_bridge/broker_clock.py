"""Explicit server-scoped timestamp correction; never infer offset from stale ticks."""
import json
from pathlib import Path
from datetime import timedelta

CONFIG = Path(__file__).with_name('broker_clock.json')


def offset(mt5):
    if not CONFIG.exists():
        return 0
    config = json.loads(CONFIG.read_text('utf-8'))
    account = mt5.account_info()
    if account is None or account.server != config['server']:
        raise RuntimeError('Broker clock configuration does not match connected server')
    seconds = config['offset_seconds']
    if type(seconds) is not int or abs(seconds) > 14*3600 or seconds % 900:
        raise ValueError('Invalid broker clock offset')
    return seconds


def candles(rates, seconds):
    rows = [{field: (value.item() if hasattr(value, 'item') else value)
             for field, value in zip(rates.dtype.names, row)} for row in rates]
    for row in rows:
        row['time'] -= seconds
    return rows


def interval(start, end, seconds):
    return start + timedelta(seconds=seconds), end + timedelta(seconds=seconds)
