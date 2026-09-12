"""
example_strategy.py
--------------------
A placeholder strategy (SMA crossover) showing the expected shape.
Replace this file's logic with your ported backtested strategy - keep the
class name `Strategy` and the on_bar(...) signature so run.py finds it.
"""
import pandas as pd
from app.strategy_adapter import StrategyAdapter, Signal


class Strategy(StrategyAdapter):
    fast_window = 9
    slow_window = 21
    qty = 1
    exchange_segment = "NSE_EQ"

    def on_bar(self, candles: pd.DataFrame):
        if len(candles) < self.slow_window + 1:
            return []

        candles = candles.copy()
        candles["fast_ma"] = candles["close"].rolling(self.fast_window).mean()
        candles["slow_ma"] = candles["close"].rolling(self.slow_window).mean()

        prev = candles.iloc[-2]
        last = candles.iloc[-1]

        crossed_up = prev["fast_ma"] <= prev["slow_ma"] and last["fast_ma"] > last["slow_ma"]
        crossed_down = prev["fast_ma"] >= prev["slow_ma"] and last["fast_ma"] < last["slow_ma"]

        security_id = self.instruments[0]

        if crossed_up:
            return [Signal(side="BUY", quantity=self.qty, security_id=security_id,
                            exchange_segment=self.exchange_segment)]
        if crossed_down:
            return [Signal(side="SELL", quantity=self.qty, security_id=security_id,
                            exchange_segment=self.exchange_segment)]
        return []
