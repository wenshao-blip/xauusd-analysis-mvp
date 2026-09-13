"""一次完整运行：结算旧预测 → 读取MT5/新闻 → 生成并冻结预测 → 导出网页数据 → 推送。"""
import argparse,json,os,subprocess,sys,uuid
import operations,settlement_audit,time
from workflow_lock import acquire
from datetime import datetime,timedelta,timezone
from pathlib import Path
from zoneinfo import ZoneInfo
from baseline_analyzer import analyze
from indicators import multi_timeframe
from mt5_reader import snapshot as mt5_snapshot, history as mt5_history, quote as mt5_quote
import intraday_shadow
from market_context import daily_summary,multi_candle_signals,multi_structure_levels
from news_sources import collect as news_collect
from notifications import send_all
from prediction_ledger import Prediction,connect,export_json,save,settle_history
from report_formatter import build_report

ROOT=Path(__file__).resolve().parents[1]; DB=ROOT/'local_bridge'/'aurum.db'; WEB=ROOT/'public'/'data'/'dashboard.json'
def iso(dt):return dt.isoformat(timespec='seconds')
def bj(dt):return dt.astimezone(ZoneInfo('Asia/Shanghai')).strftime('%Y-%m-%d %H:%M')
def next_regular_time(now):
    local=now.astimezone(ZoneInfo('Asia/Shanghai'))
    for hour in range(0,24,2):
        candidate=local.replace(hour=hour,minute=0,second=0,microsecond=0)
        if candidate>local:return candidate.astimezone(timezone.utc)
    return (local+timedelta(days=1)).replace(hour=0,minute=0,second=0,microsecond=0).astimezone(timezone.utc)

def full_report_time(now):
    local=now.astimezone(ZoneInfo('Asia/Shanghai'))
    return local.hour in (10,16,21)

def materially_changed(previous, result):
    """Only alert between fixed reports when the decision meaningfully changes."""
    if not previous:
        return True
    if previous['decision'] != result['decision'] or previous['direction'] != result['direction']:
        return True
    old_probs=(previous['p_up'],previous['p_range'],previous['p_down'])
    new_probs=(result['p_up'],result['p_range'],result['p_down'])
    return max(abs(a-b) for a,b in zip(old_probs,new_probs)) >= .12

def publish_dashboard(prediction_id):
    """Publish only the public dashboard snapshot; credentials remain local."""
    relative='public/data/dashboard.json'
    commands=(
        ['git','add','--',relative],
        ['git','diff','--cached','--quiet','--',relative],
    )
    # The bundled Git stores its HTTPS helper outside the default PATH.
    # Keep this local setup explicit so scheduled publishing uses the same Git.
    env = os.environ.copy()
    helper = Path(sys.executable).parents[1] / 'native' / 'git' / 'mingw64' / 'bin'
    if helper.exists():
        env['PATH'] = str(helper) + os.pathsep + env.get('PATH', '')
    subprocess.run(commands[0],cwd=ROOT,check=True,capture_output=True,text=True,env=env)
    unchanged=subprocess.run(commands[1],cwd=ROOT,capture_output=True,text=True,env=env).returncode==0
    if not unchanged:
        subprocess.run(['git','commit','--only','-m',f'Update dashboard {prediction_id}','--',relative],cwd=ROOT,check=True,capture_output=True,text=True,encoding='utf-8',errors='replace',env=env)
    result=subprocess.run(['git','push','origin','main'],cwd=ROOT,capture_output=True,text=True,timeout=60,encoding='utf-8',errors='replace',env=env)
    return {'ok':result.returncode==0,'changed':not unchanged,'error':result.stderr.strip() if result.returncode else ''}


def write_dashboard(db, now, shadow=None):
    """Replace the dashboard atomically, including health even when market reads fail."""
    tmp=WEB.with_suffix('.tmp')
    export_json(db,tmp)
    dashboard=json.loads(tmp.read_text('utf-8'))
    shadow=shadow if shadow is not None else intraday_shadow.export(db,now)
    shadow['report_text']=intraday_shadow.report(shadow)
    dashboard['shadow']=shadow
    dashboard['shadow_error']=None
    dashboard['health']=operations.health(db,now)
    tmp.write_text(json.dumps(dashboard,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    tmp.replace(WEB)
    return dashboard


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--symbol',default='XAUUSD')
    ap.add_argument('--hours',type=int)
    for flag in ('manual','supplemental','no-push','no-publish','reconcile-only','retry-publish'):
        ap.add_argument('--'+flag,action='store_true')
    a=ap.parse_args()
    if a.hours is not None and a.hours<=0:
        ap.error('--hours must be positive')
    now=datetime.now(timezone.utc)
    maintenance=a.reconcile_only or a.retry_publish
    kind=('reconcile' if maintenance else 'manual' if a.manual else
          'supplemental' if a.supplemental else 'custom' if a.hours else 'scheduled_2h')
    key=operations.job_key(now,kind) if kind in ('scheduled_2h','supplemental') else f'{kind}-{uuid.uuid4().hex}'
    db=connect(DB)
    operations.initialize(db,now)
    intraday_shadow.initialize(db)
    prior_run=db.execute('SELECT code FROM operation_runs WHERE id=?',(key,)).fetchone()
    retry_shadow=bool(prior_run and prior_run['code']=='shadow_error')
    operations.start(db,key,kind,now)
    code='ok';stage='market';pid=None;result=None;shadow=None;pushed={};published={}
    generated=False;previous=None
    try:
        # Fixed slots have stable IDs. A restart cannot create a second formal prediction.
        existing=db.execute('SELECT id FROM predictions WHERE id=?',(key,)).fetchone()
        if existing and not maintenance and not retry_shadow:
            pid=existing['id']
        elif not a.retry_publish:
            operations.update(db,key,'market')
            try:
                raw=mt5_quote(a.symbol) if maintenance else mt5_snapshot(a.symbol)
                tick=datetime.fromtimestamp(raw['time_msc']/1000,timezone.utc)
                operations.set_value(db,'market_time',iso(tick))
                fresh=-60<=(now-tick).total_seconds()<=900
                operations.set_value(db,'market_status','ok' if fresh else 'stale_quote')
            except Exception:
                operations.set_value(db,'market_status','mt5_error')
                code='mt5_error';raw=None;fresh=False
            if raw is not None and not fresh:
                code='stale_quote'
            if fresh and not maintenance:
                stage='analysis'
                operations.update(db,key,stage)
                raw['indicators']=multi_timeframe(raw['candles'])
                price=(raw['bid']+raw['ask'])/2
                raw['indicators']['_market']=daily_summary(raw['candles']['D1'],price)
                raw['indicators']['_candles']=multi_candle_signals(raw['candles'])
                raw['indicators']['_structure']=multi_structure_levels(raw['candles'])
                news=news_collect()
                now=datetime.now(timezone.utc)
                valid=now+timedelta(hours=a.hours or 6) if (a.hours or a.manual) else next_regular_time(now)
                previous=db.execute("SELECT * FROM predictions WHERE run_type='scheduled_2h' ORDER BY created_at DESC LIMIT 1").fetchone()
                result=analyze(raw,news,iso(valid),kind)
                pid=key
                p=Prediction(pid,iso(now),result['valid_until'],iso(now),round(price,5),
                    result['decision'],result['direction'],result['p_up'],result['p_range'],result['p_down'],
                    result['target_low'],result['target_high'],result['execution'],result['abandon'],
                    raw['indicators'],news['articles'],result['model_version'],kind)
                # Generate/freeze before historical I/O so an old outage cannot block today's view.
                try:
                    shadow=intraday_shadow.run(db,raw,news,result,now,lambda *_:[],scheduled=kind=='scheduled_2h')
                except Exception:
                    code='shadow_error'
                if not existing:
                    save(db,p)
                    generated=True
                operations.update(db,key,'generated',code,pid)
        stage='settlement'
        operations.update(db,key,stage,code,pid)
        if not a.retry_publish:
            cache={}
            deadline=time.monotonic()+45
            def history(start,end):
                if time.monotonic()>deadline:
                    raise settlement_audit.BudgetDeferred()
                k=(start,end)
                if k not in cache:
                    cache[k]=mt5_history(a.symbol,start,end)
                return cache[k]
            settle_history(db,datetime.now(timezone.utc),history)
            intraday_shadow.settle(db,datetime.now(timezone.utc),history)
            # Refresh statistics after reconciliation while preserving this run's manual shadow view.
            short=shadow.get('short') if shadow else None
            shadow=intraday_shadow.export(db,datetime.now(timezone.utc))
            if short is not None:
                shadow['short']=short
    except Exception:
        code={'market':'mt5_error','analysis':'analysis_error','settlement':'ledger_error'}.get(stage,'analysis_error')
    operations.update(db,key,'finished',code,pid,datetime.now(timezone.utc))
    dashboard=write_dashboard(db,datetime.now(timezone.utc),shadow)
    if generated and not a.no_push and (a.manual or a.supplemental or full_report_time(now) or materially_changed(previous,result)):
        subject,body=build_report(dashboard['current'])
        body+='\n\n'+intraday_shadow.report(dashboard['shadow'])+'\n\n'+operations.text_report(dashboard['health'])
        try:
            pushed=send_all(subject,body)
            if not any(isinstance(v,dict) and v.get('ok') for v in pushed.values()):
                code='notification_error' if code=='ok' else code
        except Exception:
            code='notification_error' if code=='ok' else code
    if not a.no_publish:
        operations.set_value(db,'publish_pending','1')
        try:
            published=publish_dashboard(pid or key)
        except Exception:
            published={'ok':False}
        if published.get('ok'):
            operations.set_value(db,'publish_pending','0')
            operations.set_value(db,'last_publish_at',iso(datetime.now(timezone.utc)))
        else:
            code='publish_error' if code in ('ok','stale_quote') else code
    operations.update(db,key,'finished',code,pid,datetime.now(timezone.utc))
    # Local /health is live; the public dashboard describes the state at upload time.
    db.close()
    print(json.dumps({'prediction_id':pid,'prediction':result,'code':code,
                      'message':operations.MESSAGES[code],'push':pushed,'publish':published},ensure_ascii=False))
    return 0 if code in ('ok','stale_quote','notification_error','publish_error','shadow_error') else 1


if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    with acquire(DB.with_suffix('.lock')) as locked:
        if not locked:
            print(json.dumps({'code':'busy','message':operations.MESSAGES['busy']},ensure_ascii=False))
            sys.exit(3)
        sys.exit(main())
