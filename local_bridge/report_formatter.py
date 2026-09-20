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
    # Confirmed swing highs/lows are the primary structure source.  Moving
    # averages and day prices below are only confluence, never a claim about
    # where a "main force" is positioned.
    structure = context.get("_structure", {})
    levels += [float(x["price"]) for x in structure.get("supports", []) + structure.get("resistances", [])]
    for tf in ("M15", "M30", "H1"):
        values = context.get(tf, {})
        levels += [float(values[key]) for key in ("ma20", "ma60", "ma200") if values.get(key) is not None]
    levels += [float(day[key]) for key in ("previous_close", "today_open", "today_high", "today_low") if day.get(key) is not None]
    support = max((level for level in levels if level < price), default=price - 5)
    resistance = min((level for level in levels if level > price), default=price + 5)
    # A zone is deliberately narrower than a target leg.  It marks a price area,
    # while TP1/TP2 are based on actual M15 volatility and the next structure.
    atr = max(0.8, float(context.get("M15", {}).get("atr") or 0))
    width = max(0.8, atr * 0.35)
    zone = lambda level: (round(level - width, 2), round(level + width, 2))
    lower_structure = [float(x["price"]) for x in structure.get("supports", []) if float(x["price"]) < support - width * .3]
    upper_structure = [float(x["price"]) for x in structure.get("resistances", []) if float(x["price"]) > resistance + width * .3]
    structural_low = max(lower_structure, default=support - atr * .9)
    structural_high = min(upper_structure, default=resistance + atr * .9)
    return zone(support), zone(resistance), zone(structural_low), zone(structural_high), width, atr


def _rr(entry, stop, target):
    """Return an auditable first-target reward/risk ratio."""
    risk = abs(float(entry) - float(stop))
    reward = abs(float(target) - float(entry))
    return reward / risk if risk > 0 else 0.0


def build_report(item):
    context = json.loads(item.get("indicators_json", "{}"))
    day = context.get("_market", {})
    support, resistance, structural_low, structural_high, width, atr = _zones(item, context)
    candles = [signal["label"] for values in context.get("_candles", {}).values() for signal in values]
    candle_text = "、".join(dict.fromkeys(candles)) if candles else "暂无有效形态"
    probs = (float(item["p_up"]), float(item["p_range"]), float(item["p_down"]))
    spread = max(probs) - min(probs)
    no_edge = item["decision"] == "flat" or spread < 0.08
    s1, s2 = support
    r1, r2 = resistance
    price = float(item["price"])

    # TP1 is roughly one M15 ATR from the confirmed entry; TP2 is two ATRs away.
    # Their bands retain a small ATR-based tolerance instead of using a fixed gap.
    target_band = max(0.8, atr * 0.25)
    target = lambda midpoint: (round(midpoint - target_band, 2), round(midpoint + target_band, 2))
    long_entry = (s1 + s2) / 2
    short_entry = (r1 + r2) / 2
    long_stop = structural_low
    short_stop = structural_high
    long_tp1 = target(max((r1 + r2) / 2, long_entry + atr))
    long_tp2 = target(max((r1 + r2) / 2 + atr, long_entry + atr * 2))
    short_tp1 = target(min((s1 + s2) / 2, short_entry - atr))
    short_tp2 = target(min((s1 + s2) / 2 - atr, short_entry - atr * 2))

    long_rr = _rr(long_entry, sum(long_stop) / 2, sum(long_tp1) / 2)
    short_rr = _rr(short_entry, sum(short_stop) / 2, sum(short_tp1) / 2)
    minimum_rr = 1.0

    # A directional score is not enough to publish a trade plan.  If the next
    # confirmed structure cannot offer at least 1R at TP1, the only valid main
    # direction is flat.  This prevents a visually attractive report from
    # recommending a trade whose nearby target has already consumed the edge.
    insufficient_space = (
        item["direction"] == "up" and long_rr < minimum_rr
    ) or (
        item["direction"] == "down" and short_rr < minimum_rr
    )
    no_edge = no_edge or insufficient_space

    if no_edge:
        if spread >= 0.08 and item["direction"] in ("up", "down"):
            bias = "上涨" if item["direction"] == "up" else "下跌"
            verdict = f"当前不操作。方向概率偏{bias}，但入场条件尚未满足；只观察关键区确认，不按现价追单。"
        else:
            verdict = "当前不操作。多空优势不明显，先观察上方阻力区和下方支撑区。"
        main_direction = "空仓等待"
        if insufficient_space:
            verdict = "当前不操作。最近结构目标不足以提供至少 1:1 的 TP1 风险收益比，等待新的价格结构。"
        main_plan = (
            "不预设多空挂单。等待下一根完整 M15 形成新的结构区，再重新计算入场、失效区和目标；"
            "当前报告中的支撑阻力仅用于观察。"
        )
    elif item["direction"] == "up":
        main_direction = "回踩做多"
        verdict = f"偏多观察：等 {s1:.2f}–{s2:.2f} 回踩企稳做多；若不回踩，只观察 {r1:.2f}–{r2:.2f} 的有效突破。"
        main_plan = (
            f"理想入场区：{s1:.2f}–{s2:.2f}；核心是支撑区不被 M5 收盘有效跌破。\n"
            "确认后再考虑：M5 出现止跌、形成更高低点、看涨吞没或长下影拒绝。\n"
            f"入场确认失效：M5 收盘跌破 {s1:.2f}–{s2:.2f} 下沿后，下一根 M5 未收回，暂停入场。\n"
            f"结构失效 / 计划取消：M15 收盘有效跌破 {long_stop[0]:.2f}–{long_stop[1]:.2f}。\n"
            f"目标：TP1 {long_tp1[0]:.2f}–{long_tp1[1]:.2f} → TP2 {long_tp2[0]:.2f}–{long_tp2[1]:.2f}。"
        )
    else:
        main_direction = "反弹做空"
        verdict = f"偏空观察：等 {r1:.2f}–{r2:.2f} 反弹受阻做空；若不反弹，只观察 {s1:.2f}–{s2:.2f} 的有效跌破。"
        main_plan = (
            f"理想入场区：{r1:.2f}–{r2:.2f}；核心是阻力区不被 M5 收盘有效突破。\n"
            "确认后再考虑：M5 出现滞涨、形成更低高点、看跌吞没或长上影拒绝。\n"
            f"入场确认失效：M5 收盘突破 {r1:.2f}–{r2:.2f} 上沿后，下一根 M5 未回落，暂停入场。\n"
            f"结构失效 / 计划取消：M15 收盘有效突破 {short_stop[0]:.2f}–{short_stop[1]:.2f}。\n"
            f"目标：TP1 {short_tp1[0]:.2f}–{short_tp1[1]:.2f} → TP2 {short_tp2[0]:.2f}–{short_tp2[1]:.2f}。"
        )

    # New reports carry the selected result of the multi-scenario candidate
    # engine.  The fallback branches above keep old frozen ledger rows readable.
    strategy = context.get("_strategy")
    if strategy:
        main_direction = strategy["label"]
        if strategy["name"] == "flat":
            reasons = "；".join(strategy.get("reasons", [])) or "没有候选通过门槛"
            verdict = f"当前不操作。{reasons}。"
            main_plan = "继续观察支撑、阻力和完整M5收盘；下一次报告重新比较突破、回踩、反弹和区间候选。"
        else:
            entry = strategy["entry"]; stop = strategy["stop"]
            stp1 = strategy["tp1"]; stp2 = strategy["tp2"]
            confirmations = "；".join(strategy.get("confirmation", []))
            reasons = "；".join(strategy.get("reasons", []))
            verdict = f"当前评分最高的场景是{strategy['label']}，仅在确认条件全部满足后考虑。"
            main_plan = (
                f"理想入场区：{entry[0]:.2f}–{entry[1]:.2f}。\n"
                f"确认条件：{confirmations}。\n"
                f"结构失效区：{stop[0]:.2f}–{stop[1]:.2f}。\n"
                f"目标：TP1 {stp1[0]:.2f}–{stp1[1]:.2f} → TP2 {stp2[0]:.2f}–{stp2[1]:.2f}。\n"
                f"候选得分：{strategy['score']:.1f}/100；TP1风险收益：{strategy['rr_tp1']:.2f}R。\n"
                f"选择依据：{reasons}。"
            )

    body = (
        f"XAUUSD 黄金分析报告\n\n"
        f"【当前抓取价格】\n{price:.2f}\n\n"
        f"【方向概率】\n上涨：{probs[0]:.0%}　震荡：{probs[1]:.0%}　下跌：{probs[2]:.0%}\n\n"
        f"【唯一主方向】\n{main_direction}\n\n"
        f"【当前建议】\n{verdict}\n\n"
        f"【观察与操作方案】\n{main_plan}\n\n"
        "【统一入场条件】\n必须等待 M5 K线收盘确认，再观察下一根K线是否延续；只有价格位置、K线形态和指标方向同时支持时才考虑。\n\n"
        "【取消计划】\nM15/M5结构反向转弱；价格直接穿过失效区；高影响新闻前后30分钟；点差异常；价格已接近目标、剩余空间不足；报告即将失效。\n\n"
        "【禁止事项】\n禁止追涨追跌；禁止在K线尚未收盘时猜突破；禁止因为错过入场而提高价格追单；禁止同时执行多空两套方案。\n\n"
        f"【关键区间】\n支撑区：{s1:.2f}–{s2:.2f}\n阻力区：{r1:.2f}–{r2:.2f}\nM15 平均波动（ATR）：{atr:.2f}\n预测方向价区间：{float(item['target_low']):.2f}–{float(item['target_high']):.2f}\n当前K线形态：{candle_text}\n\n"
        f"【计划质量】\nTP1最低风险收益门槛：1.00R\n做多候选：{long_rr:.2f}R　做空候选：{short_rr:.2f}R\n\n"
        f"【今日行情】\n昨日收盘：{day.get('previous_close', '—')}\n今日开盘：{day.get('today_open', '—')}\n今日最高：{day.get('today_high', '—')}\n今日最低：{day.get('today_low', '—')}\n今日波动：{day.get('day_range', '—')}\n今日涨跌：{day.get('change', '—')}（{float(day.get('change_pct', 0)):+.2%}）\n今日振幅：{float(day.get('amplitude_pct', 0)):.2%}\n\n"
        f"【报告时间】\n生成：{bj(item['created_at'])}（北京时间）\n有效至：{bj(item['valid_until'])}（北京时间）\n报告编号：{item['id']}"
    )
    return "Aurum Signal 黄金分析报告", body
