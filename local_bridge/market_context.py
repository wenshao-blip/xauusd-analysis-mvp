"""Daily context, candle confirmation, and auditable swing structure."""
def daily_summary(d1, price):
    previous, today = d1[-2], d1[-1]
    prev_close=float(previous['close']); open_=float(today['open']); high=float(today['high']); low=float(today['low']); change=price-prev_close
    return {'previous_close':round(prev_close,5),'today_open':round(open_,5),'today_high':round(high,5),'today_low':round(low,5),'day_range':round(high-low,5),'change':round(change,5),'change_pct':round(change/prev_close,6),'amplitude_pct':round((high-low)/prev_close,6),'basis':'MT5 broker D1'}
def candle_signals(bars):
    prev,cur=bars[-2],bars[-1]; o,h,l,c=map(float,(cur['open'],cur['high'],cur['low'],cur['close'])); po,pc=map(float,(prev['open'],prev['close'])); body=max(abs(c-o),1e-9); upper=h-max(o,c); lower=min(o,c)-l; signals=[]
    if c>o and pc<po and o<=pc and c>=po:signals.append({'type':'bullish_engulfing','bias':'up','label':'看涨吞没'})
    if c<o and pc>po and o>=pc and c<=po:signals.append({'type':'bearish_engulfing','bias':'down','label':'看跌吞没'})
    if lower>=body*2 and upper<=body:signals.append({'type':'lower_rejection','bias':'up','label':'长下影拒绝'})
    if upper>=body*2 and lower<=body:signals.append({'type':'upper_rejection','bias':'down','label':'长上影拒绝'})
    prior=bars[-22:-2]; resistance=max(float(x['high']) for x in prior); support=min(float(x['low']) for x in prior)
    if c>resistance:signals.append({'type':'breakout_up','bias':'up','label':'向上突破收盘确认','level':round(resistance,2)})
    if c<support:signals.append({'type':'breakout_down','bias':'down','label':'向下突破收盘确认','level':round(support,2)})
    return signals
def multi_candle_signals(candles): return {tf:candle_signals(candles[tf]) for tf in ('M5','M15','M30','H1')}
def _swings(bars,field,lookback=90,wing=2):
    values=[float(x[field]) for x in bars[-lookback:]]; points=[]
    for i in range(wing,len(values)-wing):
        window=values[i-wing:i+wing+1]
        if (field=='low' and values[i]==min(window)) or (field=='high' and values[i]==max(window)):
            if not points or abs(points[-1]-values[i])>1e-8: points.append(values[i])
    return points[-8:]
def multi_structure_levels(candles):
    """Frozen multi-timeframe swing levels; no untestable 'main force' claim."""
    weights={'M15':2,'M30':3,'H1':4}; supports=[]; resistances=[]
    for tf,weight in weights.items():
        supports += [{'price':round(x,5),'timeframe':tf,'weight':weight} for x in _swings(candles[tf],'low')]
        resistances += [{'price':round(x,5),'timeframe':tf,'weight':weight} for x in _swings(candles[tf],'high')]
    return {'supports':supports,'resistances':resistances,'method':'confirmed local swing highs/lows, M15/M30/H1'}
