"""可审计的技术基线。后续模型必须与此基线分版本比较。"""
def analyze(market,news,valid_until,run_type='scheduled'):
    ind=market['indicators']; price=(market['bid']+market['ask'])/2; up=down=0
    for tf,weight in [('H1',3),('M30',2),('M15',2),('M5',1)]:
        x=ind[tf]
        up+=weight*((x['close']>x['ma20'])+(x['ma20']>x['ma60'])+(x['macd_hist']>0)+(x['+di']>x['-di']))
        down+=weight*((x['close']<x['ma20'])+(x['ma20']<x['ma60'])+(x['macd_hist']<0)+(x['+di']<x['-di']))
    total=32; edge=(up-down)/total; p_up=max(.15,min(.70,.33+edge*.45));p_down=max(.15,min(.70,.33-edge*.45));p_range=1-p_up-p_down
    if p_range<.10:
        excess=.10-p_range;p_up-=excess/2;p_down-=excess/2;p_range=.10
    direction=max({'up':p_up,'range':p_range,'down':p_down},key={'up':p_up,'range':p_range,'down':p_down}.get)
    atr_proxy=sum(abs(x['high']-x['low']) for x in market['candles']['M15'][-14:])/14
    low,high=(price+atr_proxy*.6,price+atr_proxy*1.4) if direction=='up' else ((price-atr_proxy*1.4,price-atr_proxy*.6) if direction=='down' else (price-atr_proxy*.7,price+atr_proxy*.7))
    stale=not news.get('complete',False); conflicting=abs(edge)<.08; decision='flat' if stale or conflicting else 'trade'
    return {'valid_until':valid_until,'decision':decision,'direction':direction,'p_up':round(p_up,4),'p_range':round(p_range,4),'p_down':round(p_down,4),'target_low':round(low,2),'target_high':round(high,2),'execution':['M15收盘确认目标方向','M5回踩/反抽后动能再次同向'],'abandon':['新闻源不完整或数据过期','高影响事件前后30分钟','点差异常','M15重新收回突破位'],'run_type':run_type,'model_version':'technical-baseline-v1'}

