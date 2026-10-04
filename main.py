"""XAUUSD educational signal engine; no broker orders are submitted."""
import os
import time
import json
import websocket
from websocket import WebSocketBadStatusException
import pandas as pd
from risk import RiskManager

SYMBOL = os.getenv('SYMBOL', 'XAU/USD')
DERIV_APP_ID = os.getenv('DERIV_APP_ID', '1089')
INTERVAL = os.getenv('INTERVAL', '15min')

def indicators(data):
    close = data['close']
    data['ema20'] = close.ewm(span=20, adjust=False).mean()
    data['ema50'] = close.ewm(span=50, adjust=False).mean()
    delta = close.diff()
    up = delta.clip(lower=0).ewm(alpha=1/14, adjust=False).mean()
    down = (-delta.clip(upper=0)).ewm(alpha=1/14, adjust=False).mean()
    data['rsi'] = 100 - 100/(1 + up/down.replace(0, float('nan')))
    tr = pd.concat([data.high-data.low, (data.high-data.close.shift()).abs(), (data.low-data.close.shift()).abs()], axis=1).max(axis=1)
    data['atr'] = tr.ewm(alpha=1/14, adjust=False).mean()
    return data

def signal(df):
    required = ('open', 'high', 'low', 'close')
    if not isinstance(df, pd.DataFrame) or len(df) < 60 or any(k not in df.columns for k in required):
        return {'signal': 'WAIT', 'reason': 'Insufficient candles'}
    df = indicators(df.copy())
    a, b = df.iloc[-2], df.iloc[-1]
    if pd.isna(b.rsi) or pd.isna(b.atr): return {'signal':'WAIT'}
    trend_up = b.ema20 > b.ema50 and b.close > b.ema20
    trend_down = b.ema20 < b.ema50 and b.close < b.ema20
    rising = b.close > a.close
    falling = b.close < a.close
    direction = 'BUY' if trend_up and rising and 52 <= b.rsi <= 68 else 'SELL' if trend_down and falling and 32 <= b.rsi <= 48 else 'WAIT'
    if direction == 'WAIT': return {'signal':'WAIT', 'price':round(b.close,2)}
    stop = b.close - 1.5*b.atr if direction == 'BUY' else b.close + 1.5*b.atr
    target = b.close + 2.25*b.atr if direction == 'BUY' else b.close - 2.25*b.atr
    return {'signal':direction, 'price':round(b.close,2), 'stop':round(stop,2), 'target':round(target,2), 'rsi':round(b.rsi,1), 'mode':'PAPER_ONLY'}

def deriv_request(ws, payload):
    ws.send(json.dumps(payload))
    response = json.loads(ws.recv())
    if response.get('error'):
        raise RuntimeError('Deriv: ' + response['error'].get('message', 'Request failed'))
    return response

def fetch():
    """Read public Deriv gold candles; token is not used for public market data."""
    # Try the documented public endpoint first; retain legacy as fallback.
    ws = None
    failures = []
    for endpoint in (
        'wss://api.derivws.com/trading/v1/options/ws/public',
        'wss://ws.derivws.com/websockets/v3?app_id=' + DERIV_APP_ID,
    ):
        try:
            ws = websocket.create_connection(endpoint, timeout=15, origin='https://app.deriv.com')
            break
        except Exception as exc:
            code = getattr(exc, 'status_code', None)
            failures.append(type(exc).__name__ + ((' HTTP ' + str(code)) if code else ''))
    if ws is None:
        raise RuntimeError('Deriv public feed unavailable (' + '; '.join(failures) + '); no signal generated')
    try:
        assets = deriv_request(ws, {'active_symbols': 'brief'})
        matches = [item for item in assets.get('active_symbols', [])
                   if 'gold' in item.get('display_name', '').lower()
                   or item.get('symbol', '').lower() in ('frxxauusd', 'xauusd')]
        if not matches:
            raise RuntimeError('Gold is not available in Deriv active symbols for this app')
        asset = next((a for a in matches if a.get('symbol', '').lower() in
                      ('frxxauusd', 'xauusd')), matches[0])
        granularity = {'1min': 60, '5min': 300, '15min': 900, '30min': 1800,
                       '1h': 3600}.get(INTERVAL, 900)
        data = deriv_request(ws, {'ticks_history': asset['symbol'],
                                  'end': 'latest', 'style': 'candles',
                                  'granularity': granularity, 'count': 151})
        candles = data.get('candles') or []
        if len(candles) < 52:
            raise RuntimeError('Insufficient Deriv gold candle history')
        df = pd.DataFrame(candles)
        for key in ('open', 'high', 'low', 'close'):
            df[key] = pd.to_numeric(df[key], errors='raise')
        # Exclude the newest candle because it may still be forming.
        return df.iloc[:-1].reset_index(drop=True)
    finally:
        ws.close()

if __name__ == '__main__':
    risk = RiskManager()
    print({'mode':'PAPER_ONLY','starting_balance':risk.balance,'risk_per_trade_usd':risk.budget(),'daily_loss_limit_usd':risk.day_start_balance*0.02,'note':'No broker execution or automatic P&L feed.'}, flush=True)
    while True:
        try:
            result = signal(fetch()) if risk.budget() > 0 else {'signal':'SUSPENDED'}
            if result.get('signal') in ('BUY','SELL'):
                result['max_planned_risk_usd'] = round(risk.budget(), 2)
                result['lot_size'] = None
                result['warning'] = 'Lot size requires verified broker contract specs; signal is not an order'
            print(result, flush=True)
        except Exception as exc: print({'error':str(exc)}, flush=True)
        time.sleep(900)
