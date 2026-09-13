"""Validate each forecast's own closed M5 path; never substitute a later quote."""
import math
from datetime import datetime, timezone

REASONS = {
    'history_error': '历史行情读取失败，等待重试',
    'missing_start': '缺少起始行情，等待补齐',
    'missing_end': '缺少到期行情，可能休市或数据未同步',
    'history_gap': '区间内行情不连续，休市或缺失尚未核实',
    'invalid_bar': '行情数值或时间异常，等待核查',
    'settled': '已按有效期完成结算',
    'pending_check': '等待逐条核查',
}


class BudgetDeferred(Exception):
    pass


def initialize(db):
    db.execute('''CREATE TABLE IF NOT EXISTS settlement_audit (
        ledger TEXT NOT NULL, prediction_id TEXT NOT NULL,
        checked_at TEXT NOT NULL, reason TEXT NOT NULL, attempts INTEGER NOT NULL,
        bars INTEGER NOT NULL, PRIMARY KEY(ledger,prediction_id))''')
    db.commit()


def record(db, ledger, pid, now, reason, count=0):
    db.execute('''INSERT INTO settlement_audit VALUES (?,?,?,?,1,?)
        ON CONFLICT(ledger,prediction_id) DO UPDATE SET checked_at=excluded.checked_at,
        reason=excluded.reason, attempts=settlement_audit.attempts+1, bars=excluded.bars''',
        (ledger, pid, now.isoformat(timespec='seconds'), reason, count))
    db.commit()


def path_for(history, start, end):
    """Only complete 5-minute bars wholly inside [start,end]; all gaps stay pending."""
    try:
        raw = history(start, end)
    except BudgetDeferred:
        raise
    except Exception:
        return None, 'history_error', 0
    first = math.ceil(start.timestamp()/300)*300
    last = math.floor(end.timestamp()/300)*300-300
    # Valuation uses the last complete M5 before expiry (at most <5 minutes old).
    if last < first:
        return None, 'missing_end', 0
    try:
        bars = {}
        for b in raw:
            t = float(b['time'])
            if not math.isfinite(t):
                return None, 'invalid_bar', 0
            if not first <= t <= last:
                continue
            high, low, close = (float(b[k]) for k in ('high','low','close'))
            if (t % 300 or not all(math.isfinite(v) and v > 0 for v in (high,low,close))
                    or not low <= close <= high):
                return None, 'invalid_bar', len(bars)
            values = (high, low, close)
            if t in bars and bars[t] != values:
                return None, 'invalid_bar', len(bars)
            bars[t] = values
    except (TypeError, KeyError, ValueError, OverflowError):
        return None, 'invalid_bar', 0
    if first not in bars:
        return None, 'missing_start', len(bars)
    if last not in bars:
        return None, 'missing_end', len(bars)
    if len(bars) != int((last-first)/300)+1:
        return None, 'history_gap', len(bars)
    return {'close': bars[last][2], 'high': max(b[0] for b in bars.values()),
            'low': min(b[1] for b in bars.values())}, 'settled', len(bars)


def summary(db, now=None):
    now=now or datetime.now(timezone.utc)
    tables={r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    rows=[]
    for table,ledger,condition in [('predictions','predictions',"p.status='open'"),
                                  ('shadow_forecasts','shadow',"p.kind!='draft' AND p.settlement IS NULL")]:
        if table not in tables:
            continue
        rows += db.execute(f'''SELECT p.id prediction_id,p.valid_until,a.checked_at,a.reason,a.attempts,
            ? ledger FROM {table} p LEFT JOIN settlement_audit a ON a.ledger=? AND a.prediction_id=p.id
            WHERE {condition} AND julianday(p.valid_until)<=julianday(?)''',
            (ledger,ledger,now.isoformat())).fetchall()
    items=[]
    for row in sorted(rows,key=lambda r:r['valid_until'])[:30]:
        item=dict(row)
        item['reason']=item['reason'] if item['reason'] not in (None,'settled') else 'pending_check'
        item['message']=REASONS[item['reason']]
        items.append(item)
    return {'pending':len(rows),'items':items}
