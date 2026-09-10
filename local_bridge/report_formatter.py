"""One clear report format shared by scheduled and manual delivery."""
import json
from datetime import datetime
from zoneinfo import ZoneInfo

BJ = ZoneInfo("Asia/Shanghai")


def bj(value):
    dt = datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(BJ)
    return dt.strftime("%Y年%m月%d日 %H:%M")


def _zones(item, context):
    price = float(item["price"])
    day = context.get("_market", {})
    levels = []
    for tf in ("M15", "M30", "H1"):
        values = context.get(tf, {})
        levels += [float(values[key]) for key in ("ma20", "ma60", "ma200") if values.get(key) is not None]
    levels += [float(day[key]) for key in ("previous_close", "today_open", "today_high", "today_low") if day.get(key) is not None]
    support = max((level for level in levels if level < price), default=price - 5)
    resistance = min((level for level in levels if level > price), default=price + 5)
    width = max(0.8, float(day.get("day_range", 20)) * 0.035)
    zone = lambda level: (round(level - width, 2), round(level + width, 2))
    return zone(support), zone(resistance), width


def build_report(item):
    context = json.loads(item.get("indicators_json", "{}"))
    day = context.get("_market", {})
    support, resistance, width = _zones(item, context)
    candles = [signal["label"] for values in context.get("_candles", {}).values() for signal in values]
    candle_text = "、".join(dict.fromkeys(candles)) if candles else "暂无有效形态"
    probs = (float(item["p_up"]), float(item["p_range"]), float(item["p_down"]))
    spread = max(probs) - min(probs)
    no_edge = item["decision"] == "flat" or spread < 0.08
    s1, s2 = support
    r1, r2 = resistance
    price = float(item["price"])

    long_stop = (s1 - width, s1)
    short_stop = (r2, r2 + width)
    long_tp2 = (r2 + width, r2 + width * 2)
    short_tp2 = (s1 - width * 2, s1 - width)

    if no_edge:
        if spread >= 0.08 and item["direction"] in ("up", "down"):
            bias = "上涨" if item["direction"] == "up" else "下跌"
            verdict = f"当前不操作。方向概率偏{bias}，但入场条件尚未满足；只观察关键区确认，不按现价追单。"
        else:
            verdict = "当前不操作。多空优势不明显，先观察上方阻力区和下方支撑区。"
        breakout_long_stop = (r1 - width, r1)
        breakout_short_stop = (s2, s2 + width)
        breakout_long_tp1 = (r2 + width, r2 + width * 2)
        breakout_long_tp2 = (r2 + width * 2, r2 + width * 3)
        breakout_short_tp1 = (s1 - width * 2, s1 - width)
        breakout_short_tp2 = (s1 - width * 3, s1 - width * 2)
        long_plan = (
            f"上方方案｜突破做多\n等 M5 收盘站稳 {r1:.2f}–{r2:.2f}，回踩不破后再考虑。\n"
            f"多单失效区：{breakout_long_stop[0]:.2f}–{breakout_long_stop[1]:.2f}。\n"
            f"多单目标：TP1 {breakout_long_tp1[0]:.2f}–{breakout_long_tp1[1]:.2f} → TP2 {breakout_long_tp2[0]:.2f}–{breakout_long_tp2[1]:.2f}。"
        )
        short_plan = (
            f"下方方案｜突破做空\n等 M5 收盘跌破 {s1:.2f}–{s2:.2f}，反抽不过后再考虑。\n"
            f"空单失效区：{breakout_short_stop[0]:.2f}–{breakout_short_stop[1]:.2f}。\n"
            f"空单目标：TP1 {breakout_short_tp1[0]:.2f}–{breakout_short_tp1[1]:.2f} → TP2 {breakout_short_tp2[0]:.2f}–{breakout_short_tp2[1]:.2f}。"
        )
        # Put the stronger observed direction first while keeping both conditional plans.
        main_plan = f"{short_plan}\n\n{long_plan}" if item["direction"] == "down" else f"{long_plan}\n\n{short_plan}"
    elif item["direction"] == "up":
        verdict = f"偏多观察：等 {s1:.2f}–{s2:.2f} 回踩企稳做多；若不回踩，只观察 {r1:.2f}–{r2:.2f} 的有效突破。"
        main_plan = (
            f"理想入场区：{s1:.2f}–{s2:.2f}；核心是支撑区不被 M5 收盘有效跌破。\n"
            "确认后再考虑：M5 出现止跌、形成更高低点、看涨吞没或长下影拒绝。\n"
            f"止损/失效区：{long_stop[0]:.2f}–{long_stop[1]:.2f} 下方。\n"
            f"目标：TP1 {r1:.2f}–{r2:.2f} → TP2 {long_tp2[0]:.2f}–{long_tp2[1]:.2f}。"
        )
    else:
        verdict = f"偏空观察：等 {r1:.2f}–{r2:.2f} 反弹受阻做空；若不反弹，只观察 {s1:.2f}–{s2:.2f} 的有效跌破。"
        main_plan = (
            f"理想入场区：{r1:.2f}–{r2:.2f}；核心是阻力区不被 M5 收盘有效突破。\n"
            "确认后再考虑：M5 出现滞涨、形成更低高点、看跌吞没或长上影拒绝。\n"
            f"止损/失效区：{short_stop[0]:.2f}–{short_stop[1]:.2f} 上方。\n"
            f"目标：TP1 {s1:.2f}–{s2:.2f} → TP2 {short_tp2[0]:.2f}–{short_tp2[1]:.2f}。"
        )

    body = (
        f"XAUUSD 黄金分析报告\n\n"
        f"【当前抓取价格】\n{price:.2f}\n\n"
        f"【当前建议】\n{verdict}\n\n"
        f"【观察与操作方案】\n{main_plan}\n\n"
        "【统一入场条件】\n必须等待 M5 K线收盘确认，再观察下一根K线是否延续；只有价格位置、K线形态和指标方向同时支持时才考虑。\n\n"
        "【取消计划】\nM15/M5结构反向转弱；价格直接穿过失效区；高影响新闻前后30分钟；点差异常；价格已接近目标、剩余空间不足；报告即将失效。\n\n"
        "【禁止事项】\n禁止追涨追跌；禁止在K线尚未收盘时猜突破；禁止因为错过入场而提高价格追单；禁止同时执行多空两套方案。\n\n"
        f"【关键区间】\n支撑区：{s1:.2f}–{s2:.2f}\n阻力区：{r1:.2f}–{r2:.2f}\n预测目标价区间：{float(item['target_low']):.2f}–{float(item['target_high']):.2f}\n当前K线形态：{candle_text}\n\n"
        f"【方向概率】\n上涨：{probs[0]:.0%}　震荡：{probs[1]:.0%}　下跌：{probs[2]:.0%}\n\n"
        f"【今日行情】\n昨日收盘：{day.get('previous_close', '—')}\n今日开盘：{day.get('today_open', '—')}\n今日最高：{day.get('today_high', '—')}\n今日最低：{day.get('today_low', '—')}\n今日波动：{day.get('day_range', '—')}\n今日涨跌：{day.get('change', '—')}（{float(day.get('change_pct', 0)):+.2%}）\n今日振幅：{float(day.get('amplitude_pct', 0)):.2%}\n\n"
        f"【报告时间】\n生成：{bj(item['created_at'])}（北京时间）\n有效至：{bj(item['valid_until'])}（北京时间）\n报告编号：{item['id']}"
    )
    return "Aurum Signal 黄金分析报告", body
