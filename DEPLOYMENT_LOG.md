# ORB Live Trading — Full Deployment & Communication Log

**Project:** `orb_live_trading`  
**GitHub:** https://github.com/Mritunjay2005/orb_live_trading  
**Period covered:** 4 September 2026 – 5 September 2026  
**Final Reserved Public IP:** `80.225.255.207`  
**Region:** Oracle Cloud, Mumbai (`ap-mumbai-1`)

This document records every meaningful decision, command, error, and fix from the full conversation, in chronological order.

---

## Phase 0 — Original Request & Requirements Lock

### User goal
Convert the existing paper ORB+ADX system into:
- Single lightweight Python program with **real order placement**
- 100% of available Upstox capital
- Equal budget split across instruments (max 6)
- 5× leverage when CSV `leverage=true`
- Docker + GitHub Actions CI/CD
- Self-hosted Grafana + Prometheus
- ntfy.sh alerts
- Terraform deploy on Oracle Cloud Always Free (Mumbai)
- Secrets only in `.env`
- Auto wake/sleep on trading days, square-off 15:14 IST
- Static IP for Upstox whitelist

### Locked decisions
| Item | Choice |
|------|--------|
| Daily loss kill-switch | **4%** |
| Entry order type | **Market** |
| Capital | Upstox funds API → 100% of `available_margin` |
| CSV columns | `symbol,instrument_key,leverage` |
| Max instruments | **6** |
| Holidays | Weekends only (user maintains extra list) |
| Cloud | Always Free only, Mumbai |
| Grafana | Self-hosted on same instance |
| Alerts | ntfy.sh public topic |
| Live switch | `LIVE_TRADING=true/false` in `.env` |

### Security note given
Hardcoded Upstox tokens and OCI private key in original attachments were treated as compromised; user was told to rotate them.

---

## Phase 1 — Codebase Creation (by assistant)

Full project generated under `orb_live_trading/` with:

| Path | Purpose |
|------|---------|
| `main.py` | Single-file live engine (ORB+ADX, orders, risk, ntfy, metrics) |
| `Dockerfile` / `docker-compose.yml` | Trading + Prometheus + Grafana |
| `infra/terraform/` | Always Free Ampere A1, VCN, security lists |
| `monitoring/` | Prometheus + Grafana dashboards |
| `.github/workflows/` | CI + image build to GHCR |
| `README.md` / `REASONING.md` | Setup guide + design rationale |
| `.env.example` | All secrets template |
| `filtered_stocks.csv` | Example instrument list |

Strategy rules kept aligned with original backtester (ORB 15-min, ADX>25, trailing stop, 1.5R, square-off 15:14).

---

## Phase 2 — GitHub Repository Setup

### User machine path
```text
Y:/TRADING_SETUP/orb_live_trading
```

### Commands run (Git Bash) — chronological

```bash
cd /y/TRADING_SETUP/orb_live_trading

git init
# Expected: Initialized empty Git repository ...

git branch -M main

git add .
# Expected: LF/CRLF warnings only (normal on Windows)

git commit -m "Initial ORB live trading system"
# Expected: [main (root-commit) ...] 19 files changed ...

git remote add origin https://github.com/Mritunjay2005/orb_live_trading.git

git push -u origin main
# Expected: branch 'main' set up to track 'origin/main'
```

**Result:** Push succeeded. Repo live at  
https://github.com/Mritunjay2005/orb_live_trading

### Personal Access Token explanation given
GitHub no longer accepts account password for HTTPS push. User must create a **Personal Access Token (classic)** with `repo` scope and paste it when Git asks for password.

### Mistake corrected
User ran on **laptop**:
```bash
git pull
docker compose pull
docker compose up -d
```
These commands are for the **OCI server only**, not the Windows laptop. Docker Desktop was not running; `.env` did not exist locally. Corrected.

---

## Phase 3 — OCI Credentials

User provided OCI config snippet:

```ini
user=ocid1.user.oc1..aaaaaaaanlehrfsrhro5tbpzwg2l6p6rc27hmwj35jpy7qwyx3sm5hgn2w4a
fingerprint=f2:19:6f:be:ff:39:1e:04:a9:88:fe:65:83:f7:0c:4b
tenancy=ocid1.tenancy.oc1..aaaaaaaaci65sub4wzeolfoekfknvqxpw5wmiawwra2zpa24k6kz5fhnxwfq
region=ap-mumbai-1
```

User confirmed possession of:
- OCI API private key (`.pem`)
- Tenancy OCID, User OCID, Fingerprint, Compartment OCID

### How to obtain remaining Terraform fields (instructions given)

| Field | How to get |
|-------|------------|
| `private_key_path` | Full path to OCI `.pem` file (use `/` in path) |
| `ssh_public_key` | `cat ~/.ssh/id_ed25519.pub` (or generate with `ssh-keygen -t ed25519`) |
| `ssh_ingress_cidr` | Current public IP from whatismyipaddress.com + `/32` |

User’s SSH public key used:
```text
ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIGzggXOd1cXA8S2x5ZkLDvI8J1bPzDvtUen4V1a5EHxm piyus@LAPTOP-M79JVL2R
```

User’s home IP used for SSH rule:
```text
122.179.89.81/32
```

---

## Phase 4 — Terraform Deploy

### Commands

```bash
cd /y/TRADING_SETUP/orb_live_trading/infra/terraform

cp terraform.tfvars.example terraform.tfvars
# User filled real values in notepad

terraform init
# Expected: Terraform has been successfully initialized!
# Provider installed: oracle/oci v9.0.0

terraform plan
# Expected: Plan: 6 to add, 0 to change, 0 to destroy.
# Resources: VCN, IGW, route table, security list, subnet, Ampere A1 instance
```

### Apply

```bash
terraform apply
# Typed: yes
```

### Successful outputs (first ephemeral IP)

```text
grafana_url    = "http://80.225.198.208:3000"
instance_id    = "ocid1.instance.oc1.ap-mumbai-1.anrg6ljrxlgsyficsu334twtxurhj2b3ybycemyllp3sajt2hlyyyy6kloia"
metrics_url    = "http://80.225.198.208:8000/metrics"
prometheus_url = "http://80.225.198.208:9090"
public_ip      = "80.225.198.208"
ssh_command    = "ssh -i <your-private-key> opc@80.225.198.208"
```

**Instance:** `orb-live-trading`  
**Shape:** VM.Standard.A1.Flex (2 OCPU / 12 GB)  
**Image:** Canonical Ubuntu 22.04 (ARM)  
**Note:** Console showed username **`ubuntu`** (not `opc`).

---

## Phase 5 — Reserved Public IP

User struggled with OCI console navigation (no classic “Resources” menu; different tab layout).

### Guidance given
- Prefer **Compute → Instance → Networking tab → VNIC → IP addresses**
- Or **Networking → IP management → Public IPs → Reserve → Assign to VNIC**
- Reserved IP can be deferred until before live trading

### Final result (from screenshot)

| Field | Value |
|-------|--------|
| Private IP | `10.0.1.66` |
| Public IP | **`80.225.255.207 (Reserved)`** |
| IP lifetime column | Still showed “Ephemeral” (UI quirk); IP itself marked Reserved |

**Old IP** `80.225.198.208` replaced by **`80.225.255.207`**.

User confirmed:
- Reserved IP done
- Whitelisted in Upstox
- SSH works with new IP

---

## Phase 6 — First SSH into Server

### Commands tried

```bash
ssh -i ~/.ssh/id_ed25519 ubuntu@80.225.198.208   # original IP
# Later:
ssh -i ~/.ssh/id_ed25519 ubuntu@80.225.255.207   # reserved IP
```

**Result:** User confirmed “yes i am in”.

Working directory on server after login: user home, then `/opt/orb_live_trading`.

---

## Phase 7 — Application Setup on Server

### Clone and env

```bash
cd /opt/orb_live_trading
sudo chown -R $USER:$USER /opt/orb_live_trading
git clone https://github.com/Mritunjay2005/orb_live_trading.git .
cp .env.example .env
nano .env
# User sets UPSTOX_ACCESS_TOKEN, NTFY_TOPIC, LIVE_TRADING=false
```

### Docker permission error (first attempt)

```bash
docker-compose up -d
# Error: PermissionError ... Permission denied on docker socket
```

**Cause:** `ubuntu` user not in `docker` group (cloud-init had targeted `opc`).

**Fix:**
```bash
sudo usermod -aG docker $USER
newgrp docker
docker ps
# Expected: empty list, no error
```

### docker vs docker-compose

```bash
docker compose up -d
# Error: unknown shorthand flag: 'd' in -d
```

**Cause:** Server has Compose v1 as `docker-compose` (hyphen), not plugin `docker compose`.

```bash
docker --version
# Docker version 29.1.3 ...

docker-compose --version
# docker-compose version 1.29.2 ...
```

**Correct command:** `docker-compose` (with hyphen).

### First successful build & start (partial)

```bash
docker-compose up -d
```

- Built `trading` image from `python:3.12-slim`
- Pulled Prometheus v2.54.1 and Grafana 11.2.0
- Created `orb-trading` and `orb-prometheus` successfully
- **Grafana failed:** mount conflict on provisioning file  
  `read-only file system` when mounting `provisioning.yml` onto dashboards path

### Grafana fix steps

```bash
mkdir -p monitoring/grafana/provisioning/dashboards
mkdir -p monitoring/grafana/provisioning/datasources
cp monitoring/grafana/provisioning.yml monitoring/grafana/provisioning/dashboards/dashboards.yml

# Created datasource prometheus.yml pointing at http://prometheus:9090
# Edited docker-compose.yml volumes for grafana to:
#   - grafana_data:/var/lib/grafana
#   - ./monitoring/grafana/provisioning:/etc/grafana/provisioning:ro
#   - ./monitoring/grafana/dashboards:/var/lib/grafana/dashboards:ro
# Updated path in dashboards.yml to /var/lib/grafana/dashboards
```

### ContainerConfig error (docker-compose 1.29.2 bug)

```text
KeyError: 'ContainerConfig'
```

**Fix:**
```bash
docker rm -f 70c1d36779c7_orb-grafana orb-grafana 2>/dev/null
docker-compose rm -f grafana
docker-compose up -d --no-deps grafana
```

### Final container status (success)

```text
Name            State
orb-grafana     Up
orb-prometheus  Up
orb-trading     Up (healthy)
```

---

## Phase 8 — Verification

### Trading logs

```bash
docker-compose logs --tail=50 trading
```

**Observed:**
```text
Prometheus metrics on :8000
ORB Live Engine starting  LIVE_TRADING=False
Sleeping 139528 seconds until 2026-09-07T08:50:00+05:30
```

**Meaning:** Weekend detected; engine correctly sleeps until Monday 7 Sep 2026 08:50 IST.

### Metrics

```bash
curl -s http://localhost:8000/metrics | head -20
# Expected: Prometheus metrics output (python_gc_*, process_*, etc.)
```

### Grafana

Browser: `http://80.225.255.207:3000`  
Login: `admin` / `admin`  
User confirmed it opened successfully.

---

## Phase 9 — Final State Summary

| Item | Value |
|------|--------|
| GitHub | https://github.com/Mritunjay2005/orb_live_trading |
| OCI Instance | `orb-live-trading` (Ampere A1, 2 OCPU / 12 GB) |
| Reserved Public IP | **`80.225.255.207`** |
| SSH | `ssh -i ~/.ssh/id_ed25519 ubuntu@80.225.255.207` |
| Grafana | http://80.225.255.207:3000 |
| Prometheus | http://80.225.255.207:9090 |
| Metrics | http://80.225.255.207:8000/metrics |
| LIVE_TRADING | `false` (paper) |
| Next wake | Monday 2026-09-07 08:50 IST |

---

## Phase 10 — Ongoing Operations Cheat Sheet

### On laptop (code changes)

```bash
cd /y/TRADING_SETUP/orb_live_trading
# edit files
git add .
git commit -m "describe change"
git push
```

Image rebuilds via GitHub Actions. Server does **not** auto-pull yet (manual update required unless deploy workflow is added later).

### On server (update code + restart)

```bash
ssh -i ~/.ssh/id_ed25519 ubuntu@80.225.255.207
cd /opt/orb_live_trading
git pull
docker-compose up -d --build
docker-compose ps
docker-compose logs -f trading
```

### After editing `.env` on server

```bash
cd /opt/orb_live_trading
nano .env
docker-compose restart trading
docker-compose logs --tail=30 trading
```

### Useful checks

```bash
docker-compose ps
docker-compose logs --tail=50 trading
curl -s http://localhost:8000/metrics | head
```

---

## Still Pending / Recommended Before Live

1. Confirm valid `UPSTOX_ACCESS_TOKEN` in server `.env`
2. Confirm `NTFY_TOPIC` set
3. Keep `LIVE_TRADING=false` for at least one full paper trading day
4. Watch logs Monday morning after 08:50 IST
5. Only then set `LIVE_TRADING=true` and restart trading container
6. Optional: add GitHub Actions deploy workflow for automatic server pull on push

---

## Error → Fix Index (quick reference)

| Error | Fix |
|-------|-----|
| `docker compose` unknown flag `-d` | Use `docker-compose` (hyphen) |
| Permission denied docker socket | `sudo usermod -aG docker $USER` then `newgrp docker` |
| Grafana mount read-only / path conflict | Fix provisioning dir structure + volumes |
| `KeyError: 'ContainerConfig'` | `docker rm -f` broken container, `docker-compose up -d --no-deps grafana` |
| SSH user | Use `ubuntu@`, not `opc@` (Ubuntu image) |
| IP changed after reserve | Use new IP `80.225.255.207` everywhere |

---

## Safety Reminders Recorded

- Real orders only when `LIVE_TRADING=true`
- Hard 4% daily loss kill-switch
- Forced square-off at 15:14 IST
- Max 6 instruments
- Product type Intraday (`I`) — no overnight holds by design
- Never commit `.env` or `.pem` keys
- Rotate any tokens/keys that were previously exposed

---

**End of log**  
Generated from the full deployment conversation (4–5 September 2026).

---

## Phase 11 — Prometheus & Monitoring Stack (Detailed)

### Architecture

```
main.py (trading container)
    │ exposes /metrics on port 8000
    ▼
Prometheus (port 9090)
    │ scrapes trading:8000 every 15s
    ▼
Grafana (port 3000)
    │ reads Prometheus as datasource
    ▼
Browser dashboard
```

### Prometheus configuration

**File on server:** `/opt/orb_live_trading/monitoring/prometheus/prometheus.yml`

```yaml
global:
  scrape_interval: 15s
  evaluation_interval: 15s

scrape_configs:
  - job_name: "orb-trading"
    static_configs:
      - targets: ["trading:8000"]
    metrics_path: /metrics
```

- Scrapes the trading container hostname `trading` on port `8000`
- Interval: every 15 seconds
- Path: `/metrics` (Prometheus client library in `main.py`)

### Metrics exposed by `main.py`

These are defined in code and available at:

- Inside server: `http://localhost:8000/metrics`
- From browser: `http://80.225.255.207:8000/metrics`

| Metric name | Type | Meaning |
|-------------|------|---------|
| `orb_equity` | Gauge | Current equity (start-of-day capital + realised PnL) |
| `orb_daily_pnl` | Gauge | Realised PnL today |
| `orb_open_positions` | Gauge | Number of open positions |
| `orb_trades_total` | Counter | Closed trades (labels: symbol, direction, exit_reason) |
| `orb_errors_total` | Counter | Errors (label: type) |
| `orb_api_latency_seconds` | Histogram | Upstox API latency (label: endpoint) |
| `orb_kill_switch_active` | Gauge | 1 if daily loss limit hit, else 0 |
| `orb_allocation_budget` | Gauge | Per-instrument cash budget (label: symbol) |
| `orb_last_candle_age_seconds` | Gauge | Age of newest closed candle (label: symbol) |

Plus standard Python process metrics (`python_gc_*`, `process_*`, etc.).

### How Prometheus was started

```bash
# Part of docker-compose up -d
# Image: prom/prometheus:v2.54.1
# Container name: orb-prometheus
# Port mapping: 0.0.0.0:9090 -> 9090
# Volume: prom_data (persistent TSDB, 15-day retention)
# Command:
#   --config.file=/etc/prometheus/prometheus.yml
#   --storage.tsdb.retention.time=15d
```

### Verify Prometheus is scraping

On server:

```bash
# Prometheus UI targets page
curl -s http://localhost:9090/api/v1/targets | head

# Or open in browser:
# http://80.225.255.207:9090
# Status → Targets → should show job "orb-trading" as UP
```

Query examples in Prometheus UI (`http://80.225.255.207:9090`):

```
orb_equity
orb_daily_pnl
orb_open_positions
orb_kill_switch_active
rate(orb_errors_total[5m])
```

### Grafana configuration

**Image:** `grafana/grafana:11.2.0`  
**Container:** `orb-grafana`  
**Port:** `3000`  
**Default login:** `admin` / `admin` (change on first login)

**Datasource** (created during fix):

File: `monitoring/grafana/provisioning/datasources/prometheus.yml`

```yaml
apiVersion: 1
datasources:
  - name: Prometheus
    type: prometheus
    access: proxy
    url: http://prometheus:9090
    isDefault: true
    editable: true
```

**Dashboard provider:**

File: `monitoring/grafana/provisioning/dashboards/dashboards.yml`

```yaml
apiVersion: 1
providers:
  - name: "ORB"
    orgId: 1
    folder: ""
    type: file
    disableDeletion: false
    editable: true
    options:
      path: /var/lib/grafana/dashboards
```

**Dashboard JSON:**

File: `monitoring/grafana/dashboards/orb_overview.json`

Panels included:
- Equity (`orb_equity`)
- Daily Realised PnL (`orb_daily_pnl`)
- Open Positions (`orb_open_positions`)
- Kill Switch Active (`orb_kill_switch_active`)
- Allocation Budget per Symbol (`orb_allocation_budget`)
- API Latency
- Errors rate

### Grafana volume fix (what we changed)

Original (broken) mounts caused read-only / path conflicts.

Final working volumes in `docker-compose.yml` for grafana:

```yaml
volumes:
  - grafana_data:/var/lib/grafana
  - ./monitoring/grafana/provisioning:/etc/grafana/provisioning:ro
  - ./monitoring/grafana/dashboards:/var/lib/grafana/dashboards:ro
```

### Access URLs (Reserved IP)

| Service | URL |
|---------|-----|
| Grafana | http://80.225.255.207:3000 |
| Prometheus | http://80.225.255.207:9090 |
| Trading metrics | http://80.225.255.207:8000/metrics |

### Security list ports opened by Terraform

| Port | Purpose |
|------|---------|
| 22 | SSH (restricted to user home IP `/32`) |
| 3000 | Grafana |
| 9090 | Prometheus |
| 8000 | Trading metrics |

---

## Phase 12 — ntfy.sh Alerts (Configured in Code)

**Not fully verified live yet** (engine is sleeping until Monday).

Configured via `.env`:
- `NTFY_TOPIC=...`
- `NTFY_SERVER=https://ntfy.sh` (default)

Events that will be pushed when trading runs:
- STARTUP / SHUTDOWN
- ENTRY / EXIT
- STOP_LOSS / TRAILING_SL / TARGET / SQUARE_OFF
- DAILY_LOSS_LIMIT
- ORDER REJECTED / ERROR / FATAL

Install the ntfy app on phone and subscribe to the same topic name set in `.env`.

---

## Phase 13 — What Was Intentionally Deferred

| Item | Reason / Status |
|------|-----------------|
| Auto-deploy on `git push` | Image builds on GHCR; server still needs manual `git pull` + `docker-compose up` unless a deploy workflow is added |
| Full ADX prior-daily history | Minimal stub in first version; ADX becomes more reliable after history accumulates |
| Reserved IP before first SSH | Deferred then completed; final IP `80.225.255.207` |
| `LIVE_TRADING=true` | Kept false until paper day observed |
| NSE holiday calendar | Weekends only; user maintains extra holidays |

---

## Complete Command Timeline (Compact)

```text
# Laptop — Git
git init
git branch -M main
git add .
git commit -m "Initial ORB live trading system"
git remote add origin https://github.com/Mritunjay2005/orb_live_trading.git
git push -u origin main

# Laptop — Terraform
cd infra/terraform
cp terraform.tfvars.example terraform.tfvars   # fill values
terraform init
terraform plan
terraform apply   # yes

# OCI Console
# Convert/assign Reserved Public IP → 80.225.255.207
# Whitelist 80.225.255.207 in Upstox

# Laptop — SSH
ssh -i ~/.ssh/id_ed25519 ubuntu@80.225.255.207

# Server — app setup
cd /opt/orb_live_trading
sudo chown -R $USER:$USER /opt/orb_live_trading
git clone https://github.com/Mritunjay2005/orb_live_trading.git .
cp .env.example .env && nano .env
sudo usermod -aG docker $USER && newgrp docker
docker-compose up -d
# Grafana failed → fix provisioning dirs + volumes
docker rm -f ...grafana...
docker-compose up -d --no-deps grafana
docker-compose ps
docker-compose logs --tail=50 trading
curl -s http://localhost:8000/metrics | head
```

---

**End of extended log (Prometheus + monitoring + full timeline)**
