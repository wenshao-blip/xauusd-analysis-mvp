"""一次完整运行：结算旧预测 → 读取MT5/新闻 → 生成并冻结预测 → 导出网页数据 → 推送。"""
import argparse,json,uuid
from datetime import datetime,timedelta,timezone
from pathlib import Path
from zoneinfo import ZoneInfo
from baseline_analyzer import analyze
from indicators import multi_timeframe
from mt5_reader import snapshot as mt5_snapshot
from news_sources import collect as news_collect
from notifications import send_all
from prediction_ledger import Prediction,connect,export_json,save,settle_due

ROOT=Path(__file__).resolve().parents[1]; DB=ROOT/'local_bridge'/'aurum.db'; WEB=ROOT/'public'/'data'/'dashboard.json'
def iso(dt):return dt.isoformat(timespec='seconds')
def next_scheduled_time(now):
    local=now.astimezone(ZoneInfo('Asia/Shanghai'))
    for hour in (4,10,16):
        candidate=local.replace(hour=hour,minute=0,second=0,microsecond=0)
        if candidate>local:return candidate.astimezone(timezone.utc)
    return (local+timedelta(days=1)).replace(hour=4,minute=0,second=0,microsecond=0).astimezone(timezone.utc)
def main():
    ap=argparse.ArgumentParser();ap.add_argument('--symbol',default='XAUUSD');ap.add_argument('--hours',type=int);ap.add_argument('--manual',action='store_true');ap.add_argument('--no-push',action='store_true');a=ap.parse_args()
    now=datetime.now(timezone.utc); valid=now+timedelta(hours=a.hours) if a.hours else (now+timedelta(hours=6) if a.manual else next_scheduled_time(now)); hours=max(1,int((valid-now).total_seconds()/3600+.999)); raw=mt5_snapshot(a.symbol); raw['indicators']=multi_timeframe(raw['candles']); news=news_collect(); db=connect(DB)
    # 上个区间用当前时刻前最后一段M5行情结算；正式版可替换为Tick路径。
    m5=raw['candles']['M5']; settle_due(db,iso(now),float(m5[-1]['close']),max(float(x['high']) for x in m5[-max(2,hours*12):]),min(float(x['low']) for x in m5[-max(2,hours*12):]))
    result=analyze(raw,news,iso(valid),'manual' if a.manual else 'scheduled'); pid=f"{now:%Y%m%dT%H%M%SZ}-{uuid.uuid4().hex[:6]}"
    p=Prediction(pid,iso(now),result['valid_until'],iso(now),round((raw['bid']+raw['ask'])/2,5),result['decision'],result['direction'],result['p_up'],result['p_range'],result['p_down'],result['target_low'],result['target_high'],result['execution'],result['abandon'],raw['indicators'],news['articles'],result['model_version'],result['run_type'])
    save(db,p);export_json(db,WEB);db.close(); body=f"XAUUSD {p.decision} / {p.direction}\n上涨 {p.p_up:.0%} 震荡 {p.p_range:.0%} 下跌 {p.p_down:.0%}\n目标区间 {p.target_low}–{p.target_high}\n有效至 {p.valid_until}"
    pushed={} if a.no_push else send_all('Aurum Signal 黄金评估',body);print(json.dumps({'prediction_id':pid,'prediction':result,'news_errors':news['errors'],'push':pushed},ensure_ascii=False,indent=2))
if __name__=='__main__':main()
