"""XAUUSD educational signal engine; no broker orders are submitted."""
import os
import time
import requests
import pandas as pd
from risk import RiskManager

SYMBOL = os.getenv('SYMBOL', 'XAU/USD')
API_KEY = os.getenv('TWELVEDATA_API_KEY', '')
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

def fetch():
    if not API_KEY: raise RuntimeError('Set TWELVEDATA_API_KEY to enable live market signals')
    r = requests.get('https://api.twelvedata.com/time_series', params={'symbol':SYMBOL,'interval':INTERVAL,'outputsize':150,'apikey':API_KEY}, timeout=15)
    r.raise_for_status()
    payload = r.json()
    if 'values' not in payload: raise RuntimeError(str(payload.get('message', 'Market data unavailable')))
    df = pd.DataFrame(payload['values']).iloc[::-1].reset_index(drop=True)
    for k in ['open','high','low','close']: df[k] = pd.to_numeric(df[k])
    return df.iloc[:-1]

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
