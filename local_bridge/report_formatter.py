"""One report format shared by scheduled and manual delivery."""
import json
from datetime import datetime
from zoneinfo import ZoneInfo

BJ=ZoneInfo('Asia/Shanghai')

def bj(value):
    dt=datetime.fromisoformat(str(value).replace('Z','+00:00')).astimezone(BJ)
    return dt.strftime('%Y年%m月%d日 %H:%M')

def _zones(item,context):
    price=float(item['price']); day=context.get('_market',{}); levels=[]
    for tf in ('M15','M30','H1'):
        x=context.get(tf,{})
        levels += [float(x[k]) for k in ('ma20','ma60','ma200') if x.get(k) is not None]
    levels += [float(day[k]) for k in ('previous_close','today_open','today_high','today_low') if day.get(k) is not None]
    support=max((x for x in levels if x<price),default=price-5); resistance=min((x for x in levels if x>price),default=price+5)
    width=max(.8,float(day.get('day_range',20))*.035)
    zone=lambda x:(round(x-width,2),round(x+width,2))
    return zone(support),zone(resistance),width

def build_report(item):
    context=json.loads(item.get('indicators_json','{}')); day=context.get('_market',{}); support,resistance,width=_zones(item,context)
    candles=[s['label'] for values in context.get('_candles',{}).values() for s in values]
    probs=(float(item['p_up']),float(item['p_range']),float(item['p_down'])); spread=max(probs)-min(probs)
    no_edge=item['decision']=='flat' or spread<.08
    if no_edge:
        verdict='当前不操作：多空概率接近，等待价格离开核心区间后再判断。'
    else:
        verdict=('偏多观察' if item['direction']=='up' else '偏空观察')+'：只在区间与M5确认同时满足时考虑。'
    s1,s2=support;r1,r2=resistance; price=float(item['price'])
    conditional=(f"- 突破做多：M5收盘站稳 {r2:.2f} 上方，随后没有重新跌回阻力区。\n"
                 f"- 回踩做多：回落至 {s1:.2f}–{s2:.2f}，M5出现看涨吞没或长下影拒绝。\n"
                 f"- 突破做空：M5收盘跌破 {s1:.2f}，随后反抽未回到支撑区。\n"
                 f"- 反弹做空：反弹至 {r1:.2f}–{r2:.2f}，M5出现看跌吞没或长上影拒绝。")
    body=(f"XAUUSD 黄金分析报告\n\n生成时间：{bj(item['created_at'])}（北京时间）\n有效期：{bj(item['created_at'])} 至 {bj(item['valid_until'])}（北京时间）\n\n"
          f"【结论】\n{verdict}\n\n【今日行情】\n昨日收盘：{day.get('previous_close','—')}\n今日开盘：{day.get('today_open','—')}\n当前价格：{price}\n今日最高：{day.get('today_high','—')}\n今日最低：{day.get('today_low','—')}\n今日波动：{day.get('day_range','—')}\n今日涨跌：{day.get('change','—')}（{float(day.get('change_pct',0)):+.2%}）\n今日振幅：{float(day.get('amplitude_pct',0)):.2%}\n\n"
          f"【概率】\n上涨：{probs[0]:.0%}　震荡：{probs[1]:.0%}　下跌：{probs[2]:.0%}\n\n【核心区间】\n支撑区：{s1:.2f}–{s2:.2f}\n阻力区：{r1:.2f}–{r2:.2f}\n目标价区间：{item['target_low']}–{item['target_high']}\nK线确认：{'、'.join(candles) if candles else '暂无有效形态'}\n\n【条件建议】\n{conditional}\n入场条件：必须等待M5收盘及对应K线形态确认；当前不满足时继续空仓。\n\n【风险区间】\n多单失效区：{s1-width:.2f}–{s1:.2f}\n空单失效区：{r2:.2f}–{r2+width:.2f}\nTP1参考：{r1:.2f}–{r2:.2f}\nTP2参考：{r2+width:.2f}–{r2+width*2:.2f}\n\n【禁止事项】\n禁止追涨追跌；禁止未等M5收盘；禁止新闻前后30分钟开仓；禁止点差异常时操作；禁止目标空间不足时勉强交易。\n\n报告编号：{item['id']}")
    return 'Aurum Signal 黄金分析报告',body

