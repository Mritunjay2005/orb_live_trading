"""
broker_router.py
-----------------
Single place that decides which broker API handles which job.
- Upstox is used for market data / analysis (candles, quotes, LTP).
- Dhan is used for order placement / modification / cancellation.
This split is configurable via DATA_PROVIDER / ORDER_PROVIDER env vars,
so you can swap either side independently without touching algo-pod code.
"""
import os
import httpx

UPSTOX_BASE = "https://api.upstox.com/v2"
DHAN_BASE = "https://api.dhan.co"

DATA_PROVIDER = os.getenv("DATA_PROVIDER", "upstox")
ORDER_PROVIDER = os.getenv("ORDER_PROVIDER", "dhan")


class UpstoxClient:
    def __init__(self):
        self.token = os.getenv("UPSTOX_ACCESS_TOKEN")
        self.headers = {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/json",
        }

    async def get_quote(self, instrument_key: str):
        async with httpx.AsyncClient() as client:
            r = await client.get(
                f"{UPSTOX_BASE}/market-quote/quotes",
                params={"instrument_key": instrument_key},
                headers=self.headers,
                timeout=10,
            )
            r.raise_for_status()
            return r.json()

    async def get_candles(self, instrument_key: str, interval: str, from_date: str, to_date: str):
        async with httpx.AsyncClient() as client:
            r = await client.get(
                f"{UPSTOX_BASE}/historical-candle/{instrument_key}/{interval}/{to_date}/{from_date}",
                headers=self.headers,
                timeout=15,
            )
            r.raise_for_status()
            return r.json()


class DhanClient:
    def __init__(self):
        self.client_id = os.getenv("DHAN_CLIENT_ID")
        self.token = os.getenv("DHAN_ACCESS_TOKEN")
        self.headers = {
            "access-token": self.token,
            "Content-Type": "application/json",
        }

    async def place_order(self, order: dict):
        payload = {
            "dhanClientId": self.client_id,
            "transactionType": order["side"],           # BUY / SELL
            "exchangeSegment": order["exchange_segment"],
            "productType": order.get("product_type", "INTRADAY"),
            "orderType": order.get("order_type", "MARKET"),
            "validity": order.get("validity", "DAY"),
            "securityId": order["security_id"],
            "quantity": order["quantity"],
            "price": order.get("price", 0),
        }
        async with httpx.AsyncClient() as client:
            r = await client.post(
                f"{DHAN_BASE}/orders", json=payload, headers=self.headers, timeout=10
            )
            r.raise_for_status()
            return r.json()

    async def cancel_order(self, order_id: str):
        async with httpx.AsyncClient() as client:
            r = await client.delete(
                f"{DHAN_BASE}/orders/{order_id}", headers=self.headers, timeout=10
            )
            r.raise_for_status()
            return r.json()

    async def get_positions(self):
        async with httpx.AsyncClient() as client:
            r = await client.get(
                f"{DHAN_BASE}/positions", headers=self.headers, timeout=10
            )
            r.raise_for_status()
            return r.json()

    async def get_funds(self):
        async with httpx.AsyncClient() as client:
            r = await client.get(
                f"{DHAN_BASE}/fundlimit", headers=self.headers, timeout=10
            )
            r.raise_for_status()
            return r.json()


DATA_CLIENTS = {"upstox": UpstoxClient()}
ORDER_CLIENTS = {"dhan": DhanClient()}


def get_data_client():
    return DATA_CLIENTS[DATA_PROVIDER]


def get_order_client():
    return ORDER_CLIENTS[ORDER_PROVIDER]
