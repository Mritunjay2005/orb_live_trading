import os
import time
import httpx
import jwt
from fastapi import FastAPI, Request, Form, Depends, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from .otp import generate_and_send_otp, verify_otp

app = FastAPI(title="dashboard")
templates = Jinja2Templates(directory="app/templates")

QUEUE_SERVICE_URL = os.getenv("QUEUE_SERVICE_URL", "http://queue-service:8000")
JWT_SECRET = os.getenv("DASHBOARD_JWT_SECRET", "dev-secret-change-me")
SESSION_MINUTES = int(os.getenv("OTP_EXPIRY_MINUTES", "10"))


def make_session_token(email: str) -> str:
    payload = {"email": email, "exp": time.time() + SESSION_MINUTES * 60}
    return jwt.encode(payload, JWT_SECRET, algorithm="HS256")


def get_session(request: Request):
    token = request.cookies.get("session")
    if not token:
        return None
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
    except jwt.PyJWTError:
        return None


@app.get("/", response_class=HTMLResponse)
async def login_page(request: Request):
    session = get_session(request)
    if session:
        return RedirectResponse("/live")
    return templates.TemplateResponse("login.html", {"request": request})


@app.post("/request-otp")
async def request_otp(request: Request, email: str = Form(...)):
    generate_and_send_otp(email)
    return templates.TemplateResponse("verify.html", {"request": request, "email": email})


@app.post("/verify-otp")
async def verify_otp_route(request: Request, email: str = Form(...), otp: str = Form(...)):
    if not verify_otp(email, otp):
        return templates.TemplateResponse(
            "verify.html", {"request": request, "email": email, "error": "Invalid or expired code."}
        )
    token = make_session_token(email)
    response = RedirectResponse("/live", status_code=303)
    response.set_cookie("session", token, httponly=True, max_age=SESSION_MINUTES * 60)
    return response


@app.get("/live", response_class=HTMLResponse)
async def live_view(request: Request):
    session = get_session(request)
    if not session:
        return RedirectResponse("/")

    async with httpx.AsyncClient() as client:
        risk = (await client.get(f"{QUEUE_SERVICE_URL}/risk/status", timeout=10)).json()
        txns = (await client.get(f"{QUEUE_SERVICE_URL}/transactions/recent", params={"limit": 20}, timeout=10)).json()

    return templates.TemplateResponse(
        "live.html", {"request": request, "risk": risk, "txns": txns, "email": session["email"]}
    )


@app.get("/logout")
async def logout():
    response = RedirectResponse("/")
    response.delete_cookie("session")
    return response
