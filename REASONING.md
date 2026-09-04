# REASONING.md — Design Decisions & Why Everything Exists

This document explains **why** each major design choice was made for the `orb_live_trading` system.  
Read this before modifying anything.

---

## 1. Single Python Program (`main.py`)

**Why:** You explicitly requested a lightweight, single-file program that contains all logic.  
This reduces operational surface area on a free-tier instance (no multi-service dependency hell) and makes the trading process easy to start/stop via systemd.

**Trade-off:** The file is long. All strategy, broker adapter, risk, state, metrics and alerting live in one place.  
Helpers are kept as pure functions inside the same file so the mental model stays “one process = one trading day”.

---

## 2. Real Order Placement + 100 % Capital + 5× Leverage

**Why you asked for it:** You have already paper-traded and want live execution with maximum capital efficiency.

**How it is implemented safely:**
- At start of day the system calls Upstox `GET /v2/user/get-funds-and-margin` and takes `equity.available_margin`.
- That amount is divided equally by the number of instruments in `filtered_stocks.csv` (max 6).
- For each instrument the system calculates how many shares fit inside the allocated cash budget at current LTP.
- If the CSV column `leverage=true`, the quantity is multiplied by 5 (your stated 5× intraday leverage rule).
- Product type is forced to `"I"` (Intraday) so positions are expected to be squared off the same day.
- A hard **4 % daily loss kill-switch** is checked continuously. When equity (starting capital – realised losses) falls ≥ 4 %, all open positions are force-closed and no new entries are allowed for the rest of the day.

**Why the kill-switch is non-negotiable:**  
Per-trade stop-losses do not protect the account from a sequence of losing trades. 4 % is the number you chose.

---

## 3. Market Orders for Entries

You chose market orders.  
On a 15-minute ORB breakout the system waits for the first closed candle that breaches High1 or Low1, then fires a market order in the breakout direction.  
This matches the original back-tester’s assumption of “fill at the breakout level” as closely as possible with real exchange execution.

---

## 4. Square-off at 15:14 IST

Copied verbatim from your existing `orb_backtester.py` / `orb_trading_engine.py`.  
Any still-open position is closed with a market order at or after 15:14 so that the account never carries overnight risk under product `"I"`.

---

## 5. CSV Format & Daily Re-read

```csv
symbol,instrument_key,leverage
CUPID,NSE_EQ|INE509F01029,true
...
```

- `leverage` is a boolean (`true`/`false`). When true the system uses 5×.
- File is re-read every morning so you can update the list via GitHub and the instance will pick it up after the next restart or daily wake-up.
- Hard limit of 6 instruments protects the free instance and Upstox rate limits.

---

## 6. Free-Tier OCI Only (Mumbai) + Reserved Public IP

**Why reserved public IP:**  
Upstox requires you to whitelist the IP that places orders. An ephemeral IP changes on stop/start. A **RESERVED** public IP stays the same for the lifetime of the reservation (free within Always Free limits).

**Shape:** `VM.Standard.A1.Flex` with 2 OCPU / 12 GB (current Always Free ceiling for many accounts as of mid-2026).  
If capacity is unavailable in Mumbai the Terraform will fail; you may need to retry or use a different AD.

**What Terraform creates:**
- VCN + public subnet + Internet Gateway + security lists (SSH, Grafana 3000, Prometheus 9090)
- Ampere A1 instance
- Reserved public IP attached to the instance
- cloud-init that installs Docker, docker-compose, pulls the image (or clones the repo), writes systemd units, and starts the stack

---

## 7. Self-hosted Grafana + Prometheus on the same instance

**Why:** You asked for a dashboard showing equity curve, open positions, daily P&L, trade log, error log, per-instrument allocation and health.  
On free tier there is no budget for a separate monitoring cluster, so everything runs on the same host via `docker-compose`.

Metrics are exposed by the trading process itself on `/metrics` (Prometheus format). Grafana dashboards are provisioned automatically.

---

## 8. ntfy.sh Public Topic

Lightweight, zero-infrastructure push notifications for:
- Startup / shutdown
- Entry / exit
- Stop-loss hit
- Daily loss limit triggered
- System / API errors

You supply the public topic name in `.env`.

---

## 9. Secrets only in `.env`

No tokens, keys or private material ever enter the Git repository.  
`.env.example` shows the required keys. On the instance you create a real `.env` (or inject via cloud-init / systemd EnvironmentFile).

---

## 10. Auto start / sleep schedule

A systemd timer (or simple cron inside the container) wakes the process at ~08:50 IST on weekdays, runs the trading day, then exits after 15:30.  
The container itself can stay up; the Python process sleeps until the next trading window.

Weekends are treated as non-trading. You maintain any extra holiday list yourself.

---

## 11. GitHub Actions CI/CD

- On push to `main`: lint + basic unit tests of pure functions.
- Build Docker image → push to GitHub Container Registry (GHCR).
- Optional: a deploy workflow that SSHes into the instance and pulls the new image (you enable it after first setup).

---

## 12. What this system deliberately does **not** do

- No real-money order placement unless `LIVE_TRADING=true` in `.env`.
- No overnight positions (product = I + forced square-off).
- No complex portfolio optimisation — equal cash allocation only.
- No automatic holiday calendar beyond weekends (you own the holiday list).
- No multi-account or multi-broker support.

---

## Final warning

Automated live trading with 100 % capital and leverage can produce large losses in a single session.  
The 4 % kill-switch, market-order execution, and forced square-off are the only hard protections.  
You are solely responsible for the capital you put at risk and for verifying every order in the Upstox console.

---

*Document generated as part of the orb_live_trading project setup.*
