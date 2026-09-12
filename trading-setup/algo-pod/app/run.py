"""
run.py - live loop for one algo pod.

Each pod is completely independent: its own strategy module, its own
instrument set, its own process/container. Killing or redeploying one
pod never touches the others.
"""
import os
import time
import importlib
import httpx
import pandas as pd

POD_ID = os.getenv("POD_ID", "algo-pod")
STRATEGY_MODULE = os.getenv("STRATEGY_MODULE", "strategies.example_strategy")
INSTRUMENTS = os.getenv("INSTRUMENTS", "").split(",")
EXECUTION_GATE_URL = os.getenv("EXECUTION_GATE_URL", "http://execution-gate:8000")
QUEUE_SERVICE_URL = os.getenv("QUEUE_SERVICE_URL", "http://queue-service:8000")
POLL_SECONDS = int(os.getenv("POLL_SECONDS", "60"))


def load_strategy():
    mod = importlib.import_module(STRATEGY_MODULE)
    return mod.Strategy(instruments=INSTRUMENTS)


def fetch_candles(client: httpx.Client, instrument_key: str) -> pd.DataFrame:
    today = time.strftime("%Y-%m-%d")
    resp = client.get(
        f"{EXECUTION_GATE_URL}/analyze/candles",
        params={
            "instrument_key": instrument_key,
            "interval": "1minute",
            "from_date": today,
            "to_date": today,
        },
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json().get("data", {}).get("candles", [])
    # Upstox candle format: [timestamp, open, high, low, close, volume, oi]
    df = pd.DataFrame(data, columns=["ts", "open", "high", "low", "close", "volume", "oi"])
    return df.iloc[::-1].reset_index(drop=True)  # oldest -> newest


def send_order(client: httpx.Client, signal):
    payload = {
        "pod_id": POD_ID,
        "side": signal.side,
        "exchange_segment": signal.exchange_segment,
        "security_id": signal.security_id,
        "quantity": signal.quantity,
        "order_type": signal.order_type,
        "price": signal.price,
    }
    resp = client.post(f"{EXECUTION_GATE_URL}/orders/place", json=payload, timeout=15)
    return resp


def main():
    strategy = load_strategy()
    print(f"[{POD_ID}] started, instruments={INSTRUMENTS}, strategy={STRATEGY_MODULE}")

    with httpx.Client() as client:
        while True:
            try:
                for instrument_key in INSTRUMENTS:
                    if not instrument_key:
                        continue
                    candles = fetch_candles(client, instrument_key)
                    signals = strategy.on_bar(candles)
                    for sig in signals:
                        r = send_order(client, sig)
                        print(f"[{POD_ID}] order -> {sig} -> status {r.status_code}")
            except Exception as e:
                print(f"[{POD_ID}] error: {e}")

            time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()
