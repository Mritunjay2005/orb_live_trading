"""
queue-service
-------------
Central ledger + event bus:
- Every request/response the execution-gate makes gets logged here (/events).
- Funds & transaction state is tracked here (/risk/status, /funds).
- At end of a trading session (/session/close) it fires two notifications
  via the notifier service: a detailed one (ntfy) and a summary one (Telegram).
"""
import os
import time
import json
import httpx
import redis
from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI(title="queue-service")

r = redis.from_url(os.getenv("REDIS_URL", "redis://redis:6379/0"), decode_responses=True)
NOTIFIER_URL = os.getenv("NOTIFIER_URL", "http://notifier:8000")

EVENTS_KEY = "events:log"          # capped list of recent events
TXN_KEY = "txn:log"                # capped list of trade/order events
PNL_KEY = "risk:daily_pnl"
POSITIONS_KEY = "risk:open_positions"
MAX_LOG_LEN = 5000


class Event(BaseModel):
    kind: str
    ts: float
    payload: dict


class PnlUpdate(BaseModel):
    pod_id: str
    realized_pnl_delta: float
    open_positions: int


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/events")
async def push_event(event: Event):
    r.lpush(EVENTS_KEY, json.dumps(event.dict()))
    r.ltrim(EVENTS_KEY, 0, MAX_LOG_LEN - 1)

    if event.kind in ("order_placed", "order_error", "order_blocked"):
        r.lpush(TXN_KEY, json.dumps(event.dict()))
        r.ltrim(TXN_KEY, 0, MAX_LOG_LEN - 1)

    return {"stored": True}


@app.get("/events/recent")
async def recent_events(limit: int = 50):
    raw = r.lrange(EVENTS_KEY, 0, limit - 1)
    return [json.loads(x) for x in raw]


@app.get("/transactions/recent")
async def recent_transactions(limit: int = 50):
    raw = r.lrange(TXN_KEY, 0, limit - 1)
    return [json.loads(x) for x in raw]


@app.post("/risk/pnl-update")
async def pnl_update(update: PnlUpdate):
    r.incrbyfloat(PNL_KEY, update.realized_pnl_delta)
    r.set(POSITIONS_KEY, update.open_positions)
    return {"ok": True}


@app.get("/risk/status")
async def risk_status():
    pnl = float(r.get(PNL_KEY) or 0)
    positions = int(r.get(POSITIONS_KEY) or 0)
    return {"daily_pnl": pnl, "open_positions": positions}


@app.post("/risk/reset-daily")
async def reset_daily():
    """Call this once per day (e.g. via a cron / GitHub Actions scheduled job
    hitting this endpoint, or a simple cron inside this container) before market open."""
    r.set(PNL_KEY, 0)
    r.set(POSITIONS_KEY, 0)
    return {"reset": True}


@app.post("/session/close")
async def close_session():
    """End-of-day summary -> two separate notifications."""
    pnl = float(r.get(PNL_KEY) or 0)
    positions = int(r.get(POSITIONS_KEY) or 0)
    txns = [json.loads(x) for x in r.lrange(TXN_KEY, 0, 49)]

    detailed_lines = [f"Session close @ {time.strftime('%Y-%m-%d %H:%M:%S')}",
                       f"Daily PnL: {pnl}", f"Open positions: {positions}", "Recent txns:"]
    for t in txns[:20]:
        detailed_lines.append(json.dumps(t))
    detailed_text = "\n".join(detailed_lines)

    summary_lines = []
    for t in txns[:10]:
        p = t.get("payload", {})
        order = p.get("order", {})
        if order:
            summary_lines.append(
                f"{order.get('security_id','?')} | {order.get('side','?')} qty {order.get('quantity','?')} | {time.strftime('%H:%M:%S', time.localtime(t['ts']))}"
            )
    summary_text = "Session summary:\n" + ("\n".join(summary_lines) if summary_lines else "No trades.")

    async with httpx.AsyncClient() as client:
        await client.post(f"{NOTIFIER_URL}/notify/detailed", json={"text": detailed_text}, timeout=10)
        await client.post(f"{NOTIFIER_URL}/notify/summary", json={"text": summary_text}, timeout=10)

    return {"pnl": pnl, "positions": positions, "notified": True}
