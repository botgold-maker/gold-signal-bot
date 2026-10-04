"""Research-only next-bar OHLC backtest. Usage: python backtest.py candles.csv"""
import sys
import pandas as pd
from main import indicators

def run(frame, minimum_score=90, cost=0.50, max_hold=16):
    required = ['open', 'high', 'low', 'close']
    if len(frame) < 100 or any(c not in frame for c in required):
        raise ValueError('Need 100+ OHLC candles')
    d = frame.copy()
    for c in required:
        d[c] = pd.to_numeric(d[c], errors='raise')
    if d[required].isna().any().any():
        raise ValueError('Missing candles')
    d = indicators(d)
    trades = []
    i = 60
    while i < len(d)-max_hold-1:
        b, prev = d.iloc[i], d.iloc[i-1]
        if pd.isna(b.rsi) or pd.isna(b.atr) or b.atr <= 0:
            i += 1
            continue
        buy = b.ema20 > b.ema50 and b.close > b.ema20 and b.close > prev.close and 52 <= b.rsi <= 68
        sell = b.ema20 < b.ema50 and b.close < b.ema20 and b.close < prev.close and 32 <= b.rsi <= 48
        if not (buy or sell):
            i += 1
            continue
        side = 1 if buy else -1
        score = 60 + min(15, 15*abs(b.ema20-b.ema50)/b.atr) + min(15, 15*abs(b.close-prev.close)/b.atr) + min(10, abs(b.rsi-50))
        if score < minimum_score:
            i += 1
            continue
        entry = d.iloc[i+1]['open'] + side*cost
        stop = entry-side*1.5*b.atr
        target = entry+side*2.25*b.atr
        end = i+max_hold
        exit_price = None
        for j in range(i+1, end+1):
            bar = d.iloc[j]
            if (bar.low <= stop if buy else bar.high >= stop):
                exit_price, end = stop, j
                break
            if (bar.high >= target if buy else bar.low <= target):
                exit_price, end = target, j
                break
        if exit_price is None:
            exit_price = d.iloc[end]['close']-side*cost
        trades.append(side*(exit_price-entry)/(1.5*b.atr))
        i = end+1
    if not trades:
        return {'trades': 0}
    equity = pd.Series(trades).cumsum()
    return {'trades': len(trades), 'total_R': round(float(sum(trades)), 2),
            'win_rate_pct': round(100*sum(x>0 for x in trades)/len(trades), 1),
            'max_drawdown_R': round(float((equity.cummax().clip(lower=0)-equity).max()), 2)}

if __name__ == '__main__':
    print(run(pd.read_csv(sys.argv[1]), int(sys.argv[2]) if len(sys.argv)>2 else 90))
