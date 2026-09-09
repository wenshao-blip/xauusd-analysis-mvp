"""免费新闻/事件源。失败时返回错误并由工作流降级为空仓，不静默伪造数据。"""
import csv, json, urllib.parse, urllib.request
from pathlib import Path
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from xml.etree import ElementTree as ET

GDELT='https://api.gdeltproject.org/api/v2/doc/doc'
FED_RSS='https://www.federalreserve.gov/feeds/press_monetary.xml'
BLS_ICS='https://www.bls.gov/schedule/news_release/bls.ics'
UA={'User-Agent':'AurumSignal/0.1 research-dashboard'}

def get(url,timeout=15):
    with urllib.request.urlopen(urllib.request.Request(url,headers=UA),timeout=timeout) as r:return r.read()

def gdelt(limit=20):
    query='(gold OR XAUUSD OR "Federal Reserve" OR inflation OR "US dollar" OR "Treasury yields")'
    url=GDELT+'?'+urllib.parse.urlencode({'query':query,'mode':'artlist','maxrecords':limit,'timespan':'24h','sort':'datedesc','format':'json'})
    data=json.loads(get(url)); now=datetime.now(timezone.utc).isoformat()
    return [{'title':x.get('title',''),'source':x.get('domain',''),'published_at':x.get('seendate',''),'first_seen_at':now,'url':x.get('url',''),'impact':'unrated','gold_bias':'unknown','provider':'GDELT'} for x in data.get('articles',[])]

def fed(limit=10):
    root=ET.fromstring(get(FED_RSS)); now=datetime.now(timezone.utc).isoformat(); out=[]
    for item in root.findall('.//item')[:limit]:
        pub=item.findtext('pubDate',''); parsed=parsedate_to_datetime(pub).astimezone(timezone.utc).isoformat() if pub else ''
        out.append({'title':item.findtext('title',''),'source':'Federal Reserve','published_at':parsed,'first_seen_at':now,'url':item.findtext('link',''),'impact':'high','gold_bias':'unknown','provider':'Federal Reserve RSS'})
    return out

def bls_calendar():
    text=get(BLS_ICS).decode('utf-8','replace'); events=[]; current={}
    for line in text.splitlines():
        if line=='BEGIN:VEVENT':current={}
        elif line.startswith('DTSTART'):current['starts_at']=line.split(':',1)[-1]
        elif line.startswith('SUMMARY:'):current['title']=line.split(':',1)[-1]
        elif line=='END:VEVENT' and current:events.append(current)
    return events

def local_calendar():
    path=Path(__file__).resolve().parents[2]/'Kunpeng_USD_HighImpact_2026.csv'
    if not path.exists():return []
    with path.open(encoding='utf-8-sig',newline='') as f:
        return [{'starts_at':r['beijing_time'],'title':r['event'],'currency':r['currency'],'impact':r['impact'],'provider':'local-frozen-calendar'} for r in csv.DictReader(f)]

def collect():
    result={'captured_at':datetime.now(timezone.utc).isoformat(),'articles':[],'events':local_calendar(),'errors':[]}
    for name,fn,key in [('gdelt',gdelt,'articles'),('fed',fed,'articles'),('bls',bls_calendar,'events')]:
        try:result[key].extend(fn())
        except Exception as exc:result['errors'].append({'source':name,'error':str(exc)})
    # 可用性最低门槛：至少一个带时间戳的新闻源和一个事件日历。
    # GDELT限流或BLS反爬会保留错误记录，但已有美联储RSS和本地冻结日历时不阻断分析。
    result['complete']=bool(result['articles'] and result['events']);return result
