# Algo Trading Stack — Oracle Cloud (2 OCPU / 12GB) + Upstox + Dhan

Microservice architecture:

```
                     ┌───────────────┐
   Upstox (data) ───►│               │
                     │ execution-gate│◄─── algo-pod-1 (independent, own strategy+instruments)
   Dhan (orders) ───►│               │◄─── algo-pod-2
                     └───────┬───────┘◄─── algo-pod-3 (profile: full)
                             │ logs every req/response       ◄─── algo-pod-4 (profile: full)
                             ▼
                     ┌───────────────┐        end-of-session
                     │ queue-service │───────► notifier ──► ntfy.sh (full detail)
                     │ (Redis ledger)│                  └─► Telegram (summary)
                     └───────┬───────┘
                             │
                     ┌───────▼───────┐      ┌────────────┐
                     │  dashboard    │      │ Prometheus │
                     │ (OTP login)   │      │ + Grafana  │
                     └───────────────┘      │ + cAdvisor │
                                             │ + node-exp │
                                             └────────────┘
       all fronted by Caddy (reverse proxy, ports 80/443)
```

**Design decisions worth knowing:**
- Upstox = market data/analysis, Dhan = order placement, both configurable per-call via `DATA_PROVIDER`/`ORDER_PROVIDER` in `.env` — swap either independently.
- Algo pods talk to `execution-gate` directly (low latency); `execution-gate` fire-and-forgets a copy of every request/response to `queue-service` so nothing trading-critical waits on logging.
- `algo-pod-3` and `algo-pod-4` are behind the `full` Compose profile so a fresh 12GB box isn't overloaded by default — enable them once you've confirmed pods 1–2 are stable.

## 0. Prerequisites (you said these are ready)
- Oracle Cloud account + API key (tenancy OCID, user OCID, fingerprint, private key path, compartment OCID).
- A GitHub repo to push this into.
- Upstox API key/secret + access token, Dhan client ID + access token.
- A Gmail account + an **App Password** (not your normal password) for OTP emails: Google Account → Security → 2-Step Verification → App Passwords.
- Optional: an ntfy.sh topic name (just make one up, keep it private), a Telegram bot token (via @BotFather) and your chat ID.

## 1. Push this repo to GitHub
```bash
cd trading-setup
git init
git add .
git commit -m "Initial trading stack scaffold"
git branch -M main
git remote add origin https://github.com/YOUR_USERNAME/YOUR_REPO.git
git push -u origin main
```
Update `terraform/variables.tf`'s `git_repo_url` default (or pass `-var`) to point at this repo — the instance clones it on boot.

## 2. Add GitHub Actions secrets
Repo → Settings → Secrets and variables → Actions → New repository secret:
- `OCI_HOST` — the instance's public IP (from `terraform output public_ip` after step 3)
- `OCI_USER` — `ubuntu`
- `OCI_SSH_PRIVATE_KEY` — the private key matching the public key Terraform installed

## 3. Provision the Oracle Cloud instance with Terraform
```bash
cd terraform
terraform init
terraform apply \
  -var="tenancy_ocid=<your_tenancy_ocid>" \
  -var="user_ocid=<your_user_ocid>" \
  -var="fingerprint=<your_api_key_fingerprint>" \
  -var="private_key_path=~/.oci/oci_api_key.pem" \
  -var="compartment_ocid=<your_compartment_ocid>" \
  -var="git_repo_url=https://github.com/YOUR_USERNAME/YOUR_REPO.git"
```
It will output `public_ip`. **Before this is production-safe**, edit `terraform/main.tf`'s security list and change the `0.0.0.0/0` source on port 22 to your own `<your-ip>/32`.

## 4. First-time setup on the instance
```bash
ssh ubuntu@<public_ip>
cd /opt/trading
cp .env.example .env
nano .env   # fill in every value: Upstox, Dhan, ntfy, Telegram, Gmail app password, Grafana password, JWT secret
docker compose up -d --build
docker compose ps
```

## 5. Point a domain at it (for real HTTPS on the dashboard)
Free option: use a free DNS subdomain (DuckDNS, or `<public_ip>.nip.io`) pointing at the instance's public IP, then edit `Caddyfile` to use that domain instead of `:80`, and run `docker compose up -d caddy`. Until you do this, the dashboard is reachable at `http://<public_ip>/` (no TLS) — fine for testing, not for sharing with strangers.

## 6. Adding your real strategy
Drop your backtested file's core logic into a new file under `algo-pod/strategies/`, following the pattern in `example_strategy.py`:
- Keep your indicator math and entry/exit thresholds exactly as they were.
- Wrap the signal-generation part in a class `Strategy(StrategyAdapter)` with `on_bar(self, candles: pd.DataFrame) -> list[Signal]`.
- If your original strategy is a `backtrader.Strategy`, port the body of `next()` into `on_bar()` (see the docstring in `algo-pod/app/strategy_adapter.py` for the two porting paths). Upload your file here (or attach it in chat) and I'll do the port for you exactly as-is.

Wire it into a pod and ship it:
```bash
# locally, then push to GitHub (CI/CD deploys automatically):
# edit docker-compose.yml -> algo-pod-N -> STRATEGY_MODULE=strategies.your_new_file
git add . && git commit -m "Add strategy X to pod N" && git push
```
Or add a brand-new 5th+ pod without touching existing ones:
```bash
./scripts/add_algo.sh 5 strategies.your_new_file "NSE_EQ:TCS"
git add . && git commit -m "Add algo-pod-5" && git push
```
CI/CD (GitHub Actions) then builds and SSHes into the box to redeploy automatically on every push to `main`.

## 7. Manual deploy (without CI/CD) on the box
```bash
cd /opt/trading && ./scripts/deploy.sh
```

## 8. Enable pods 3 & 4
```bash
docker compose --profile full up -d --build
```

## 9. Daily risk reset
Before market open each day, reset the PnL/position counters (cron on the box, or a scheduled GitHub Action hitting the endpoint):
```bash
curl -X POST http://localhost:8002/risk/reset-daily   # from inside the box (queue-service is not publicly exposed)
```

## 10. End-of-session notifications
Trigger manually or via cron at market close:
```bash
curl -X POST http://localhost:8002/session/close
```
This sends the full-detail message to your ntfy topic and the reduced summary (instrument/position/time only) to Telegram.

## 11. Dashboards
- **Public/shareable, read-only:** `http://<domain-or-ip>/` — OTP-gated (any email can request a code; it only proves the person can read that inbox, it doesn't authorize trading actions — the page is display-only, no API keys or full account balances are ever rendered).
- **Grafana** (infra health: CPU/RAM/disk per container, API connectivity): `http://<domain-or-ip>/grafana/` — log in with `admin` / the `GRAFANA_ADMIN_PASSWORD` you set, then import community dashboards **Node Exporter Full (ID 1860)** and **cAdvisor (ID 14282)**; the Prometheus datasource is already provisioned.

## Safety notes (please actually read these)
- Start with `KILL_SWITCH=true` in `.env` and everything else fully configured; flip to `false` only once you've watched a full session with paper/small-size orders.
- `MAX_DAILY_LOSS_INR` and `MAX_OPEN_POSITIONS` in `.env` are enforced in `execution-gate` before any order reaches Dhan — tune these to your actual risk tolerance, not the defaults.
- Never commit `.env` (it's gitignored) — rotate any key you accidentally push immediately.
- This scaffold is infrastructure, not a guarantee of profitability or correctness of any trading logic — test thoroughly with small size before scaling capital.
