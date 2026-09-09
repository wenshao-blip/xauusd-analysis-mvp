"""MT5 只读适配器。明确不包含 order_send 或任何交易操作。"""
TIMEFRAMES=('M5','M15','M30','H1')
def snapshot(symbol='XAUUSD',bars=240):
    try: import MetaTrader5 as mt5
    except ImportError as exc: raise RuntimeError('请在安装了 MetaTrader5 Python 包的 Windows 环境运行') from exc
    if not mt5.initialize(): raise RuntimeError(f'MT5连接失败: {mt5.last_error()}')
    try:
        info=mt5.symbol_info_tick(symbol)
        if info is None: raise RuntimeError(f'找不到品种 {symbol}，请检查经纪商后缀')
        mapping={'M5':mt5.TIMEFRAME_M5,'M15':mt5.TIMEFRAME_M15,'M30':mt5.TIMEFRAME_M30,'H1':mt5.TIMEFRAME_H1}
        candles={}
        for name,tf in mapping.items():
            rates=mt5.copy_rates_from_pos(symbol,tf,0,bars)
            if rates is None or len(rates)<bars:raise RuntimeError(f'{name} K线不足：需要{bars}根')
            candles[name]=[{field:(value.item() if hasattr(value,'item') else value) for field,value in zip(rates.dtype.names,row)} for row in rates]
        return {'symbol':symbol,'bid':info.bid,'ask':info.ask,'spread':info.ask-info.bid,'time_msc':info.time_msc,'candles':candles}
    finally: mt5.shutdown()
