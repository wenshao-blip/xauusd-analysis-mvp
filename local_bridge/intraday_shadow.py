"""Independent, immutable intraday experiment. Never changes v3 predictions."""
import copy
import json
from datetime import datetime, timedelta, timezone

BJ = timezone(timedelta(hours=8))
VERSION = 'intraday-shadow-v1'
LABELS = {'up': '偏多', 'down': '偏空', 'range': '震荡'}


def stamp(dt):
    return dt.astimezone(timezone.utc).isoformat(timespec='seconds')


def initialize(db):
    db.execute('''CREATE TABLE IF NOT EXISTS shadow_forecasts (
        id TEXT PRIMARY KEY, kind TEXT NOT NULL, session TEXT NOT NULL,
        created_at TEXT NOT NULL, valid_until TEXT NOT NULL,
        payload TEXT NOT NULL, settlement TEXT,
        UNIQUE(kind, session))''')
    db.commit()


def put(db, item, kind, session):
    item = dict(item, model_version=VERSION, kind=kind, session=session)
    db.execute('INSERT OR IGNORE INTO shadow_forecasts VALUES (?,?,?,?,?,?,NULL)',
               (item['id'], kind, session, item['created_at'], item['valid_until'],
                json.dumps(item, ensure_ascii=False)))
    db.commit()
    return json.loads(db.execute('SELECT payload FROM shadow_forecasts WHERE kind=? AND session=?',
                                (kind, session)).fetchone()[0])


def closed(bars, seconds, now):
    return [b for b in bars if float(b['time']) + seconds <= now.timestamp()]


def volatility(market):
    # Broker D1 is explicit: ATR14 uses only the previous completed daily bars.
    bars = market['candles']['D1'][:-1]
    if len(bars) < 15:
        raise ValueError('日内影子版本需要至少15根已完成D1')
    tr = [max(float(b['high'])-float(b['low']), abs(float(b['high'])-float(a['close'])),
              abs(float(b['low'])-float(a['close']))) for a, b in zip(bars, bars[1:])]
    atr = sum(tr[-14:]) / 14
    today = market['candles']['D1'][-1]
    used = float(today['high']) - float(today['low'])
    if atr <= 0:
        raise ValueError('D1 ATR无效')
    return {'atr': atr, 'used': used, 'used_ratio': used / atr,
            'remaining': max(0, atr-used), 'no_chase': used / atr >= .8,
            'basis': 'MT5 broker D1 range / completed D1 ATR14 (simple true-range mean)'}


def news_risk(news):
    # Calendar sources do not consistently preserve timezone. Do not claim a safe window.
    return {'level': 'unverified' if not news.get('complete') else 'caution',
            'message': '新闻/日历不完整，暂停考虑' if not news.get('complete') else
                       '高影响事件前后30分钟暂停；日历时区与事件时间需核实，不能视为安全窗口',
            'events': news.get('events', []), 'errors': news.get('errors', [])}


def daily_forecast(market, news, now, kind):
    local = now.astimezone(BJ)
    expiry = (local + timedelta(days=1)).replace(hour=6, minute=0, second=0, microsecond=0)
    if kind == 'draft':
        expiry = local.replace(hour=8, minute=0, second=0, microsecond=0)
    d1 = market['candles']['D1'][:-1]
    closes = [float(b['close']) for b in d1]
    if len(closes) < 60:
        raise ValueError('日内方向计算需要60根已完成D1')
    price = (market['bid'] + market['ask']) / 2
    ma20, ma60 = sum(closes[-20:])/20, sum(closes[-60:])/60
    score = sum((1 if a > b else -1 if a < b else 0)
                for a, b in [(closes[-1], ma20), (ma20, ma60), (closes[-1], closes[-6])])
    probs = {'up': .3 + score*.09, 'range': .4, 'down': .3-score*.09}
    direction = max(probs, key=probs.get)
    vol = volatility(market)
    width = vol['atr']*.05
    support = max((float(b['low']) for b in d1[-20:] if float(b['low']) < price), default=price-vol['atr'])
    resistance = min((float(b['high']) for b in d1[-20:] if float(b['high']) > price), default=price+vol['atr'])
    return {'id': f'{VERSION}-{local:%Y%m%d}-{kind}', 'created_at': stamp(now),
            'valid_until': stamp(expiry), 'price': price, 'direction': direction,
            'probabilities': probs, 'probability_basis': 'uncalibrated technical heuristic',
            'support': [round(support-width, 2), round(support+width, 2)],
            'resistance': [round(resistance-width, 2), round(resistance+width, 2)],
            'volatility': vol, 'news_risk': news_risk(news), 'flat_band': .0015}


def active_daily(db, now):
    row = db.execute("SELECT payload FROM shadow_forecasts WHERE kind='daily' AND created_at<=? AND valid_until>? ORDER BY created_at DESC LIMIT 1",
                     (stamp(now), stamp(now))).fetchone()
    return json.loads(row[0]) if row else None


def m15_confirmed(market, direction, now):
    bars = closed(market['candles']['M15'], 900, now)
    if len(bars) < 21 or direction == 'range':
        return False
    last, prior = bars[-1], bars[-21:-1]
    # Close beyond the previous 20 completed bars; wicks or a forming candle do not count.
    return (float(last['close']) > max(float(b['high']) for b in prior) if direction == 'up'
            else float(last['close']) < min(float(b['low']) for b in prior))


def short_forecast(market, news, baseline, daily, now):
    item = copy.deepcopy(baseline)
    item.update(created_at=stamp(now), price=(market['bid']+market['ask'])/2,
                id=f'{VERSION}-short-{stamp(now)}', daily_id=daily['id'] if daily else None,
                flat_band=.0015)
    alignment = 'unavailable' if not daily else ('aligned' if daily['direction'] == item['direction'] else 'conflict')
    item['alignment'] = alignment
    item['m15_confirmed'] = m15_confirmed(market, item['direction'], now)
    item['volatility'] = volatility(market)
    item['news_risk'] = news_risk(news)
    if alignment == 'conflict':
        for key in ('p_up', 'p_range', 'p_down'):
            item[key] = item[key]*.7 + .3/3
        item['execution'].append('与日内定调冲突：仅在已收盘M15突破前20根结构后考虑')
        if not item['m15_confirmed']:
            item['decision'] = 'flat'
    if alignment == 'unavailable' or item['volatility']['no_chase'] or not news.get('complete'):
        item['decision'] = 'flat'
    item['abandon'].append('当日振幅达到日ATR的80%：禁止追单，影子版本暂停新入场')
    return item


def settle(db, now, history):
    """Each horizon gets its own M5 path. Missing endpoints stay pending, never use latest tick."""
    rows = db.execute("SELECT * FROM shadow_forecasts WHERE kind!='draft' AND settlement IS NULL AND valid_until<=?",
                      (stamp(now),)).fetchall()
    for row in rows:
        item = json.loads(row['payload'])
        start = datetime.fromisoformat(item['created_at'])
        end = datetime.fromisoformat(item['valid_until'])
        bars = history(start, end)
        # Exclude the partially observed entry bar and all bars after expiry.
        bars = sorted([b for b in bars if float(b['time']) >= start.timestamp()
                       and float(b['time'])+300 <= end.timestamp()], key=lambda b: b['time'])
        if not bars or float(bars[0]['time'])-start.timestamp() > 300 or end.timestamp()-(float(bars[-1]['time'])+300) > 0:
            continue
        close = float(bars[-1]['close'])
        move = close/item['price']-1
        actual = 'range' if abs(move) <= item['flat_band'] else 'up' if move > 0 else 'down'
        probs = item.get('probabilities') or dict(zip(('up','range','down'), (item['p_up'],item['p_range'],item['p_down'])))
        result = {'settled_at': stamp(now), 'actual_close': close,
                  'actual_high': max(float(b['high']) for b in bars),
                  'actual_low': min(float(b['low']) for b in bars), 'actual_direction': actual,
                  'direction_hit': int(item['direction'] == actual),
                  'brier': sum((probs[k]-int(k == actual))**2 for k in probs)/3}
        db.execute('UPDATE shadow_forecasts SET settlement=? WHERE id=? AND settlement IS NULL',
                   (json.dumps(result), row['id']))
    db.commit()


def export(db, now):
    rows = db.execute('SELECT * FROM shadow_forecasts ORDER BY created_at DESC').fetchall()
    def stats(kind):
        samples = [json.loads(r['settlement']) for r in rows if r['kind'] == kind and r['settlement']]
        n = len(samples)
        return {'samples': n, 'direction_hit_rate': sum(s['direction_hit'] for s in samples)/n if n else None,
                'brier': sum(s['brier'] for s in samples)/n if n else None}
    days = len({r['session'] for r in rows if r['kind'] == 'daily' and r['settlement']})
    latest = lambda kind: next((json.loads(r['payload']) for r in rows if r['kind'] == kind), None)
    return {'model_version': VERSION, 'daily': active_daily(db, now), 'latest_daily': latest('daily'),
            'draft': latest('draft'), 'short': latest('short'),
            'daily_stats': stats('daily'), 'short_stats': stats('short'),
            'settled_trading_days': days, 'minimum_trading_days': 30,
            'review_ready': days >= 30, 'auto_promote': False,
            'pending': sum(r['kind'] != 'draft' and r['settlement'] is None for r in rows)}


def run(db, market, news, baseline, now, history, scheduled=True):
    initialize(db)
    settle(db, now, history)
    local = now.astimezone(BJ)
    fresh = -60 <= now.timestamp()-market.get('time_msc', 0)/1000 <= 900
    # No late backfills: a missed 08:00 freeze remains missing for that day.
    if scheduled and fresh and local.weekday() < 5 and local.hour in (6, 8) and local.minute < 10:
        kind = 'draft' if local.hour == 6 else 'daily'
        put(db, daily_forecast(market, news, now, kind), kind, local.date().isoformat())
    daily = active_daily(db, now)
    short = short_forecast(market, news, baseline, daily, now)
    if not fresh:
        short['decision'] = 'flat'
        short['alignment'] = 'stale_market'
    if scheduled and fresh:
        slot = local.replace(hour=local.hour//2*2, minute=0, second=0, microsecond=0)
        short = put(db, short, 'short', stamp(slot))
    result = export(db, now)
    result['short'] = short
    return result


def report(shadow):
    daily, short = shadow.get('daily'), shadow.get('short')
    lines = ['【日内影子版本｜独立统计】']
    if daily:
        lines += [f"08:00冻结定调：{LABELS[daily['direction']]}，有效至北京时间 {datetime.fromisoformat(daily['valid_until']).astimezone(BJ):%m-%d %H:%M}",
                  '日内概率（未经校准）：'+' / '.join(f'{LABELS[k]} {v:.0%}' for k,v in daily['probabilities'].items()),
                  f"支撑区 {daily['support']}｜阻力区 {daily['resistance']}", daily['news_risk']['message']]
    else:
        lines.append('当前无有效08:00冻结定调，影子短线暂停考虑；06:00草稿不计统计。')
        draft = shadow.get('draft')
        if draft:
            lines += [f"最近06:00草稿（{draft['session']}，不计统计）：{LABELS[draft['direction']]}",
                      '草稿概率：'+' / '.join(f'{LABELS[k]} {v:.0%}' for k,v in draft['probabilities'].items()),
                      f"支撑区 {draft['support']}｜阻力区 {draft['resistance']}",
                      f"草稿日ATR剩余 {draft['volatility']['remaining']:.2f}", draft['news_risk']['message']]
    if short:
        tags = {'aligned': '与日内定调一致', 'conflict': '与日内定调冲突',
                'unavailable': '日内定调缺失/已过期', 'stale_market': '行情过期'}
        vol = short['volatility']
        lines += [tags[short['alignment']],
                  f"影子短线：{'有条件评估' if short['decision']=='trade' else '空仓等待'}；上涨 {short['p_up']:.0%} / 震荡 {short['p_range']:.0%} / 下跌 {short['p_down']:.0%}",
                  f"日ATR {vol['atr']:.2f}｜已运行 {vol['used_ratio']:.0%}｜剩余 {vol['remaining']:.2f}（经纪商D1口径）",
                  '达到80%日ATR禁止追单；冲突已降低置信度，必须等待已收盘M15结构确认。']
    lines.append(f"已结算交易日 {shadow['settled_trading_days']}/30；日内与两小时影子样本独立，满30日仅供复核，不自动替换v3。")
    for key, label in [('daily_stats', '冻结日内'), ('short_stats', '两小时影子')]:
        stats = shadow[key]
        rate = '—' if stats['direction_hit_rate'] is None else f"{stats['direction_hit_rate']:.1%}"
        brier = '—' if stats['brier'] is None else f"{stats['brier']:.4f}"
        lines.append(f"{label}：{stats['samples']}个已结算样本｜方向命中率 {rate}｜Brier {brier}")
    return '\n'.join(lines)
