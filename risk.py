"""Paper-trading risk policy. Not broker-side protection."""
import os
from datetime import datetime, timezone
STARTING_BALANCE=float(os.getenv("STARTING_BALANCE","50"))
RISK_FRACTION=float(os.getenv("RISK_PER_TRADE_PCT","0.5"))/100
DAILY_LOSS_FRACTION=float(os.getenv("DAILY_LOSS_LIMIT_PCT","2"))/100
MAX_CONSECUTIVE_LOSSES=2
class RiskManager:
    def __init__(self,balance=STARTING_BALANCE):
        if balance<=0: raise ValueError("Balance must be positive")
        self.balance=balance;self.day=None;self.day_start_balance=balance
        self.realized_today=0.0;self.consecutive_losses=0;self.suspended=False
    def rollover(self,now=None):
        day=(now or datetime.now(timezone.utc)).date()
        if self.day!=day:
            self.day=day;self.day_start_balance=self.balance;self.realized_today=0.0
    def budget(self,now=None):
        self.rollover(now)
        if self.suspended or self.consecutive_losses>=MAX_CONSECUTIVE_LOSSES:
            self.suspended=True;return 0.0
        remaining=self.day_start_balance*DAILY_LOSS_FRACTION+self.realized_today
        if remaining<=0:
            self.suspended=True;return 0.0
        return max(0.0,min(self.balance*RISK_FRACTION,remaining))
    def proposed_lots(self,entry,stop,dollars_per_price_unit_per_lot,min_lot=0.01,step=0.01):
        risk=self.budget();distance=abs(entry-stop)
        if risk<=0 or distance<=0 or dollars_per_price_unit_per_lot<=0 or min_lot<=0 or step<=0:return None
        import math
        lots=round(math.floor((risk/(distance*dollars_per_price_unit_per_lot)+1e-12)/step)*step,8)
        return lots if lots>=min_lot and lots*distance*dollars_per_price_unit_per_lot<=risk+1e-9 else None
    def record_closed_pnl(self,pnl,now=None):
        self.rollover(now);self.balance+=pnl;self.realized_today+=pnl
        self.consecutive_losses=self.consecutive_losses+1 if pnl<0 else 0
        if self.balance<=0 or self.realized_today<=-self.day_start_balance*DAILY_LOSS_FRACTION or self.consecutive_losses>=MAX_CONSECUTIVE_LOSSES:self.suspended=True
        return self.suspended
