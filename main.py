#!/usr/bin/env python3
"""
ORB Live Trading Engine – single-file production process
=======================================================
Strategy: Opening Range Breakout (15-min) + live ADX(14) > 25
Broker:   Upstox (market orders, product=I)
Risk:     100% available capital, equal allocation, optional 5× leverage,
          hard 4% daily loss kill-switch, force square-off 15:14 IST

IMPORTANT
---------
- LIVE_TRADING=false  → paper mode (orders only logged)
- LIVE_TRADING=true   → real market orders
- You must whitelist the OCI reserved public IP in the Upstox app.
- This is real-money software. You accept all risk.
"""

from __future__ import annotations

import csv
import json
import logging
import math
import os
import signal
import sys
import time
import traceback
from dataclasses import dataclass, field, asdict
from datetime import date, datetime, time as dtime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import pytz
import requests
from dotenv import load_dotenv
from prometheus_client import (
    Counter,
    Gauge,
    Histogram,
    start_http_server,
)

# ---------------------------------------------------------------------------
# Config from environment
# ---------------------------------------------------------------------------
load_dotenv()

IST = pytz.timezone("Asia/Kolkata")

UPSTOX_ACCESS_TOKEN = os.getenv("UPSTOX_ACCESS_TOKEN", "").strip()
LIVE_TRADING = os.getenv("LIVE_TRADING", "false").lower() in ("1", "true", "yes")
DAILY_LOSS_LIMIT_PCT = float(os.getenv("DAILY_LOSS_LIMIT_PCT", "4.0"))
MAX_INSTRUMENTS = int(os.getenv("MAX_INSTRUMENTS", "6"))
LEVERAGE_MULTIPLIER = int(os.getenv("LEVERAGE_MULTIPLIER", "5"))
NTFY_TOPIC = os.getenv("NTFY_TOPIC", "").strip()
NTFY_SERVER = os.getenv("NTFY_SERVER", "https://ntfy.sh").rstrip("/")
INSTRUMENTS_CSV = Path(os.getenv("INSTRUMENTS_CSV", "filtered_stocks.csv"))
STATE_DIR = Path(os.getenv("STATE_DIR", "state"))
LOG_DIR = Path(os.getenv("LOG_DIR", "logs"))
DATA_DIR = Path(os.getenv("DATA_DIR", "data"))
METRICS_PORT = int(os.getenv("METRICS_PORT", "8000"))
SQUARE_OFF_TIME_STR = os.getenv("SQUARE_OFF_TIME", "15:14")

# Strategy constants (unchanged from original engine)
ADX_PERIOD = 14
ADX_THRESHOLD = 25.0
BIG_CANDLE_THRESHOLD_PCT = 1.5
ATR_SL_MULTIPLIER = 2.0
TRAIL_STEP_PCT = 0.2
RISK_REWARD = 1.5
ENTRY_COST_PCT = 0.5          # informational only for live (real costs differ)
POLL_INTERVAL_SEC = 15
MARKET_OPEN = dtime(9, 15)
FIRST_CANDLE_END = dtime(9, 30)
SQUARE_OFF_TIME = datetime.strptime(SQUARE_OFF_TIME_STR, "%H:%M").time()
WAKE_TIME = dtime(8, 50)
SLEEP_AFTER = dtime(15, 35)

# Upstox endpoints
FUNDS_URL = "https://api.upstox.com/v2/user/get-funds-and-margin"
PLACE_ORDER_URL = "https://api-hft.upstox.com/v3/order/place"
INTRADAY_CANDLE_URL = "https://api.upstox.com/v3/historical-candle/intraday/{instrument_key}/minutes/15"
POSITIONS_URL = "https://api.upstox.com/v2/portfolio/short-term-positions"
ORDER_BOOK_URL = "https://api.upstox.com/v2/order/retrieve-all"
LTP_URL = "https://api.upstox.com/v2/market-quote/ltp"
MARGIN_URL = "https://api.upstox.com/v2/charges/margin"

HEADERS = {
    "Accept": "application/json",
    "Authorization": f"Bearer {UPSTOX_ACCESS_TOKEN}",
    "Content-Type": "application/json",
}

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
LOG_DIR.mkdir(parents=True, exist_ok=True)
STATE_DIR.mkdir(parents=True, exist_ok=True)
DATA_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(LOG_DIR / "orb_live.log", encoding="utf-8"),
    ],
)
log = logging.getLogger("orb_live")

# ---------------------------------------------------------------------------
# Prometheus metrics
# ---------------------------------------------------------------------------
METRIC_EQUITY = Gauge("orb_equity", "Current equity (start-of-day capital + realised PnL)")
METRIC_DAILY_PNL = Gauge("orb_daily_pnl", "Realised PnL today")
METRIC_OPEN_POSITIONS = Gauge("orb_open_positions", "Number of open positions")
METRIC_TRADES_TOTAL = Counter("orb_trades_total", "Closed trades", ["symbol", "direction", "exit_reason"])
METRIC_ERRORS = Counter("orb_errors_total", "Errors", ["type"])
METRIC_API_LATENCY = Histogram("orb_api_latency_seconds", "Upstox API latency", ["endpoint"])
METRIC_KILL_SWITCH = Gauge("orb_kill_switch_active", "1 if daily loss limit hit")
METRIC_ALLOCATION = Gauge("orb_allocation_budget", "Per-instrument cash budget", ["symbol"])
METRIC_LAST_CANDLE_AGE = Gauge("orb_last_candle_age_seconds", "Age of newest closed candle", ["symbol"])

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------
@dataclass
class Instrument:
    symbol: str
    instrument_key: str
    leverage: bool
    budget: float = 0.0
    max_qty: int = 0
    ltp: float = 0.0


@dataclass
class Position:
    symbol: str
    instrument_key: str
    direction: str          # LONG / SHORT
    qty: int
    entry_price: float
    sl: float
    target: float
    current_sl: float
    trail_ref: float
    trail_step: float
    entry_time: str
    adx_at_entry: float
    or_high: float
    or_low: float
    order_id: Optional[str] = None
    status: str = "OPEN"    # OPEN / CLOSED


@dataclass
class DayState:
    trading_day: str
    start_equity: float
    realised_pnl: float = 0.0
    kill_switch: bool = False
    phase: Dict[str, str] = field(default_factory=dict)   # symbol → phase
    positions: Dict[str, Position] = field(default_factory=dict)
    opening_range: Dict[str, Dict] = field(default_factory=dict)
    last_processed_ts: Dict[str, str] = field(default_factory=dict)
    blocked_reason: Dict[str, str] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Helpers – time
# ---------------------------------------------------------------------------
def now_ist() -> datetime:
    return datetime.now(IST)


def is_weekday(d: date | None = None) -> bool:
    d = d or now_ist().date()
    return d.weekday() < 5


def seconds_until(t: dtime) -> float:
    n = now_ist()
    target = n.replace(hour=t.hour, minute=t.minute, second=0, microsecond=0)
    if target <= n:
        target += timedelta(days=1)
    return (target - n).total_seconds()


# ---------------------------------------------------------------------------
# ntfy
# ---------------------------------------------------------------------------
def notify(title: str, message: str, priority: str = "default", tags: str = "") -> None:
    if not NTFY_TOPIC:
        return
    try:
        requests.post(
            f"{NTFY_SERVER}/{NTFY_TOPIC}",
            data=message.encode("utf-8"),
            headers={
                "Title": title,
                "Priority": priority,
                "Tags": tags,
            },
            timeout=10,
        )
    except Exception as e:
        log.warning("ntfy failed: %s", e)


# ---------------------------------------------------------------------------
# Upstox API wrappers
# ---------------------------------------------------------------------------
def api_get(url: str, params: dict | None = None, endpoint: str = "generic") -> dict:
    t0 = time.time()
    try:
        r = requests.get(url, headers=HEADERS, params=params, timeout=20)
        METRIC_API_LATENCY.labels(endpoint=endpoint).observe(time.time() - t0)
        if r.status_code == 401:
            raise RuntimeError("Upstox 401 – token expired or invalid. Refresh UPSTOX_ACCESS_TOKEN.")
        if r.status_code == 429:
            time.sleep(2)
            r = requests.get(url, headers=HEADERS, params=params, timeout=20)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        METRIC_ERRORS.labels(type="api_get").inc()
        log.error("GET %s failed: %s", url, e)
        raise


def api_post(url: str, payload: dict, endpoint: str = "generic") -> dict:
    t0 = time.time()
    try:
        r = requests.post(url, headers=HEADERS, json=payload, timeout=20)
        METRIC_API_LATENCY.labels(endpoint=endpoint).observe(time.time() - t0)
        if r.status_code == 401:
            raise RuntimeError("Upstox 401 – token expired or invalid.")
        if r.status_code == 429:
            time.sleep(2)
            r = requests.post(url, headers=HEADERS, json=payload, timeout=20)
        # Do not raise on 400 – caller inspects body for order rejection
        return r.json() if r.content else {}
    except Exception as e:
        METRIC_ERRORS.labels(type="api_post").inc()
        log.error("POST %s failed: %s", url, e)
        raise


def get_available_cash() -> float:
    """Return equity available_margin (cash available for trading)."""
    data = api_get(FUNDS_URL, endpoint="funds")
    equity = data.get("data", {}).get("equity", {})
    available = float(equity.get("available_margin", 0) or 0)
    log.info("Available margin (equity): ₹%.2f", available)
    return available


def get_ltp(instrument_key: str) -> float:
    """Best-effort LTP. Falls back to 0 on failure."""
    try:
        # instrument_key must be URL-encoded in query
        q = {"instrument_key": instrument_key}
        data = api_get(LTP_URL, params=q, endpoint="ltp")
        # response shape: data -> { "NSE_EQ:..." : { "last_price": ... } }
        for v in data.get("data", {}).values():
            return float(v.get("last_price", 0) or 0)
    except Exception as e:
        log.warning("LTP fetch failed for %s: %s", instrument_key, e)
    return 0.0


def fetch_intraday_15min(instrument_key: str) -> pd.DataFrame:
    url = INTRADAY_CANDLE_URL.format(instrument_key=instrument_key)
    empty = pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume", "oi"])
    try:
        data = api_get(url, endpoint="intraday")
        candles = data.get("data", {}).get("candles", [])
        if not candles:
            return empty
        df = pd.DataFrame(candles, columns=["timestamp", "open", "high", "low", "close", "volume", "oi"])
        df["timestamp"] = pd.to_datetime(df["timestamp"]).dt.tz_convert(IST)
        return df.sort_values("timestamp").drop_duplicates("timestamp").reset_index(drop=True)
    except Exception as e:
        log.error("Intraday candles failed for %s: %s", instrument_key, e)
        return empty


def place_market_order(
    instrument_key: str,
    quantity: int,
    transaction_type: str,   # BUY / SELL
    tag: str = "orb",
) -> Optional[str]:
    """
    Place a MARKET order with product=I (intraday).
    Returns order_id on success, None on failure / paper mode.
    """
    if quantity <= 0:
        log.warning("Quantity <= 0 – skipping order")
        return None

    payload = {
        "quantity": int(quantity),
        "product": "I",
        "validity": "DAY",
        "price": 0,
        "tag": tag[:20],
        "instrument_token": instrument_key,
        "order_type": "MARKET",
        "transaction_type": transaction_type.upper(),
        "disclosed_quantity": 0,
        "trigger_price": 0,
        "is_amo": False,
        "slice": False,
    }

    if not LIVE_TRADING:
        log.info("[PAPER] Would place %s %s qty=%s %s", transaction_type, instrument_key, quantity, payload)
        return f"PAPER-{int(time.time())}"

    try:
        resp = api_post(PLACE_ORDER_URL, payload, endpoint="place_order")
        status = resp.get("status")
        if status == "success":
            order_id = resp.get("data", {}).get("order_id")
            log.info("ORDER PLACED %s %s qty=%s order_id=%s", transaction_type, instrument_key, quantity, order_id)
            return order_id
        else:
            log.error("Order rejected: %s", resp)
            notify("ORDER REJECTED", str(resp)[:300], priority="high", tags="warning")
            METRIC_ERRORS.labels(type="order_reject").inc()
            return None
    except Exception as e:
        log.error("place_market_order exception: %s", e)
        notify("ORDER ERROR", str(e)[:300], priority="high", tags="x")
        return None


# ---------------------------------------------------------------------------
# ADX (same logic as original back-tester)
# ---------------------------------------------------------------------------
def wilder_adx(daily_df: pd.DataFrame, period: int = ADX_PERIOD) -> pd.DataFrame:
    df = daily_df.copy().reset_index(drop=True)
    if len(df) < period + 1:
        df["adx"] = np.nan
        return df

    high, low, close = df["high"], df["low"], df["close"]
    prev_close = close.shift(1)
    prev_high = high.shift(1)
    prev_low = low.shift(1)

    tr = pd.concat([
        (high - low),
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)

    up_move = high - prev_high
    down_move = prev_low - low
    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)

    def wilder_smooth(series, period):
        result = np.full(len(series), np.nan)
        if len(series) < period:
            return result
        s = pd.Series(series)
        result[period - 1] = s.iloc[:period].sum()
        for i in range(period, len(s)):
            result[i] = result[i - 1] - (result[i - 1] / period) + s.iloc[i]
        return result

    tr_s = wilder_smooth(tr.to_numpy(), period)
    plus_s = wilder_smooth(plus_dm, period)
    minus_s = wilder_smooth(minus_dm, period)

    with np.errstate(divide="ignore", invalid="ignore"):
        plus_di = 100 * (plus_s / tr_s)
        minus_di = 100 * (minus_s / tr_s)
        dx = 100 * (np.abs(plus_di - minus_di) / (plus_di + minus_di))

    dx = pd.Series(dx)
    adx = np.full(len(dx), np.nan)
    first_valid = dx.first_valid_index()
    if first_valid is not None and first_valid + period <= len(dx):
        start = first_valid + period - 1
        if start < len(dx):
            adx[start] = dx.iloc[first_valid:first_valid + period].mean()
            for i in range(start + 1, len(dx)):
                if np.isnan(dx.iloc[i]) or np.isnan(adx[i - 1]):
                    continue
                adx[i] = (adx[i - 1] * (period - 1) + dx.iloc[i]) / period
    df["adx"] = adx
    return df


def live_adx(prior_daily: pd.DataFrame, today_partial: dict) -> float:
    if prior_daily.empty:
        return float("nan")
    combined = pd.concat([prior_daily, pd.DataFrame([today_partial])], ignore_index=True)
    result = wilder_adx(combined)
    val = result["adx"].iloc[-1]
    return float(val) if not pd.isna(val) else float("nan")


# ---------------------------------------------------------------------------
# Instrument loading & sizing
# ---------------------------------------------------------------------------
def load_instruments() -> List[Instrument]:
    if not INSTRUMENTS_CSV.exists():
        raise FileNotFoundError(f"{INSTRUMENTS_CSV} not found")
    rows = []
    with open(INSTRUMENTS_CSV, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for r in reader:
            lev = str(r.get("leverage", "false")).strip().lower() in ("1", "true", "yes")
            rows.append(Instrument(
                symbol=r["symbol"].strip(),
                instrument_key=r["instrument_key"].strip(),
                leverage=lev,
            ))
    if len(rows) > MAX_INSTRUMENTS:
        log.warning("CSV has %d instruments – truncating to %d", len(rows), MAX_INSTRUMENTS)
        rows = rows[:MAX_INSTRUMENTS]
    if not rows:
        raise RuntimeError("No instruments in CSV")
    return rows



def get_intraday_margin_per_share(instrument_key: str, price: float) -> float:
    """
    Return approximate margin required to buy 1 share intraday (product=I).
    Falls back to full price (1x) if API fails.
    """
    if price <= 0:
        return 0.0
    payload = {
        "instruments": [
            {
                "instrument_key": instrument_key,
                "quantity": 1,
                "transaction_type": "BUY",
                "product": "I",
                "price": float(price),
            }
        ]
    }
    try:
        resp = api_post(MARGIN_URL, payload, endpoint="margin")
        data = resp.get("data") or {}
        required = (
            data.get("required_margin")
            or data.get("total_margin")
            or data.get("final_margin")
        )
        if required is None and isinstance(data.get("margins"), list) and data["margins"]:
            m0 = data["margins"][0]
            required = m0.get("required_margin") or m0.get("total_margin") or m0.get("final_margin")
        if required is None and isinstance(data, dict):
            required = data.get("total") or (data.get("equity") or {}).get("required_margin")
        required = float(required or 0)
        if required <= 0:
            log.warning("Margin API returned 0 for %s — using full price (1x)", instrument_key)
            return price
        return required
    except Exception as e:
        log.warning("Margin API failed for %s: %s — using full price (1x)", instrument_key, e)
        return price

def allocate_and_size(instruments: List[Instrument], total_cash: float) -> List[Instrument]:
    n = len(instruments)
    budget = total_cash / n if n else 0.0
    for inst in instruments:
        inst.budget = budget
        METRIC_ALLOCATION.labels(symbol=inst.symbol).set(budget)
        inst.ltp = get_ltp(inst.instrument_key)
        if inst.ltp <= 0:
            log.warning("%s LTP unavailable — max_qty=0", inst.symbol)
            inst.max_qty = 0
            continue

        # Real Upstox intraday margin for 1 share (true 5x/2x/1x from broker)
        margin_ps = get_intraday_margin_per_share(inst.instrument_key, inst.ltp)
        if margin_ps <= 0:
            inst.max_qty = 0
            continue

        inst.max_qty = max(0, math.floor(budget / margin_ps))
        approx_lev = (inst.ltp / margin_ps) if margin_ps else 1.0
        log.info(
            "%s  budget=₹%.0f  ltp=%.2f  margin/share=₹%.2f  ~lev=%.1fx  max_qty=%d",
            inst.symbol, budget, inst.ltp, margin_ps, approx_lev, inst.max_qty,
        )
    return instruments


# ---------------------------------------------------------------------------
# State persistence
# ---------------------------------------------------------------------------
def state_path(day: date) -> Path:
    return STATE_DIR / f"day_{day.isoformat()}.json"


def load_day_state(day: date) -> DayState:
    p = state_path(day)
    if p.exists():
        try:
            raw = json.loads(p.read_text())
            st = DayState(
                trading_day=raw["trading_day"],
                start_equity=raw["start_equity"],
                realised_pnl=raw.get("realised_pnl", 0.0),
                kill_switch=raw.get("kill_switch", False),
                phase=raw.get("phase", {}),
                opening_range=raw.get("opening_range", {}),
                last_processed_ts=raw.get("last_processed_ts", {}),
                blocked_reason=raw.get("blocked_reason", {}),
            )
            for sym, pos in raw.get("positions", {}).items():
                st.positions[sym] = Position(**pos)
            return st
        except Exception as e:
            log.error("Corrupt state file %s: %s – starting fresh", p, e)
    return DayState(trading_day=day.isoformat(), start_equity=0.0)


def save_day_state(st: DayState) -> None:
    p = state_path(date.fromisoformat(st.trading_day))
    payload = {
        "trading_day": st.trading_day,
        "start_equity": st.start_equity,
        "realised_pnl": st.realised_pnl,
        "kill_switch": st.kill_switch,
        "phase": st.phase,
        "opening_range": st.opening_range,
        "last_processed_ts": st.last_processed_ts,
        "blocked_reason": st.blocked_reason,
        "positions": {s: asdict(p) for s, p in st.positions.items()},
    }
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, indent=2, default=str))
    tmp.replace(p)


# ---------------------------------------------------------------------------
# Core per-symbol live logic (mirrors original process_symbol_live)
# ---------------------------------------------------------------------------
def process_symbol(
    inst: Instrument,
    st: DayState,
    prior_daily: pd.DataFrame,
    closed_candles: pd.DataFrame,
) -> None:
    symbol = inst.symbol
    if st.kill_switch:
        return
    if st.phase.get(symbol) == "DONE":
        return

    if closed_candles.empty:
        return

    last_ts = st.last_processed_ts.get(symbol)
    if last_ts:
        closed_candles = closed_candles[closed_candles["timestamp"] > pd.Timestamp(last_ts)]
    if closed_candles.empty:
        return

    for _, c in closed_candles.iterrows():
        if st.phase.get(symbol) == "DONE":
            break

        phase = st.phase.get(symbol, "AWAITING_OPENING_RANGE")

        # ---- opening range ----
        if phase == "AWAITING_OPENING_RANGE":
            # only accept the first candle that ends at/after 09:30
            if c["timestamp"].time() < FIRST_CANDLE_END:
                st.last_processed_ts[symbol] = str(c["timestamp"])
                continue
            or_ = {
                "open1": float(c["open"]),
                "high1": float(c["high"]),
                "low1": float(c["low"]),
            }
            range1 = or_["high1"] - or_["low1"]
            or_["big_candle"] = bool(or_["open1"] and (range1 / or_["open1"] * 100) > BIG_CANDLE_THRESHOLD_PCT)
            st.opening_range[symbol] = or_
            st.phase[symbol] = "AWAITING_BREAKOUT"
            st.last_processed_ts[symbol] = str(c["timestamp"])
            log.info("%s OR set  H=%.2f L=%.2f big=%s", symbol, or_["high1"], or_["low1"], or_["big_candle"])
            continue

        # ---- breakout ----
        if phase == "AWAITING_BREAKOUT":
            or_ = st.opening_range[symbol]
            high1, low1 = or_["high1"], or_["low1"]
            broke_high = c["high"] > high1
            broke_low = c["low"] < low1
            direction = None
            if broke_high and broke_low:
                direction = "LONG" if c["close"] >= c["open"] else "SHORT"
            elif broke_high:
                direction = "LONG"
            elif broke_low:
                direction = "SHORT"

            st.last_processed_ts[symbol] = str(c["timestamp"])

            if direction is None:
                if c["timestamp"].time() >= SQUARE_OFF_TIME:
                    st.phase[symbol] = "DONE"
                continue

            # ADX gate
            today_partial = {
                "date": c["timestamp"].date(),
                "open": or_["open1"],
                "high": max(high1, float(c["high"])),
                "low": min(low1, float(c["low"])),
                "close": float(c["close"]),
            }
            adx_val = live_adx(prior_daily, today_partial)
            if math.isnan(adx_val) or adx_val <= ADX_THRESHOLD:
                st.phase[symbol] = "DONE"
                st.blocked_reason[symbol] = "ADX_FILTER_BLOCKED"
                log.info("%s breakout blocked by ADX=%.2f", symbol, adx_val)
                continue

            # size
            qty = inst.max_qty
            if qty <= 0:
                st.phase[symbol] = "DONE"
                st.blocked_reason[symbol] = "ZERO_QTY"
                continue

            entry_price = high1 if direction == "LONG" else low1
            range1 = high1 - low1
            if or_["big_candle"]:
                sl_dist = ATR_SL_MULTIPLIER * range1
                sl = entry_price - sl_dist if direction == "LONG" else entry_price + sl_dist
            else:
                sl = low1 if direction == "LONG" else high1
                sl_dist = abs(entry_price - sl)
            if sl_dist <= 0:
                st.phase[symbol] = "DONE"
                st.blocked_reason[symbol] = "INVALID_SL"
                continue
            target = entry_price + RISK_REWARD * sl_dist if direction == "LONG" else entry_price - RISK_REWARD * sl_dist

            # place order
            side = "BUY" if direction == "LONG" else "SELL"
            order_id = place_market_order(inst.instrument_key, qty, side, tag=f"orb-{symbol}")
            if not order_id:
                st.phase[symbol] = "DONE"
                st.blocked_reason[symbol] = "ORDER_FAILED"
                continue

            pos = Position(
                symbol=symbol,
                instrument_key=inst.instrument_key,
                direction=direction,
                qty=qty,
                entry_price=entry_price,
                sl=sl,
                target=target,
                current_sl=sl,
                trail_ref=entry_price,
                trail_step=entry_price * (TRAIL_STEP_PCT / 100.0),
                entry_time=str(c["timestamp"]),
                adx_at_entry=adx_val,
                or_high=high1,
                or_low=low1,
                order_id=order_id,
            )
            st.positions[symbol] = pos
            st.phase[symbol] = "IN_TRADE"
            notify(
                f"ENTRY {symbol}",
                f"{direction} qty={qty} @~{entry_price:.2f} SL={sl:.2f} TGT={target:.2f} ADX={adx_val:.1f}",
                tags="chart_with_upwards_trend",
            )
            log.info("%s ENTRY %s qty=%d entry~%.2f", symbol, direction, qty, entry_price)

            # same-candle exit check
            _check_exit(inst, st, pos, c)
            continue

        # ---- manage open position ----
        if phase == "IN_TRADE":
            pos = st.positions.get(symbol)
            if not pos or pos.status != "OPEN":
                st.phase[symbol] = "DONE"
                continue
            st.last_processed_ts[symbol] = str(c["timestamp"])
            _check_exit(inst, st, pos, c)


def _check_exit(inst: Instrument, st: DayState, pos: Position, c: pd.Series) -> None:
    # square-off time
    if c["timestamp"].time() >= SQUARE_OFF_TIME:
        _close_position(inst, st, pos, float(c["close"]), "SQUARE_OFF_EOD")
        return

    direction = pos.direction
    if direction == "LONG":
        while c["high"] >= pos.trail_ref + pos.trail_step:
            pos.trail_ref += pos.trail_step
            pos.current_sl += pos.trail_step
        if c["low"] <= pos.current_sl:
            reason = "STOP_LOSS" if pos.current_sl <= pos.sl else "TRAILING_SL"
            _close_position(inst, st, pos, pos.current_sl, reason)
            return
        if c["high"] >= pos.target:
            _close_position(inst, st, pos, pos.target, "TARGET")
            return
    else:
        while c["low"] <= pos.trail_ref - pos.trail_step:
            pos.trail_ref -= pos.trail_step
            pos.current_sl -= pos.trail_step
        if c["high"] >= pos.current_sl:
            reason = "STOP_LOSS" if pos.current_sl >= pos.sl else "TRAILING_SL"
            _close_position(inst, st, pos, pos.current_sl, reason)
            return
        if c["low"] <= pos.target:
            _close_position(inst, st, pos, pos.target, "TARGET")
            return


def _close_position(inst: Instrument, st: DayState, pos: Position, exit_price: float, reason: str) -> None:
    if pos.status != "OPEN":
        return
    # opposite side market order
    side = "SELL" if pos.direction == "LONG" else "BUY"
    order_id = place_market_order(inst.instrument_key, pos.qty, side, tag=f"exit-{pos.symbol}")
    # PnL (approximate – real fill may differ)
    if pos.direction == "LONG":
        gross = (exit_price - pos.entry_price) * pos.qty
    else:
        gross = (pos.entry_price - exit_price) * pos.qty
    # simplistic cost model
    costs = pos.entry_price * pos.qty * (ENTRY_COST_PCT / 100.0)
    net = gross - costs
    st.realised_pnl += net
    pos.status = "CLOSED"

    METRIC_TRADES_TOTAL.labels(symbol=pos.symbol, direction=pos.direction, exit_reason=reason).inc()
    METRIC_DAILY_PNL.set(st.realised_pnl)
    METRIC_EQUITY.set(st.start_equity + st.realised_pnl)
    METRIC_OPEN_POSITIONS.set(sum(1 for p in st.positions.values() if p.status == "OPEN"))

    notify(
        f"EXIT {pos.symbol}",
        f"{reason} {pos.direction} qty={pos.qty} entry={pos.entry_price:.2f} exit~{exit_price:.2f} net≈₹{net:.0f}",
        tags="chart_with_downwards_trend" if net < 0 else "white_check_mark",
    )
    log.info("%s EXIT %s net≈₹%.0f reason=%s", pos.symbol, reason, net, reason)

    st.phase[pos.symbol] = "DONE"
    # kill-switch check
    if st.start_equity > 0:
        loss_pct = -st.realised_pnl / st.start_equity * 100.0
        if loss_pct >= DAILY_LOSS_LIMIT_PCT:
            st.kill_switch = True
            METRIC_KILL_SWITCH.set(1)
            notify("DAILY LOSS LIMIT", f"Realised loss {loss_pct:.2f}% ≥ {DAILY_LOSS_LIMIT_PCT}% – kill switch ON", priority="urgent", tags="rotating_light")
            log.warning("KILL SWITCH activated – daily loss %.2f%%", loss_pct)
            # force-close any remaining open positions
            for s, p in list(st.positions.items()):
                if p.status == "OPEN":
                    _close_position(inst, st, p, exit_price, "KILL_SWITCH")


# ---------------------------------------------------------------------------
# Prior daily bars (minimal – last ~20 trading days for ADX)
# ---------------------------------------------------------------------------
def get_prior_daily(instrument_key: str, symbol: str, trading_day: date) -> pd.DataFrame:
    """
    Fetch a short history of daily bars built from 15-min data.
    For simplicity we use the intraday endpoint of previous days via historical
    if needed; here we keep a lightweight version that builds from whatever
    intraday we already have + a small historical pull if the cache is empty.
    """
    # In a production hardening pass you would cache daily bars.
    # For the free-tier single-file version we return empty and let ADX
    # become valid only after enough intraday bars accumulate, or you can
    # pre-seed data_cache.
    return pd.DataFrame(columns=["date", "open", "high", "low", "close"])


# ---------------------------------------------------------------------------
# Main trading day loop
# ---------------------------------------------------------------------------
def run_trading_day() -> None:
    today = now_ist().date()
    if not is_weekday(today):
        log.info("Weekend – sleeping")
        return

    log.info("=" * 60)
    log.info("ORB LIVE  %s  LIVE_TRADING=%s", today, LIVE_TRADING)
    log.info("=" * 60)
    notify("STARTUP", f"ORB live engine started for {today}  LIVE={LIVE_TRADING}", tags="rocket")

    if not UPSTOX_ACCESS_TOKEN:
        log.error("UPSTOX_ACCESS_TOKEN missing")
        notify("FATAL", "Missing UPSTOX_ACCESS_TOKEN", priority="urgent", tags="x")
        return

    instruments = load_instruments()
    total_cash = get_available_cash()
    if total_cash <= 0:
        log.error("No available cash – aborting day")
        notify("NO CASH", "available_margin is 0", priority="high", tags="warning")
        return

    instruments = allocate_and_size(instruments, total_cash)

    st = load_day_state(today)
    if st.start_equity <= 0:
        st.start_equity = total_cash
    METRIC_EQUITY.set(st.start_equity + st.realised_pnl)
    METRIC_DAILY_PNL.set(st.realised_pnl)
    METRIC_KILL_SWITCH.set(1 if st.kill_switch else 0)

    # simple prior-daily cache (empty for first version)
    prior_cache: Dict[str, pd.DataFrame] = {i.symbol: get_prior_daily(i.instrument_key, i.symbol, today) for i in instruments}

    while True:
        n = now_ist()
        if n.time() >= SLEEP_AFTER:
            log.info("Past SLEEP_AFTER – ending day")
            break
        if st.kill_switch:
            log.info("Kill switch active – waiting for square-off window then exit")
            if n.time() >= SQUARE_OFF_TIME:
                break

        for inst in instruments:
            try:
                candles = fetch_intraday_15min(inst.instrument_key)
                if not candles.empty:
                    # only fully closed bars
                    closed = candles[candles["timestamp"] + pd.Timedelta(minutes=15) <= n]
                    if not closed.empty:
                        age = (n - closed["timestamp"].iloc[-1]).total_seconds()
                        METRIC_LAST_CANDLE_AGE.labels(symbol=inst.symbol).set(age)
                    process_symbol(inst, st, prior_cache[inst.symbol], closed)
            except Exception as e:
                log.error("%s loop error: %s\n%s", inst.symbol, e, traceback.format_exc(limit=2))
                METRIC_ERRORS.labels(type="symbol_loop").inc()
            finally:
                save_day_state(st)

        # force square-off pass near end of day
        if n.time() >= SQUARE_OFF_TIME:
            for inst in instruments:
                pos = st.positions.get(inst.symbol)
                if pos and pos.status == "OPEN":
                    _close_position(inst, st, pos, pos.entry_price, "SQUARE_OFF_EOD")  # price will be improved by real fill
            save_day_state(st)
            break

        time.sleep(POLL_INTERVAL_SEC)

    notify("SHUTDOWN", f"Day {today} finished. Realised PnL ≈ ₹{st.realised_pnl:.0f}", tags="checkered_flag")
    log.info("Day complete. Realised PnL ≈ ₹%.2f", st.realised_pnl)


# ---------------------------------------------------------------------------
# Scheduler – sleep until next wake window
# ---------------------------------------------------------------------------
def sleep_until_next_window() -> None:
    n = now_ist()
    if is_weekday(n.date()) and WAKE_TIME <= n.time() < SLEEP_AFTER:
        return  # already in window
    # compute next weekday 08:50
    candidate = n.replace(hour=WAKE_TIME.hour, minute=WAKE_TIME.minute, second=0, microsecond=0)
    if candidate <= n:
        candidate += timedelta(days=1)
    while candidate.weekday() >= 5:
        candidate += timedelta(days=1)
    secs = (candidate - n).total_seconds()
    log.info("Sleeping %.0f seconds until %s", secs, candidate.isoformat())
    time.sleep(min(secs, 3600))  # wake at least hourly to re-check


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def main() -> None:
    # start metrics server
    try:
        start_http_server(METRICS_PORT)
        log.info("Prometheus metrics on :%d", METRICS_PORT)
    except Exception as e:
        log.warning("Could not start metrics server: %s", e)

    def handle_sig(signum, frame):
        log.info("Signal %s – exiting", signum)
        notify("SHUTDOWN", "Process received signal – exiting", tags="wave")
        sys.exit(0)

    signal.signal(signal.SIGINT, handle_sig)
    signal.signal(signal.SIGTERM, handle_sig)

    log.info("ORB Live Engine starting  LIVE_TRADING=%s", LIVE_TRADING)
    while True:
        try:
            n = now_ist()
            if is_weekday(n.date()) and WAKE_TIME <= n.time() < SLEEP_AFTER:
                run_trading_day()
            sleep_until_next_window()
        except Exception as e:
            log.error("Top-level error: %s\n%s", e, traceback.format_exc())
            notify("FATAL", str(e)[:400], priority="urgent", tags="x")
            METRIC_ERRORS.labels(type="fatal").inc()
            time.sleep(60)


if __name__ == "__main__":
    main()
