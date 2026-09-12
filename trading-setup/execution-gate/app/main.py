import os
import time
import httpx
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from .broker_router import get_data_client, get_order_client

app = FastAPI(title="execution-gate")

QUEUE_SERVICE_URL = os.getenv("QUEUE_SERVICE_URL", "http://queue-service:8000")
MAX_DAILY_LOSS_INR = float(os.getenv("MAX_DAILY_LOSS_INR", "5000"))
MAX_OPEN_POSITIONS = int(os.getenv("MAX_OPEN_POSITIONS", "10"))


class OrderRequest(BaseModel):
    pod_id: str
    side: str                 # BUY / SELL
    exchange_segment: str      # e.g. NSE_EQ, NSE_FO
    security_id: str
    quantity: int
    order_type: str = "MARKET"
    product_type: str = "INTRADAY"
    price: float = 0


async def log_event(kind: str, payload: dict):
    """Fire-and-forget log of every request/response into queue-service's ledger."""
    try:
        async with httpx.AsyncClient() as client:
            await client.post(
                f"{QUEUE_SERVICE_URL}/events",
                json={"kind": kind, "ts": time.time(), "payload": payload},
                timeout=5,
            )
    except Exception:
        pass  # never let logging failures block trading


async def is_kill_switch_active() -> bool:
    if os.getenv("KILL_SWITCH", "false").lower() == "true":
        return True
    try:
        async with httpx.AsyncClient() as client:
            r = await client.get(f"{QUEUE_SERVICE_URL}/risk/status", timeout=5)
            r.raise_for_status()
            data = r.json()
            return data.get("daily_pnl", 0) <= -MAX_DAILY_LOSS_INR or data.get(
                "open_positions", 0
            ) >= MAX_OPEN_POSITIONS
    except Exception:
        # fail-safe: if we can't confirm risk status, block new orders
        return True


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/analyze/quote")
async def analyze_quote(instrument_key: str):
    client = get_data_client()
    data = await client.get_quote(instrument_key)
    await log_event("analyze_quote", {"instrument_key": instrument_key, "response": data})
    return data


@app.get("/analyze/candles")
async def analyze_candles(instrument_key: str, interval: str, from_date: str, to_date: str):
    client = get_data_client()
    data = await client.get_candles(instrument_key, interval, from_date, to_date)
    await log_event("analyze_candles", {"instrument_key": instrument_key, "interval": interval})
    return data


@app.post("/orders/place")
async def place_order(order: OrderRequest):
    if await is_kill_switch_active():
        await log_event("order_blocked", order.dict())
        raise HTTPException(status_code=423, detail="Trading halted by risk kill-switch")

    client = get_order_client()
    try:
        result = await client.place_order(order.dict())
    except httpx.HTTPStatusError as e:
        await log_event("order_error", {"order": order.dict(), "error": str(e)})
        raise HTTPException(status_code=502, detail=f"Broker rejected order: {e}")

    await log_event("order_placed", {"order": order.dict(), "result": result})
    return result


@app.get("/orders/positions")
async def positions():
    client = get_order_client()
    data = await client.get_positions()
    return data


@app.get("/orders/funds")
async def funds():
    client = get_order_client()
    data = await client.get_funds()
    await log_event("funds_check", data)
    return data
