"""Auditable multi-scenario candidate generation for the advisory report.

This module never places orders.  It compares several market scenarios using
completed-bar evidence and returns one main advisory plan or ``flat``.
"""
from __future__ import annotations


LABELS = {
    "breakout_long": "突破做多",
    "breakout_short": "突破做空",
    "pullback_long": "回踩做多",
    "rebound_short": "反弹做空",
    "range_long": "区间低吸",
    "range_short": "区间高空",
    "false_breakout_long": "假突破反转做多",
    "false_breakout_short": "假突破反转做空",
    "flat": "空仓等待",
}
TRADE_NAMES = tuple(name for name in LABELS if name != "flat")
MIN_SCORE = 65
MIN_RR = 1.0
OPPOSING_SCORE_GAP = 4


def _zone(midpoint, width):
    return [round(midpoint - width, 2), round(midpoint + width, 2)]


def _mid(zone):
    return sum(zone) / 2


def _rr(entry, stop, target):
    risk = abs(entry - stop)
    return abs(target - entry) / risk if risk else 0.0


def _nearest_levels(indicators, price):
    structure = indicators.get("_structure", {})
    supports = sorted(float(x["price"]) for x in structure.get("supports", []) if float(x["price"]) < price)
    resistances = sorted(float(x["price"]) for x in structure.get("resistances", []) if float(x["price"]) > price)
    return (supports[-1] if supports else None, resistances[0] if resistances else None,
            supports[-2] if len(supports) > 1 else None, resistances[1] if len(resistances) > 1 else None)


def _trend_score(indicators):
    score = 0
    reasons = []
    for tf, weight in (("H1", 2), ("M30", 1)):
        x = indicators[tf]
        direction = sum((1 if x["close"] > x["ma20"] else -1,
                         1 if x["ma20"] > x["ma60"] else -1,
                         1 if x["macd_hist"] > 0 else -1,
                         1 if x["+di"] > x["-di"] else -1))
        score += weight * direction
        reasons.append(f"{tf}趋势分{direction:+d}")
    return score, reasons


def _signal_types(indicators, timeframe="M5"):
    return {x["type"] for x in indicators.get("_candles", {}).get(timeframe, [])}


def _false_breakout(candles):
    """Detect a completed sweep-and-rejection followed by a confirming close."""
    bars = candles.get("M5", [])
    if len(bars) < 24:
        return None
    history, sweep, confirm = bars[-24:-2], bars[-2], bars[-1]
    prior_high = max(float(x["high"]) for x in history)
    prior_low = min(float(x["low"]) for x in history)
    sweep_high, sweep_low = float(sweep["high"]), float(sweep["low"])
    sweep_close = float(sweep["close"])
    confirm_close, confirm_open = float(confirm["close"]), float(confirm["open"])
    if sweep_high > prior_high and sweep_close <= prior_high and confirm_close < prior_high and confirm_close < confirm_open:
        return {"side": "short", "level": prior_high, "extreme": sweep_high}
    if sweep_low < prior_low and sweep_close >= prior_low and confirm_close > prior_low and confirm_close > confirm_open:
        return {"side": "long", "level": prior_low, "extreme": sweep_low}
    return None


def _part(code, label, points, observed, rule, evidence):
    return {"code": code, "label": label, "points": round(points, 1),
            "observed": observed, "rule": rule, "evidence": evidence}


def _candidate(name, score_breakdown, entry, stop, tp1, tp2, reasons, confirmation):
    rr = _rr(_mid(entry), _mid(stop), _mid(tp1))
    score = max(0, min(100, sum(x["points"] for x in score_breakdown)))
    return {
        "name": name,
        "label": LABELS[name],
        "score": round(score, 1),
        "entry": entry,
        "stop": stop,
        "tp1": tp1,
        "tp2": tp2,
        "rr_tp1": round(rr, 2),
        "score_breakdown": score_breakdown,
        "hard_rejections": [],
        "status": "detected",
        "reasons": reasons,
        "confirmation": confirmation,
    }


def _flat(reasons, candidates=None, regime="unknown", rejection_codes=None, wait_for=None):
    return {
        "name": "flat", "label": LABELS["flat"], "score": 0.0,
        "entry": None, "stop": None, "tp1": None, "tp2": None,
        "rr_tp1": 0.0, "reasons": reasons, "confirmation": [],
        "score_breakdown": [], "hard_rejections": rejection_codes or [],
        "wait_for": wait_for or ["等待下一根完整M5或M15形成新的确认条件"],
        "regime": regime, "candidates": candidates or [],
    }


def select_strategy(market, news, directional_bias, allow_trade=True):
    """Rank breakout, continuation and range candidates; choose one or flat."""
    ind = market["indicators"]
    price = (float(market["bid"]) + float(market["ask"])) / 2
    atr = max(0.8, float(ind["M15"].get("atr") or 0.8))
    width = max(0.8, atr * 0.25)
    support, resistance, support2, resistance2 = _nearest_levels(ind, price)
    if support is None or resistance is None:
        return _flat(["有效支撑或阻力不足，不能构造可审计交易计划"],
                     rejection_codes=["STRUCTURE_MISSING"])

    trend, trend_reasons = _trend_score(ind)
    adx = max(float(ind["H1"]["adx"]), float(ind["M30"]["adx"]))
    regime = "trend" if adx >= 22 else "range"
    signals = _signal_types(ind)
    false_breakout = _false_breakout(market.get("candles", {}))
    bullish = bool(signals & {"bullish_engulfing", "lower_rejection", "breakout_up"})
    bearish = bool(signals & {"bearish_engulfing", "upper_rejection", "breakout_down"})
    spread = float(market.get("spread") or 0)
    candidates = []

    def levels(long, entry_mid, stop_mid, first_mid, second_mid):
        band = max(0.8, atr * 0.2)
        return (_zone(entry_mid, width), _zone(stop_mid, width),
                _zone(first_mid, band), _zone(second_mid, band))

    if false_breakout and false_breakout["side"] == "short" and bearish:
        entry, stop, tp1, tp2 = levels(False, false_breakout["level"], false_breakout["extreme"] + width,
                                       support, support2 or support - atr)
        parts=[_part("base","基础分",50,"候选已触发","所有候选从50分起算","规则基线"),
               _part("sweep","扫高收回确认",22,"已确认","扫高收回且下一根M5转弱","M5已收盘K线"),
               _part("trend","趋势配合",6 if trend<=0 else 0,trend,"非多头环境加6分","H1/M30指标")]
        candidates.append(_candidate("false_breakout_short", parts,
            entry, stop, tp1, tp2,
            ["M5扫过前高后收回", "下一根已收盘M5继续转弱", *trend_reasons],
            ["确认K线保持在被扫前高下方", "不得在价格已接近区间下沿时追空"]))
    if false_breakout and false_breakout["side"] == "long" and bullish:
        entry, stop, tp1, tp2 = levels(True, false_breakout["level"], false_breakout["extreme"] - width,
                                       resistance, resistance2 or resistance + atr)
        parts=[_part("base","基础分",50,"候选已触发","所有候选从50分起算","规则基线"),
               _part("sweep","扫低收回确认",22,"已确认","扫低收回且下一根M5转强","M5已收盘K线"),
               _part("trend","趋势配合",6 if trend>=0 else 0,trend,"非空头环境加6分","H1/M30指标")]
        candidates.append(_candidate("false_breakout_long", parts,
            entry, stop, tp1, tp2,
            ["M5扫过前低后收回", "下一根已收盘M5继续转强", *trend_reasons],
            ["确认K线保持在被扫前低上方", "不得在价格已接近区间上沿时追多"]))

    if "breakout_up" in signals and trend >= 2:
        entry, stop, tp1, tp2 = levels(True, resistance, resistance - atr * .8,
                                       resistance2 or resistance + atr, (resistance2 or resistance + atr) + atr)
        parts=[_part("base","基础分",50,"候选已触发","所有候选从50分起算","规则基线"),
               _part("confirm","M5突破确认",14,"向上突破","实体收盘突破加14分","M5已收盘K线"),
               _part("trend","多周期趋势",min(16,trend*2),trend,"趋势分×2，最高16分","H1/M30指标"),
               _part("adx","趋势强度",min(8,adx/5),round(adx,2),"ADX/5，最高8分","H1/M30 ADX")]
        candidates.append(_candidate("breakout_long", parts,
            entry, stop, tp1, tp2, trend_reasons + ["M5实体向上突破确认"],
            ["M5收盘站上突破区", "下一根M5不重新跌回突破区下方", "优先等待回踩不破"]))
    if "breakout_down" in signals and trend <= -2:
        entry, stop, tp1, tp2 = levels(False, support, support + atr * .8,
                                       support2 or support - atr, (support2 or support - atr) - atr)
        parts=[_part("base","基础分",50,"候选已触发","所有候选从50分起算","规则基线"),
               _part("confirm","M5突破确认",14,"向下突破","实体收盘突破加14分","M5已收盘K线"),
               _part("trend","多周期趋势",min(16,abs(trend)*2),trend,"趋势绝对分×2，最高16分","H1/M30指标"),
               _part("adx","趋势强度",min(8,adx/5),round(adx,2),"ADX/5，最高8分","H1/M30 ADX")]
        candidates.append(_candidate("breakout_short", parts,
            entry, stop, tp1, tp2, trend_reasons + ["M5实体向下突破确认"],
            ["M5收盘跌破突破区", "下一根M5不重新站回突破区上方", "优先等待反抽不过"]))

    near_support = price - support <= atr * .8
    near_resistance = resistance - price <= atr * .8
    if trend >= 3 and near_support and bullish and "breakout_up" not in signals:
        entry, stop, tp1, tp2 = levels(True, support, support2 or support - atr,
                                       resistance, resistance2 or resistance + atr)
        parts=[_part("base","基础分",50,"候选已触发","所有候选从50分起算","规则基线"),
               _part("location","接近支撑",8,round(price-support,2),"距离支撑不超过0.8 ATR","结构与现价"),
               _part("trend","多周期趋势",min(20,trend*2),trend,"趋势分×2，最高20分","H1/M30指标"),
               _part("regime","趋势环境",8 if regime=="trend" else 0,regime,"趋势环境加8分","ADX状态")]
        candidates.append(_candidate("pullback_long", parts,
            entry, stop, tp1, tp2, trend_reasons + ["价格接近支撑", "M5出现看涨确认"],
            ["M5在支撑区止跌收盘", "下一根M5保持更高低点", "M15结构不跌破失效区"]))
    if trend <= -3 and near_resistance and bearish and "breakout_down" not in signals:
        entry, stop, tp1, tp2 = levels(False, resistance, resistance2 or resistance + atr,
                                       support, support2 or support - atr)
        parts=[_part("base","基础分",50,"候选已触发","所有候选从50分起算","规则基线"),
               _part("location","接近阻力",8,round(resistance-price,2),"距离阻力不超过0.8 ATR","结构与现价"),
               _part("trend","多周期趋势",min(20,abs(trend)*2),trend,"趋势绝对分×2，最高20分","H1/M30指标"),
               _part("regime","趋势环境",8 if regime=="trend" else 0,regime,"趋势环境加8分","ADX状态")]
        candidates.append(_candidate("rebound_short", parts,
            entry, stop, tp1, tp2, trend_reasons + ["价格接近阻力", "M5出现看跌确认"],
            ["M5在阻力区受阻收盘", "下一根M5保持更低高点", "M15结构不突破失效区"]))

    if regime == "range" and near_support and bullish:
        entry, stop, tp1, tp2 = levels(True, support, support2 or support - atr, resistance, resistance + atr)
        parts=[_part("base","基础分",50,"候选已触发","所有候选从50分起算","规则基线"),
               _part("range_location","区间下沿确认",10,"支撑附近","低ADX且M5看涨拒绝加10分","ADX/结构/M5"),
               _part("bias","方向不冲突",8 if directional_bias!="down" else 0,directional_bias,"非偏空加8分","方向概率")]
        candidates.append(_candidate("range_long", parts, entry, stop, tp1, tp2,
            ["H1/M30 ADX显示震荡", "价格位于区间下沿", "M5看涨拒绝"],
            ["M5收盘守住区间下沿", "不得在区间中部追价"]))
    if regime == "range" and near_resistance and bearish:
        entry, stop, tp1, tp2 = levels(False, resistance, resistance2 or resistance + atr, support, support - atr)
        parts=[_part("base","基础分",50,"候选已触发","所有候选从50分起算","规则基线"),
               _part("range_location","区间上沿确认",10,"阻力附近","低ADX且M5看跌拒绝加10分","ADX/结构/M5"),
               _part("bias","方向不冲突",8 if directional_bias!="up" else 0,directional_bias,"非偏多加8分","方向概率")]
        candidates.append(_candidate("range_short", parts, entry, stop, tp1, tp2,
            ["H1/M30 ADX显示震荡", "价格位于区间上沿", "M5看跌拒绝"],
            ["M5收盘受阻于区间上沿", "不得在区间中部追价"]))

    hard_blocks = []
    if not allow_trade:
        hard_blocks.append({"code":"BASE_GATE_FAILED","message":"基础方向、形态或数据质量门槛未通过"})
    if not news.get("complete", False):
        hard_blocks.append({"code":"NEWS_INCOMPLETE","message":"新闻数据不完整"})
    if spread > atr * .15:
        hard_blocks.append({"code":"SPREAD_HIGH","message":"点差相对M15波动异常"})
    for candidate in candidates:
        candidate["hard_rejections"] = list(hard_blocks)
        if candidate["score"] < MIN_SCORE:
            candidate["hard_rejections"].append({"code":"SCORE_BELOW_65","message":"候选得分低于65分"})
        if candidate["rr_tp1"] < MIN_RR:
            candidate["hard_rejections"].append({"code":"RR_BELOW_1","message":"TP1风险收益低于1R"})
        candidate["status"] = "qualified" if not candidate["hard_rejections"] else "rejected"
    detected={x["name"]:x for x in candidates}
    summaries=[]
    for name in TRADE_NAMES:
        if name in detected:
            x=detected[name]
            summaries.append({key:x[key] for key in ("name","label","score","rr_tp1","status","score_breakdown","hard_rejections")})
        else:
            summaries.append({"name":name,"label":LABELS[name],"score":None,"rr_tp1":None,
                              "status":"not_triggered","score_breakdown":[],
                              "hard_rejections":[{"code":"NOT_TRIGGERED","message":"本轮没有形成必要确认"}]})
    summaries.sort(key=lambda x: (-1 if x["score"] is None else -x["score"], x["name"]))
    eligible = [x for x in candidates if x["status"] == "qualified"]
    if hard_blocks or not eligible:
        reasons = [x["message"] for x in hard_blocks] or ["没有候选同时通过65分和TP1至少1R门槛"]
        codes = [x["code"] for x in hard_blocks] or ["NO_QUALIFIED_CANDIDATE"]
        return _flat(reasons, summaries, regime, codes)
    long_side=sorted((x for x in eligible if x["name"].endswith("long")),key=lambda x:x["score"],reverse=True)
    short_side=sorted((x for x in eligible if x["name"].endswith("short")),key=lambda x:x["score"],reverse=True)
    if long_side and short_side and abs(long_side[0]["score"]-short_side[0]["score"]) <= OPPOSING_SCORE_GAP:
        return _flat([f"相反方向候选分差不超过{OPPOSING_SCORE_GAP}分"],summaries,regime,
                     ["OPPOSING_CANDIDATES_TOO_CLOSE"],
                     ["等待方向分差扩大", "等待新的完整M5确认淘汰其中一侧"])
    chosen = max(eligible, key=lambda x: (x["score"], x["rr_tp1"]))
    chosen["regime"] = regime
    chosen["candidates"] = summaries
    runner_up=sorted(eligible,key=lambda x:(x["score"],x["rr_tp1"]),reverse=True)[1:2]
    chosen["selection_reason"]=(f"{chosen['label']}以{chosen['score']:.1f}分通过全部硬门槛"+
        (f"，领先下一候选{chosen['score']-runner_up[0]['score']:.1f}分" if runner_up else "，且无其他合格候选"))
    return chosen
