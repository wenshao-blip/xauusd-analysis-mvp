"""XAUUSD 预测账本：只读行情、冻结预测、到期结算与校准统计。"""
from __future__ import annotations
import json, math, sqlite3
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

SCHEMA="""
CREATE TABLE IF NOT EXISTS predictions(
 id TEXT PRIMARY KEY, created_at TEXT NOT NULL, valid_until TEXT NOT NULL,
 cutoff_at TEXT NOT NULL, price REAL NOT NULL, decision TEXT NOT NULL,
 direction TEXT NOT NULL CHECK(direction IN ('up','range','down')),
 p_up REAL NOT NULL, p_range REAL NOT NULL, p_down REAL NOT NULL,
 target_low REAL, target_high REAL, execution_json TEXT NOT NULL,
 abandon_json TEXT NOT NULL, indicators_json TEXT NOT NULL,
 news_json TEXT NOT NULL, model_version TEXT NOT NULL, run_type TEXT NOT NULL DEFAULT 'scheduled', status TEXT NOT NULL DEFAULT 'open',
 settled_at TEXT, actual_close REAL, actual_high REAL, actual_low REAL,
 actual_direction TEXT, direction_hit INTEGER, range_hit INTEGER, range_touched INTEGER,
 brier REAL);
"""

@dataclass(frozen=True)
class Prediction:
    id:str; created_at:str; valid_until:str; cutoff_at:str; price:float
    decision:str; direction:str; p_up:float; p_range:float; p_down:float
    target_low:float|None; target_high:float|None
    execution:list[str]; abandon:list[str]; indicators:dict; news:list[dict]
    model_version:str="baseline-v1"; run_type:str="scheduled"

def connect(path:Path):
    path.parent.mkdir(parents=True,exist_ok=True)
    db=sqlite3.connect(path); db.row_factory=sqlite3.Row; db.executescript(SCHEMA)
    columns={x[1] for x in db.execute('PRAGMA table_info(predictions)')}
    if 'run_type' not in columns:db.execute("ALTER TABLE predictions ADD COLUMN run_type TEXT NOT NULL DEFAULT 'scheduled'")
    return db

def save(db,p:Prediction):
    probs=(p.p_up,p.p_range,p.p_down)
    if any(x<0 or x>1 for x in probs) or not math.isclose(sum(probs),1,abs_tol=.001): raise ValueError('三项概率必须为0–1且合计为1')
    if p.cutoff_at>p.created_at or p.created_at>=p.valid_until: raise ValueError('时间顺序无效')
    values=asdict(p); values.update(execution_json=json.dumps(p.execution,ensure_ascii=False),abandon_json=json.dumps(p.abandon,ensure_ascii=False),indicators_json=json.dumps(p.indicators,ensure_ascii=False),news_json=json.dumps(p.news,ensure_ascii=False))
    cols=['id','created_at','valid_until','cutoff_at','price','decision','direction','p_up','p_range','p_down','target_low','target_high','execution_json','abandon_json','indicators_json','news_json','model_version','run_type']
    db.execute(f"INSERT INTO predictions({','.join(cols)}) VALUES({','.join(':'+x for x in cols)})",values); db.commit()

def settle_due(db,now:str,close:float,high:float,low:float,flat_band=.0015):
    rows=db.execute("SELECT * FROM predictions WHERE status='open' AND valid_until<=?",(now,)).fetchall()
    for r in rows:
        move=(close-r['price'])/r['price']; actual='range' if abs(move)<=flat_band else ('up' if move>0 else 'down')
        hit=int(actual==r['direction']); range_hit=int(r['target_low'] is not None and r['target_low']<=close<=r['target_high'])
        touched=int(r['target_low'] is not None and high>=r['target_low'] and low<=r['target_high'])
        probs={'up':r['p_up'],'range':r['p_range'],'down':r['p_down']}; brier=sum((probs[k]-int(k==actual))**2 for k in probs)/3
        db.execute("UPDATE predictions SET status='settled',settled_at=?,actual_close=?,actual_high=?,actual_low=?,actual_direction=?,direction_hit=?,range_hit=?,range_touched=?,brier=? WHERE id=?",(now,close,high,low,actual,hit,range_hit,touched,brier,r['id']))
    db.commit(); return len(rows)

def _wilson(hits,n,z=1.96):
    if not n:return (None,None)
    p=hits/n; den=1+z*z/n; mid=(p+z*z/(2*n))/den; margin=z*math.sqrt((p*(1-p)+z*z/(4*n))/n)/den
    return (max(0,mid-margin),min(1,mid+margin))

def summary(db,window=20):
    # Only equal-length, two-hour forecasts count toward formal evaluation.
    rows=db.execute("SELECT * FROM predictions WHERE status='settled' AND run_type='scheduled_2h' ORDER BY settled_at DESC LIMIT ?",(window,)).fetchall(); n=len(rows)
    def avg(key): return sum(r[key] for r in rows if r[key] is not None)/n if n else None
    bins=[]
    if n>=50:
        for lo in (.4,.5,.6,.7,.8,.9):
            samples=[]
            for r in rows:
                confidence=max(r['p_up'],r['p_range'],r['p_down'])
                if lo<=confidence<lo+.1:samples.append(r)
            if samples: bins.append({'from':lo,'to':lo+.1,'samples':len(samples),'claimed':sum(max(r['p_up'],r['p_range'],r['p_down']) for r in samples)/len(samples),'observed':sum(r['direction_hit'] for r in samples)/len(samples)})
    hits=sum(r['direction_hit'] for r in rows if r['direction_hit'] is not None)
    ci_low,ci_high=_wilson(hits,n)
    brier=avg('brier')
    # A score is withheld until there are enough same-duration observations.
    probability_quality=None if n<100 or brier is None else round(max(0,min(100,100*(1-brier/(2/9)))),1)
    stage='样本积累中' if n<50 else ('初步校准' if n<100 else '正式校准')
    return {'samples':n,'direction_hit_rate':avg('direction_hit'),'direction_ci_low':ci_low,'direction_ci_high':ci_high,'target_range_hit_rate':avg('range_hit'),'target_touched_rate':avg('range_touched'),'brier':brier,'calibration_ready':n>=100,'calibration_stage':stage,'probability_quality':probability_quality,'calibration':bins}

def export_json(db,path:Path):
    current=db.execute("SELECT * FROM predictions ORDER BY created_at DESC LIMIT 1").fetchone(); history=db.execute("SELECT * FROM predictions ORDER BY created_at DESC LIMIT 30").fetchall(); data={'current':dict(current) if current else None,'history':[dict(x) for x in history],'rolling20':summary(db,20),'rolling60':summary(db,60),'generated_at':datetime.now(timezone.utc).isoformat()}; path.parent.mkdir(parents=True,exist_ok=True); path.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
