import os
import httpx
from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI(title="notifier")

NTFY_SERVER = os.getenv("NTFY_SERVER", "https://ntfy.sh")
NTFY_TOPIC = os.getenv("NTFY_TOPIC", "")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")


class NotifyPayload(BaseModel):
    text: str


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/notify/detailed")
async def notify_detailed(payload: NotifyPayload):
    """Full detail -> ntfy.sh"""
    if not NTFY_TOPIC:
        return {"sent": False, "reason": "NTFY_TOPIC not set"}
    async with httpx.AsyncClient() as client:
        await client.post(
            f"{NTFY_SERVER}/{NTFY_TOPIC}",
            data=payload.text.encode("utf-8"),
            headers={"Title": "Trading Session - Full Detail"},
            timeout=10,
        )
    return {"sent": True}


@app.post("/notify/summary")
async def notify_summary(payload: NotifyPayload):
    """Reduced detail (instrument, position, time only) -> Telegram"""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return {"sent": False, "reason": "Telegram not configured"}
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    async with httpx.AsyncClient() as client:
        await client.post(
            url, json={"chat_id": TELEGRAM_CHAT_ID, "text": payload.text}, timeout=10
        )
    return {"sent": True}
