"""无第三方依赖的基础指标，输入为按时间升序的 MT5 K线字典。"""
def ema(values,period):
    if not values:return []
    k=2/(period+1); out=[float(values[0])]
    for value in values[1:]:out.append(float(value)*k+out[-1]*(1-k))
    return out

def sma(values,period):
    if len(values)<period:return None
    return sum(values[-period:])/period

def snapshot(bars):
    if len(bars)<200:raise ValueError('每个周期至少需要200根K线')
    close=[float(x['close']) for x in bars]; high=[float(x['high']) for x in bars]; low=[float(x['low']) for x in bars]
    e12,e26=ema(close,12),ema(close,26); macd=[a-b for a,b in zip(e12,e26)]; signal=ema(macd,9)
    k_values=[]
    for i in range(len(close)):
        lo=min(low[max(0,i-4):i+1]); hi=max(high[max(0,i-4):i+1]); k_values.append(50 if hi==lo else 100*(close[i]-lo)/(hi-lo))
    slow_k=[sum(k_values[max(0,i-2):i+1])/len(k_values[max(0,i-2):i+1]) for i in range(len(k_values))]
    slow_d=[sum(slow_k[max(0,i-2):i+1])/len(slow_k[max(0,i-2):i+1]) for i in range(len(slow_k))]
    tr=[]; plus_dm=[]; minus_dm=[]
    for i in range(len(close)):
        if i==0:tr.append(high[i]-low[i]);plus_dm.append(0);minus_dm.append(0);continue
        tr.append(max(high[i]-low[i],abs(high[i]-close[i-1]),abs(low[i]-close[i-1])))
        up=high[i]-high[i-1]; down=low[i-1]-low[i];plus_dm.append(up if up>down and up>0 else 0);minus_dm.append(down if down>up and down>0 else 0)
    def wilder(values,n=14):
        out=[values[0]]
        for x in values[1:]:out.append((out[-1]*(n-1)+x)/n)
        return out
    atr=wilder(tr); pdm=wilder(plus_dm); mdm=wilder(minus_dm); pdi=[100*a/b if b else 0 for a,b in zip(pdm,atr)]; mdi=[100*a/b if b else 0 for a,b in zip(mdm,atr)]; dx=[100*abs(a-b)/(a+b) if a+b else 0 for a,b in zip(pdi,mdi)]; adx=wilder(dx)
    return {'close':close[-1],'ma20':sma(close,20),'ma60':sma(close,60),'ma200':sma(close,200),'macd':macd[-1],'macd_signal':signal[-1],'macd_hist':macd[-1]-signal[-1],'stoch_k':slow_k[-1],'stoch_d':slow_d[-1],'atr':atr[-1],'adx':adx[-1],'+di':pdi[-1],'-di':mdi[-1]}

def multi_timeframe(candles):return {name:snapshot(candles[name]) for name in ('M5','M15','M30','H1')}
