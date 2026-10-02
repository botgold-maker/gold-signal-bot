# Gold signal bot (paper-only)
XAU/USD educational signal prototype. No broker orders are placed or closed. RiskManager is a prototype; no live P&L feed or persistent state exists.
Defaults: $50 simulated balance; 0.5% planned risk per trade; 2% daily realized loss limit; suspend after two consecutive losses. No guarantee of accuracy or protection against real trading losses.
Set TWELVEDATA_API_KEY in Railway Variables. Start command: python main.py.
Tests: python -m unittest test_risk.py
