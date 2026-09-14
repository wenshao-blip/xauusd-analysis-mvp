"""MT5 只读适配器。明确不包含 order_send 或任何交易操作。"""
TIMEFRAMES=('M5','M15','M30','H1')
import broker_clock
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
            rates=mt5.copy_rates_from_pos(symbol,tf,0,needed)
            if rates is None or len(rates)<needed:raise RuntimeError(f'{name} K线不足：需要{needed}根')
            candles[name]=broker_clock.candles(rates, offset)
        return {'symbol':symbol,'bid':info.bid,'ask':info.ask,'spread':info.ask-info.bid,'time_msc':info.time_msc-offset*1000,'candles':candles}
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
