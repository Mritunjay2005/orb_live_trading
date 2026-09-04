# ORB Live Trading System

**Opening Range Breakout + ADX(14) live trading engine for NSE equities via Upstox API**  
Single Python process · Free-tier Oracle Cloud (Mumbai) · Docker · Grafana · ntfy · Terraform

> **WARNING**  
> This places **real orders** with **100 % of available capital** and optional **5× intraday leverage**.  
> A hard 4 % daily loss kill-switch is built in. Past paper results do not guarantee live performance.  
> You are solely responsible for all capital risk. Test thoroughly before enabling `LIVE_TRADING=true`.

---

## What this repo contains

| Path | Purpose |
|------|---------|
| `main.py` | **Single** lightweight program – strategy, broker, risk, state, metrics, alerts |
| `filtered_stocks.csv` | Daily instrument list (`symbol,instrument_key,leverage`) – max 6 rows |
| `Dockerfile` + `docker-compose.yml` | Trading process + Prometheus + Grafana |
| `infra/terraform/` | Always-Free OCI (Mumbai) – VCN, Ampere A1, **reserved public IP** |
| `monitoring/` | Prometheus config + Grafana dashboards |
| `.github/workflows/` | CI (lint/test) + image build to GHCR |
| `REASONING.md` | Why every design decision was made |
| `.env.example` | All secrets / config keys (never commit real `.env`) |

---

## Quick architecture

```
GitHub (private) ──CI/CD──► GHCR image
                              │
                              ▼
OCI Always Free (Mumbai) ──── Docker Compose
                              ├── trading (main.py)
                              ├── prometheus
                              └── grafana  ← you open in browser
```

- At ~08:50 IST (weekdays) the process wakes, reads funds, divides capital equally, starts watching 15-min candles.
- Entries = market orders on ORB breakout (after ADX > 25).
- Trailing stop, target 1.5R, force square-off at 15:14 IST.
- 4 % daily loss → kill switch (close everything, no new trades).
- All events pushed to ntfy.sh + written to local logs + exposed as Prometheus metrics.

---

## Prerequisites

1. Upstox developer app with order-placement permission + a valid access token (regenerate daily if required).
2. Oracle Cloud account (Always Free eligible) with API key (you already have one).
3. GitHub account (private repo).
4. A machine with Terraform ≥ 1.5 and `oci` CLI (or just Terraform) for the first deploy.
5. ntfy.sh topic (public is fine).

---

## 1. Create the GitHub repository

```bash
# on your laptop
git clone <this-repo-url>   # or create empty private repo "orb_live_trading"
cd orb_live_trading
```

Copy the files from this project into it, then:

```bash
git add .
git commit -m "Initial ORB live trading system"
git push origin main
```

---

## 2. Configure secrets (local + GitHub)

Copy the example:

```bash
cp .env.example .env
# edit .env with real values – NEVER commit .env
```

Required keys (see `.env.example`):

- `UPSTOX_ACCESS_TOKEN`
- `NTFY_TOPIC` (e.g. `my-orb-alerts`)
- `LIVE_TRADING=false`   ← keep false until you are ready
- `GITHUB_TOKEN` (for private image pull if needed)
- OCI credentials are used only by Terraform (not inside the container)

Also add the same values as **GitHub Actions secrets** if you enable the deploy workflow.

---

## 3. First-time OCI deploy (Terraform)

```bash
cd infra/terraform
cp terraform.tfvars.example terraform.tfvars
# fill in:
#   tenancy_ocid, user_ocid, fingerprint, private_key_path
#   compartment_ocid, region = "ap-mumbai-1"
#   ssh_public_key
#   your current public IP as ssh_ingress_cidr (e.g. "1.2.3.4/32")

terraform init
terraform plan
terraform apply
```

**Important outputs:**

```
public_ip = "x.x.x.x"          ← RESERVED public IP
ssh_command = "ssh -i ... opc@x.x.x.x"
grafana_url = "http://x.x.x.x:3000"
```

1. Copy the **public_ip**.
2. In Upstox Developer Console → your app → Static IP / whitelist → add this IP.
3. SSH into the instance and place the real `.env` file (or use cloud-init to inject it).

The cloud-init script installs Docker, pulls the image (or clones the repo), starts `docker-compose`, and creates a systemd timer that runs the trading window.

---

## 4. filtered_stocks.csv

```csv
symbol,instrument_key,leverage
CUPID,NSE_EQ|INE509F01029,true
TCC,NSE_EQ|INE887D01024,false
...
```

- Maximum **6** instruments.
- `leverage=true` → quantity is multiplied by 5 after cash-based sizing.
- Update the file in GitHub; the instance re-reads it every morning.

---

## 5. Enabling live trading

1. Confirm the reserved IP is whitelisted in Upstox.
2. Confirm Grafana shows healthy metrics.
3. Set `LIVE_TRADING=true` in `.env` on the instance and restart the container.
4. Watch ntfy + Grafana + Upstox order book simultaneously on the first day.

---

## 6. Daily behaviour

| Time (IST) | Action |
|------------|--------|
| ~08:50 | Process wakes, loads CSV, fetches available margin, calculates per-instrument budget |
| 09:15–09:30 | Opening range formed |
| After 09:30 | Watch for first breakout + ADX > 25 → market order |
| Continuous | Trail stop, check targets, check 4 % daily loss |
| 15:14 | Force square-off any open position |
| After 15:30 | Sleep until next weekday |

---

## 7. Grafana dashboards

Open `http://<reserved-ip>:3000` (default admin / admin – change immediately).

Panels:
- Equity curve
- Open positions
- Daily realised P&L
- Trade log
- Error / health log
- Per-instrument allocation & utilisation
- System health (API latency, last candle age, kill-switch status)

---

## 8. ntfy alerts

Events sent to your topic:
- `STARTUP` / `SHUTDOWN`
- `ENTRY` / `EXIT`
- `STOP_LOSS` / `TRAILING_SL` / `TARGET` / `SQUARE_OFF`
- `DAILY_LOSS_LIMIT`
- `ERROR` (API, order rejection, etc.)

---

## 9. Safety checklist before first live day

- [ ] `LIVE_TRADING=false` tested end-to-end (orders are only logged)
- [ ] Reserved IP whitelisted in Upstox
- [ ] 4 % kill-switch verified in paper mode
- [ ] Max 6 instruments
- [ ] `.env` never committed
- [ ] Grafana reachable and showing metrics
- [ ] You understand market orders can slip

---

## 10. Updating the system

```bash
# on laptop
git push
# GitHub Actions builds new image

# on OCI instance
cd /opt/orb_live_trading
docker compose pull
docker compose up -d
```

---

## Disclaimer

This software is provided for educational and research purposes.  
Automated trading involves substantial risk of loss.  
The authors and contributors accept no liability for any financial losses incurred through the use of this system.

---

*See REASONING.md for the detailed design rationale.*
