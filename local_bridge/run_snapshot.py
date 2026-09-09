"""生成一次只读 MT5 + 指标快照，供分析模型与网页消费。"""
import argparse,json
from datetime import datetime,timezone
from pathlib import Path
from indicators import multi_timeframe
from mt5_reader import snapshot
def main():
    p=argparse.ArgumentParser();p.add_argument('--symbol',default='XAUUSD');p.add_argument('--out',default='../public/data/market_snapshot.json');a=p.parse_args()
    raw=snapshot(a.symbol); result={'captured_at':datetime.now(timezone.utc).isoformat(),'symbol':a.symbol,'bid':raw['bid'],'ask':raw['ask'],'spread':raw['spread'],'time_msc':raw['time_msc'],'indicators':multi_timeframe(raw['candles'])}
    out=Path(a.out);out.parent.mkdir(parents=True,exist_ok=True);out.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8');print(out.resolve())
if __name__=='__main__':main()
