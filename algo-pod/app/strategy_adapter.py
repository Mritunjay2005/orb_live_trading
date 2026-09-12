"""
strategy_adapter.py
--------------------
The contract every strategy must implement so it can run unchanged in
backtest AND live. This is the ONLY interface algo-pod's run-loop talks to,
so porting a backtested strategy means writing a thin wrapper around your
existing signal logic - your core logic (indicators, entry/exit rules)
does not need to change.

Your class must implement:
    on_bar(self, candles: pd.DataFrame) -> list[Signal]

`candles` is a DataFrame of OHLCV rows (oldest -> newest) for the instrument
this pod is assigned, refreshed on each loop tick. Return zero or more
Signal objects for orders you want placed this tick.

If your original code is a backtrader Strategy (bt.Strategy) with a
next() method:
  1. Move your indicator setup from __init__ into on_bar's first call
     (compute indicators directly on the pandas DataFrame with pandas/
     numpy/ta-lib instead of bt.indicators.*), or keep a backtrader
     Cerebro running internally in "replay" mode fed by this DataFrame -
     see the commented BacktraderBridge below for that path.
  2. Move your next()'s buy()/sell() calls to `return [Signal(...)]`
     instead of calling self.buy()/self.sell() directly.
  3. Keep all your thresholds/params as class attributes so they're
     unchanged from your backtest.
"""
from dataclasses import dataclass
from typing import List
import pandas as pd


@dataclass
class Signal:
    side: str              # "BUY" or "SELL"
    quantity: int
    security_id: str
    exchange_segment: str  # e.g. "NSE_EQ", "NSE_FO"
    order_type: str = "MARKET"
    price: float = 0.0


class StrategyAdapter:
    """Base class every algo pod strategy inherits from."""

    def __init__(self, instruments: list[str]):
        self.instruments = instruments

    def on_bar(self, candles: pd.DataFrame) -> List[Signal]:
        raise NotImplementedError


# ---------------------------------------------------------------------------
# OPTIONAL: if you want to keep using backtrader's own indicator/strategy
# machinery unchanged (not just port the logic), you can drive a Cerebro
# instance in "live" mode with a custom data feed that you push new bars
# into on every tick, and read orders back out through a custom broker
# stub. This preserves 100% of your original backtrader code but adds
# more moving parts. Ask if you want this wired up once you share the
# actual strategy file - most single-indicator/crossover style strategies
# port faster as a plain on_bar() function instead.
# ---------------------------------------------------------------------------
