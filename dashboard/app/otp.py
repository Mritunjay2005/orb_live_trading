import os
import time
import random
import smtplib
from email.mime.text import MIMEText

SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER")
SMTP_APP_PASSWORD = os.getenv("SMTP_APP_PASSWORD")
OTP_EXPIRY_MINUTES = int(os.getenv("OTP_EXPIRY_MINUTES", "10"))

# In-memory store: {email: (otp, expires_at)}. Fine for a single-instance
# free-tier box; swap for Redis if you ever scale the dashboard to >1 replica.
_otp_store: dict[str, tuple[str, float]] = {}


def generate_and_send_otp(to_email: str) -> None:
    otp = f"{random.randint(0, 999999):06d}"
    expires_at = time.time() + OTP_EXPIRY_MINUTES * 60
    _otp_store[to_email] = (otp, expires_at)

    msg = MIMEText(
        f"Your login code is {otp}. It expires in {OTP_EXPIRY_MINUTES} minutes.\n\n"
        f"This is a READ-ONLY view of a live trading project. No trading "
        f"actions can be taken from this dashboard."
    )
    msg["Subject"] = "Your trading dashboard login code"
    msg["From"] = SMTP_USER
    msg["To"] = to_email

    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
        server.starttls()
        server.login(SMTP_USER, SMTP_APP_PASSWORD)
        server.sendmail(SMTP_USER, [to_email], msg.as_string())


def verify_otp(email: str, otp: str) -> bool:
    entry = _otp_store.get(email)
    if not entry:
        return False
    stored_otp, expires_at = entry
    if time.time() > expires_at:
        del _otp_store[email]
        return False
    if stored_otp != otp:
        return False
    del _otp_store[email]  # one-time use
    return True
