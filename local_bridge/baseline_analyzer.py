"""可审计的技术基线。后续模型必须与此基线分版本比较。"""
def analyze(market,news,valid_until,run_type='scheduled'):
    ind=market['indicators']; price=(market['bid']+market['ask'])/2; up=down=0
    for tf,weight in [('H1',3),('M30',2),('M15',2),('M5',1)]:
        x=ind[tf]
        up+=weight*((x['close']>x['ma20'])+(x['ma20']>x['ma60'])+(x['macd_hist']>0)+(x['+di']>x['-di']))
        down+=weight*((x['close']<x['ma20'])+(x['ma20']<x['ma60'])+(x['macd_hist']<0)+(x['+di']<x['-di']))
    total=32; edge=(up-down)/total; p_up=max(.15,min(.70,.33+edge*.45));p_down=max(.15,min(.70,.33-edge*.45));p_range=1-p_up-p_down
    signals=[s for tf in ('M15','M5') for s in ind.get('_candles',{}).get(tf,[])]
    candle_edge=sum(1 if s['bias']=='up' else -1 for s in signals)
    adjustment=max(-.05,min(.05,candle_edge*.025));p_up+=adjustment;p_down-=adjustment
    if p_range<.10:
        excess=.10-p_range;p_up-=excess/2;p_down-=excess/2;p_range=.10
    direction=max({'up':p_up,'range':p_range,'down':p_down},key={'up':p_up,'range':p_range,'down':p_down}.get)
    atr_proxy=sum(abs(x['high']-x['low']) for x in market['candles']['M15'][-14:])/14
    low,high=(price+atr_proxy*.6,price+atr_proxy*1.4) if direction=='up' else ((price-atr_proxy*1.4,price-atr_proxy*.6) if direction=='down' else (price-atr_proxy*.7,price+atr_proxy*.7))
    stale=not news.get('complete',False); conflicting=abs(edge)<.08; opposed=(direction=='up' and candle_edge<0) or (direction=='down' and candle_edge>0); decision='flat' if stale or conflicting or opposed else 'trade'
    m15=ind['M15']; level=round(m15['ma20'],2); execution=[f"M15收盘保持在MA20 {level} {'上方' if direction=='up' else '下方'}",f"M5出现{'看涨' if direction=='up' else '看跌'}吞没、影线拒绝或突破收盘确认",f"MACD柱与DI方向保持{'向上' if direction=='up' else '向下'}一致"]
    abandon=[f"M15收盘反向穿越MA20 {level}",'高影响事件前后30分钟','点差异常扩大','价格已经进入目标区间，剩余空间不足','预测有效期即将结束']
    return {'valid_until':valid_until,'decision':decision,'direction':direction,'p_up':round(p_up,4),'p_range':round(p_range,4),'p_down':round(p_down,4),'target_low':round(low,2),'target_high':round(high,2),'execution':execution,'abandon':abandon,'run_type':run_type,'model_version':'technical-candle-v2'}
