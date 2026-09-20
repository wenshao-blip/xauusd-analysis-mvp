"""Persistent health state and schedule audit; public messages never contain credentials."""
import json
from datetime import datetime, timedelta, timezone
import settlement_audit
import session_schedule

BJ = timezone(timedelta(hours=8))
MESSAGES = {
    'ok': '完成', 'mt5_error': 'MT5读取失败，请检查终端登录和连接',
    'stale_quote': '报价时间异常或已过期，未生成新预测；检查经纪商时间设置、休市状态或MT5连接',
    'analysis_error': '分析失败，等待重试', 'shadow_error': '影子生成失败，请查看运行检查',
    'ledger_error': '账本处理失败，原记录保留', 'publish_error': 'GitHub上传失败，后台将重试',
    'notification_error': '报告通知未送达，请检查现有通知配置',
    'interrupted': '上次运行中断，已恢复核查', 'timeout': '运行超时，等待重试',
    'busy': '已有任务运行', 'running': '正在运行',
}


def stamp(now):
    return now.astimezone(timezone.utc).isoformat(timespec='seconds')


def initialize(db, now):
    db.executescript('''CREATE TABLE IF NOT EXISTS operation_meta (key TEXT PRIMARY KEY,value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS operation_runs (
            id TEXT PRIMARY KEY, kind TEXT NOT NULL, started_at TEXT NOT NULL,
            finished_at TEXT, stage TEXT NOT NULL, code TEXT NOT NULL,
            report_id TEXT, attempts INTEGER NOT NULL DEFAULT 1);''')
    db.execute("INSERT OR IGNORE INTO operation_meta VALUES ('monitor_since',?)", (stamp(now),))
    settlement_audit.initialize(db)
    db.commit()


def get(db, key, default=None):
    row = db.execute('SELECT value FROM operation_meta WHERE key=?', (key,)).fetchone()
    return row[0] if row else default


def set_value(db, key, value):
    db.execute('INSERT OR REPLACE INTO operation_meta VALUES (?,?)', (key,str(value)))
    db.commit()


def job_key(now, kind):
    local = now.astimezone(BJ)
    if kind == 'scheduled_session':
        item=session_schedule.due(now)
        if not item: raise ValueError('当前不在固定报告时段')
        name,start=item
        return f'scheduled_session-{name}-{stamp(start)}'
    hour = local.hour//2*2 if kind == 'scheduled_2h' else local.hour
    return kind+'-'+stamp(local.replace(hour=hour,minute=0,second=0,microsecond=0))


def start(db, key, kind, now):
    db.execute('''INSERT INTO operation_runs(id,kind,started_at,stage,code) VALUES (?,?,?,'starting','running')
        ON CONFLICT(id) DO UPDATE SET started_at=excluded.started_at,finished_at=NULL,
        stage='starting',code='running',attempts=operation_runs.attempts+1''', (key,kind,stamp(now)))
    db.commit()


def update(db, key, stage, code='running', report_id=None, now=None):
    db.execute('''UPDATE operation_runs SET stage=?,code=?,report_id=COALESCE(?,report_id),
        finished_at=? WHERE id=?''', (stage,code,report_id,stamp(now) if now else None,key))
    db.commit()


def expected(now, since):
    local = now.astimezone(BJ)
    start = max(since.astimezone(BJ), local-timedelta(days=7))
    day = start.replace(hour=0,minute=0,second=0,microsecond=0)
    while day <= local:
        if day.weekday() < 5:
            for hour,minute,_ in session_schedule.SLOTS:
                at=day.replace(hour=hour,minute=minute)
                if since <= at and at+timedelta(minutes=10) <= now:
                    yield at,'scheduled_session'
        day += timedelta(days=1)


def health(db, now):
    initialize(db, now)
    since = datetime.fromisoformat(get(db,'monitor_since'))
    heartbeat = get(db,'heartbeat')
    issues=[]
    if heartbeat and (now-datetime.fromisoformat(heartbeat)).total_seconds()>180:
        issues.append({'key':'scheduler_offline','message':'后台心跳过期，电脑或调度服务可能已停止'})
    runs=[dict(r) for r in db.execute('SELECT * FROM operation_runs ORDER BY started_at DESC LIMIT 12')]
    for r in runs:
        r['message']=MESSAGES.get(r['code'],'运行异常')
    row=db.execute("SELECT * FROM operation_runs WHERE kind!='reconcile' ORDER BY started_at DESC LIMIT 1").fetchone()
    latest=dict(row) if row else None
    if latest:
        latest['message']=MESSAGES.get(latest['code'],'运行异常')
    recovered_publish=latest and latest['code']=='publish_error' and get(db,'publish_pending')!='1'
    recovered_market=latest and latest['code']=='mt5_error' and get(db,'market_status')=='ok'
    if latest and not (recovered_publish or recovered_market) and latest['code'] not in ('ok','running','stale_quote'):
        issues.append({'key':'run_'+latest['id'],'message':latest['message']})
    market_time=get(db,'market_time')
    market_status=get(db,'market_status','unknown')
    local=now.astimezone(BJ)
    weekend=local.weekday()==6 or (local.weekday()==5 and local.hour>=6) or (local.weekday()==0 and local.hour<6)
    if market_status=='mt5_error':
        issues.append({'key':'mt5_error','message':MESSAGES['mt5_error']})
    elif not weekend and market_time and not -60 <= (now-datetime.fromisoformat(market_time)).total_seconds() <= 900:
        issues.append({'key':'stale_quote','message':MESSAGES['stale_quote']})
    tables={r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    shadow_rows=db.execute('SELECT kind,session FROM shadow_forecasts').fetchall() if 'shadow_forecasts' in tables else []
    frozen={(r['kind'],r['session']) for r in shadow_rows}
    generated={r[0] for r in db.execute("SELECT id FROM predictions WHERE run_type='scheduled_session'")}
    missed=[]
    for at,kind in expected(now,since):
        key=job_key(at,kind)
        exists=key in generated
        if not exists:
            label={'draft':'06:00草稿','daily':'08:00冻结定调','scheduled_session':f'{at:%H:%M}固定报告'}[kind]
            item={'key':'missing_'+key,'message':f'{at:%m-%d} {label}未生成；不事后补造预测'}
            missed.append(item)
    issues += missed
    if get(db,'publish_pending')=='1':
        issues.append({'key':'publish_pending','message':MESSAGES['publish_error']})
    if get(db,'alert_delivery')=='failed':
        issues.append({'key':'alert_delivery','message':'异常提醒未送达，请检查现有通知配置'})
    audit=settlement_audit.summary(db,now)
    if audit['pending']:
        issues.append({'key':'settlement_pending','message':f"{audit['pending']}条到期记录待核查，不计入已结算统计"})
    return {'checked_at':stamp(now),'monitor_since':stamp(since),'heartbeat':heartbeat,
            'market_time':market_time,'market_status':market_status,'weekend':weekend,
            'last_publish_at':get(db,'last_publish_at'),'last_run':latest,
            'missed_count':len(missed),'issues':issues,'settlements':audit,
            'runs':runs,'scope':'最近7日、仅监测启用后的时点；公共页面为上传快照'}


def notify_changes(db, status, now, sender):
    """One alert per active issue set; failed delivery retries after an hour, never each heartbeat."""
    fingerprint=json.dumps(sorted(x['key'] for x in status['issues']))
    previous=get(db,'alert_fingerprint','[]')
    retry=get(db,'alert_retry_after')
    if fingerprint==previous or (retry and now<datetime.fromisoformat(retry)):
        return
    if not status['issues']:
        set_value(db,'alert_fingerprint',fingerprint)
        return
    body='黄金系统运行提醒\n'+'\n'.join(x['message'] for x in status['issues'][:15])
    try:
        result=sender('Aurum Signal 运行异常提醒',body)
        delivered=any(isinstance(v,dict) and v.get('ok') for v in result.values())
    except Exception:
        delivered=False
    set_value(db,'alert_delivery','ok' if delivered else 'failed')
    if delivered:
        set_value(db,'alert_fingerprint',fingerprint)
    set_value(db,'alert_retry_after',stamp(now+timedelta(hours=1)) if not delivered else stamp(now))


def text_report(status):
    lines=['【运行与结算检查】']
    lines += [x['message'] for x in status['issues'][:15]] or ['本次核查未发现漏报或待处理异常']
    lines += [f"待核查结算：{status['settlements']['pending']}条",status['scope']]
    return '\n'.join(lines)
