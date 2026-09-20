"""MT5 只读适配器。明确不包含 order_send 或任何交易操作。"""
TIMEFRAMES=('M5','M15','M30','H1')
import broker_clock
from datetime import datetime, time, timezone
from zoneinfo import ZoneInfo


def _completed_rates(rates):
    """MT5 position 0 is the forming bar; advisory indicators use closed bars."""
    return rates[:-1]


def _today_entries(mt5, symbol):
    """Count today's opening deals for this symbol without placing or changing orders."""
    now = datetime.now(timezone.utc)
    local = now.astimezone(ZoneInfo('Asia/Shanghai'))
    start = datetime.combine(local.date(), time.min, ZoneInfo('Asia/Shanghai')).astimezone(timezone.utc)
    deals = mt5.history_deals_get(start, now)
    if deals is None:
        return {'available': False, 'count': None, 'tickets': []}
    opening = {mt5.DEAL_ENTRY_IN, mt5.DEAL_ENTRY_INOUT}
    matched = [d for d in deals if d.symbol == symbol and d.entry in opening]
    return {'available': True, 'count': len(matched), 'tickets': [int(d.ticket) for d in matched]}

def snapshot(symbol='XAUUSD',bars=240):
    try: import MetaTrader5 as mt5
    except ImportError as exc: raise RuntimeError('请在安装了 MetaTrader5 Python 包的 Windows 环境运行') from exc
    if not mt5.initialize(timeout=10000): raise RuntimeError(f'MT5连接失败: {mt5.last_error()}')
    try:
        offset = broker_clock.offset(mt5)
        info=mt5.symbol_info_tick(symbol)
        if info is None: raise RuntimeError(f'找不到品种 {symbol}，请检查经纪商后缀')
        mapping={'M5':mt5.TIMEFRAME_M5,'M15':mt5.TIMEFRAME_M15,'M30':mt5.TIMEFRAME_M30,'H1':mt5.TIMEFRAME_H1,'D1':mt5.TIMEFRAME_D1}
        candles={}
        for name,tf in mapping.items():
            needed=65 if name=='D1' else bars
            # D1 retains the current broker day for today's OHLC summary.  All
            # signal timeframes explicitly discard the still-forming bar.
            requested=needed if name=='D1' else needed+1
            rates=mt5.copy_rates_from_pos(symbol,tf,0,requested)
            if rates is None or len(rates)<requested:raise RuntimeError(f'{name} K线不足：需要{requested}根')
            if name!='D1':
                rates=_completed_rates(rates)
            candles[name]=broker_clock.candles(rates, offset)
        return {'symbol':symbol,'bid':info.bid,'ask':info.ask,'spread':info.ask-info.bid,
                'time_msc':info.time_msc-offset*1000,'candles':candles,
                'daily_entries':_today_entries(mt5,symbol)}
    finally: mt5.shutdown()


def history(symbol, start, end):
    """Read a prediction-specific UTC interval for independent shadow settlement."""
    import MetaTrader5 as mt5
    if not mt5.initialize(timeout=10000):
        raise RuntimeError(f'MT5连接失败: {mt5.last_error()}')
    try:
        offset = broker_clock.offset(mt5)
        query_start, query_end = broker_clock.interval(start, end, offset)
        rates = mt5.copy_rates_range(symbol, mt5.TIMEFRAME_M5, query_start, query_end)
        if rates is None:
            raise RuntimeError(f'M5历史读取失败: {mt5.last_error()}')
        return broker_clock.candles(rates, offset)
    finally:
        mt5.shutdown()


def quote(symbol='XAUUSD'):
    """Lightweight read-only health probe; no candle/news collection."""
    import MetaTrader5 as mt5
    if not mt5.initialize(timeout=10000):
        raise RuntimeError('MT5 connection failed')
    try:
        offset = broker_clock.offset(mt5)
        tick=mt5.symbol_info_tick(symbol)
        if tick is None:
            raise RuntimeError('MT5 quote unavailable')
        return {'time_msc':tick.time_msc-offset*1000,'bid':tick.bid,'ask':tick.ask}
    finally:
        mt5.shutdown()
