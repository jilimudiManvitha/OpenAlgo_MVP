# OpenAlgo — Deployment Guide

**Applies to:** this repository (`openalo_indian_markets_mvp`, a fork of `marketcalls/openalgo`)
**Written:** 2026-09-29
**For:** the GitHub Student Developer Pack benefits listed at the end of this file.

OpenAlgo is a self-hosted algo-trading server. It holds live broker credentials, an
encrypted token store, a live order-placement API and a streaming WebSocket feed.
Deploying it is not the same problem as deploying a blog. This guide is ordered so
you read the decision table, pick a target, then follow only that section.

---

## Table of contents

1. [What you are actually deploying](#1-what-you-are-actually-deploying)
2. [Pre-flight checklist](#2-pre-flight-checklist)
3. [Choosing a target](#3-choosing-a-target)
4. [Secrets you must generate before anything else](#4-secrets-you-must-generate-before-anything-else)
5. [Option A — VPS + Docker + Caddy (recommended)](#5-option-a--vps--docker--caddy-recommended)
6. [Option B — This PC + Cloudflare Tunnel (free, no VPS)](#6-option-b--this-pc--cloudflare-tunnel-free-no-vps)
7. [Option C — Railway / Render](#7-option-c--railway--render)
8. [Option D — Heroku (student credit)](#8-option-d--heroku-student-credit)
9. [Option E — Microsoft Azure (student credit)](#9-option-e--microsoft-azure-student-credit)
10. [Domain and TLS from the student pack](#10-domain-and-tls-from-the-student-pack)
11. [Security](#11-security)
12. [Data, databases and backups](#12-data-databases-and-backups)
13. [Post-deploy verification](#13-post-deploy-verification)
14. [Updates and rollback](#14-updates-and-rollback)
15. [Troubleshooting](#15-troubleshooting)
16. [Cloud environment variable reference](#16-cloud-environment-variable-reference)
17. [Student Pack benefits used here](#17-student-pack-benefits-used-here)

---

## 1. What you are actually deploying

Read this before choosing a platform. Several popular PaaS options cannot host this
app correctly, and it is much cheaper to know that now.

### 1.1 Processes

One container runs **two** network services:

| Service | Port | Started by | Notes |
|---|---|---|---|
| Gunicorn + eventlet (`app:app`) | `5000` (or `$PORT` on PaaS) | `start.sh` | REST API, web UI, broker adapters, scheduler |
| `websocket_proxy.server` | `8765` | `start.sh` | Live tick/quotes feed for the UI and SDK |
| ZeroMQ bus (`ZMQ`) | `5555` | broker adapters | **Internal only.** Never expose it. |

`start.sh` binds gunicorn to `0.0.0.0:${PORT:-5000}`. On any PaaS that injects
`$PORT`, the Flask app moves to that port automatically — the WebSocket proxy on
`8765` does not.

**This is the single most important constraint in this document.** The WebSocket
proxy is a bare `websockets` server (`websocket_proxy/server.py`) that binds a
`host:port` and has no HTTP router and no path multiplexing. PaaS platforms route
traffic to exactly **one** port. If you deploy to Railway, Render, Heroku or Azure
App Service, you get exactly one public HTTPS endpoint, and the live market feed
will not be reachable on it.

Options for PaaS, in order of effort:

1. **A second PaaS service on a second hostname** running only
   `python -m websocket_proxy.server`, pointed at the same Postgres and the same
   `.env`. Set `WEBSOCKET_URL = 'wss://<ws-hostname>'`. Works, costs a second
   dyno, and the two services must be kept in lockstep.
2. **Skip the streaming UI.** The REST API, scanner, strategies, Flow, charting and
   backtesting all work over plain HTTPS on `$PORT`. Only the live tick view in
   `/trading` breaks. Acceptable for a first deployment.
3. **Don't use PaaS.** Options A and B both give you both ports on one hostname
   with path routing (`/ws`), which is what the app is actually built for.

### 1.2 Persistent state

| Path | Contents | Loses it → |
|---|---|---|
| `db/*.db` | SQLite: auth/users, tokens, settings, watchlists, scanner, logs, health, sandbox | Full re-login, all settings gone |
| `db/historify.duckdb` | Historify historical candles | All downloaded history |
| `keys/` | Broker API certificates, Fernet key material (`chmod 700`) | Re-login with broker, re-upload certs |
| `strategies/` | Your Python strategy scripts | Strategies gone |
| `log/` | Application and strategy logs | Diagnostics only |

`db/` and `keys/` on a PaaS are on an **ephemeral** filesystem. Every redeploy,
every dyno cycle, every crash-restart wipes them. `keys/` is the killer: broker
logins encrypt a token with a key derived from `API_KEY_PEPPER` + `FERNET_SALT`,
and a wiped `keys/` plus a wiped `db/` means re-authenticating with the broker by
hand.

### 1.3 What is already in the repo

- `Dockerfile` — 3-stage build: `uv` venv from `pyproject.toml`, `npm ci` +
  `npm run build` for the frontend, then a slim runtime with Chromium (needed by
  Kaleido for Telegram chart export). Runs as non-root `appuser` (UID/GID 1000).
- `docker-compose.yaml` — ports 5000 + 8765, named volumes for `db`, `log`,
  `strategies`, `keys`, `tmp`, and a **bind mount of `./.env`**.
- `start.sh` — auto-generates `.env` from environment variables when `HOST_SERVER`
  is set (the cloud path), runs `upgrade/migrate_all.py`, starts the WebSocket
  proxy, then execs gunicorn.
- `install/install-docker.sh` — the official Ubuntu+nginx+certbot installer. It
  publishes the container on `127.0.0.1` only and terminates TLS in nginx. This is
  a supported path; Option A below is the Caddy equivalent.
- `Caddyfile` — a local dev stub (`openalgo.local → localhost:5000`), not a
  production config.

Build times: expect **6–12 minutes** for the first Docker build. Pushed to
Railway/Render this is a cold build every time you change a dependency.

---

## 2. Pre-flight checklist

Do not start a deploy until every line is true.

- [ ] **Broker API key + secret** in hand, and the broker's redirect URL whitelist
      updated to your deployment's `/<broker>/callback` path.
- [ ] **`APP_KEY`, `API_KEY_PEPPER`, `FERNET_SALT`** generated (§4) and stored in a
      password manager (1Password is free for a year via the student pack).
- [ ] **A domain** pointing wherever you are deploying (§10).
- [ ] **You know which instance this is.** A throwaway sandbox/analyzer instance
      and a live-money instance must never share a database, a `.env`, or a
      domain. OpenAlgo has a sandbox mode, but the safe boundary is separate
      deployments.
- [ ] **A backup plan** (§12) — written down before the first broker login.
- [ ] **Decided who can reach it.** This is a money-moving API. Default to
      VPN-only or Cloudflare Access, not "public with a strong password".

---

## 3. Choosing a target

| | **A. VPS + Docker + Caddy** | **B. PC + Cloudflare Tunnel** | **C. Railway / Render** | **D. Heroku** | **E. Azure** |
|---|---|---|---|---|---|
| Cost | ~€5.5–12/mo (Hetzner CX23 or a Mumbai-region VPS) | $0 | $5–20/mo usage | $13/mo credit, 24 mo | $100 credit, 12 mo |
| Live WebSocket feed (8765) | ✅ same host, `/ws` | ✅ tunneled | ⚠️ 2nd service or broken | ⚠️ 2nd app or broken | ⚠️ 2nd app or broken |
| Persistent `db/` + `keys/` | ✅ named volumes | ✅ local disk | ❌ ephemeral → need Postgres | ❌ ephemeral | ❌ → Azure Files / Postgres |
| Historify DuckDB history | ✅ | ✅ | ❌ | ❌ | ❌ |
| Strategies on disk | ✅ | ✅ | ❌ | ❌ | ❌ |
| Broker streaming uptime | ✅ 24/7 | ⚠️ PC must stay awake, no sleep | ✅ | ✅ | ✅ |
| Latency to broker | ✅ same region as broker | ⚠️ your ISP | ✅ pick region | ❌ dyno region (US/EU) | ✅ pick region |
| Setup effort | Medium | Low | Low | Medium | High |
| **Verdict** | **Use this** | Good for a trial / backup instance | Fine for a read-only demo | Demo only | Overkill |

For a real-money instance with active strategies and Historify history, **Option A
is the only one of these that works without compromises.** Options C, D and E all
force you to abandon the streaming feed or the local state that this fork's
scanner and backtest work depends on.

### Indian-broker latency note

Choose a VPS region near your broker's servers — **Mumbai (ap-south-1)** for most
NSE/BSE brokers. The app has `BROKER_CONNECTION_KEEPALIVE` on by default, which
keeps the pooled HTTP connection warm only inside `BROKER_KEEPALIVE_WINDOW`
(`09:00–23:30` IST). Outside that window the first order of the day pays a fresh
TLS handshake. A US or EU VPS puts a double round trip on every order fill check.

This creates a real trade-off, because **the cheapest hosts have no Indian
region**: Hetzner's CX line is Germany/Finland only, and DigitalOcean and Vultr
put Mumbai at 3–4× the price of the EU equivalent. If broker latency matters to
your strategy — it does for anything scalping, options or intraday — pay for
Lightsail Mumbai. If you are running end-of-day or 15-minute strategies, the
Hetzner Helsinki route is fine and roughly €7/mo cheaper.

---

## 4. Secrets you must generate before anything else

Three independent values. Generate them once, per deployment, and never change
them for a database that already has users in it.

```powershell
# PowerShell — run in the project root
python -c "import secrets; print('APP_KEY          =', secrets.token_hex(32))"
python -c "import secrets; print('API_KEY_PEPPER   =', secrets.token_hex(32))"
python -c "import secrets; print('FERNET_SALT      =', secrets.token_hex(32))"
```

```bash
# Linux/macOS
for k in APP_KEY API_KEY_PEPPER FERNET_SALT; do
  echo "$k = $(python3 -c 'import secrets; print(secrets.token_hex(32))')"
done
```

| Variable | What it protects | Rotatable after you have users? |
|---|---|---|
| `APP_KEY` | Flask session cookies, CSRF tokens | Yes — invalidates browser sessions, nothing else |
| `API_KEY_PEPPER` | Argon2 password hashes, Fernet KDF for broker tokens, TradingView API key hashing | **No.** See below |
| `FERNET_SALT` | Second input to the Fernet KDF that encrypts stored broker auth/feed tokens | **No** — same blast radius |

### Why `API_KEY_PEPPER` and `FERNET_SALT` must be pinned

`start.sh` contains a pre-flight block that **refuses to boot** if it finds the
publicly-known sample values shipped in `.sample.env`, because the in-app
auto-rotation cannot write back to a read-only `.env`. The same reasoning applies
to you: the app degrades to a *legacy* salt derivation (it logs
`[auth_db] WARNING: FERNET_SALT not set or invalid`) when `FERNET_SALT` is unset.
On a container platform where `/app/.env` is a read-only mount, that warning is
permanent and the derivation is weaker than intended.

**Set all three explicitly as environment variables on every PaaS target.**
`start.sh` copies them into the generated `.env`, and setting them means the
values survive restarts instead of being regenerated per-container.

If you have already got users or a connected broker:

- **Never** rotate `API_KEY_PEPPER` by hand. It invalidates every stored password
  hash and every encrypted broker token, irreversibly.
- Use the dedicated migration, which re-encrypts and resets passwords:
  `uv run python upgrade/rotate_pepper.py`
- `APP_KEY` is safe to rotate whenever you like; it only logs people out.

---

## 5. Option A — VPS + Docker + Caddy (recommended)

### 5.1 Provision

Any Ubuntu 24.04 VPS works. For this app: **2 vCPU, 4 GB RAM, 40 GB disk** minimum.
The build itself needs ~4 GB to run `npm ci` and `uv sync` in parallel.

#### Where to buy it

| Provider | Plan | Specs | Region | Indicative cost |
|---|---|---|---|---|
| **Hetzner** (Hetzner Online GmbH, Germany) | **CX23** — the current cost-optimized line | 2 shared vCPU, 4 GB, 40 GB SSD, 20 TB transfer | **Germany / Finland only** | ~€5.49/mo excl. IPv4 |
| AWS Lightsail | Linux, 2 vCPU / 4 GB bundle | 2 vCPU, 4 GB, 80 GB SSD | **Mumbai (ap-south-1)** available | ~$12/mo |
| DigitalOcean | Basic Droplet | 2 vCPU, 4 GB, 80 GB SSD | **Mumbai (blr1)** available | ~$24/mo |
| Vultr | Cloud Compute | 2 vCPU, 4 GB | **Mumbai** available | ~$24/mo |
| Oracle Cloud | Always Free Ampere A1 | up to 4 OCPU / 24 GB | Mumbai — **capacity is almost always exhausted** | $0 if you can get one |

Notes on each:

- **Hetzner CX23.** The `CX22` plan is deprecated and no longer offered. `CX23`
  replaced it and the whole line was repriced on **2026-06-15** (CX23 went from
  €3.99 to €5.49/mo excluding IPv4, add ~€1 for a public IPv4). The CX line is
  shared/burstable vCPU and is offered **only in Germany (Nuremberg, Falkenstein)
  and Finland (Helsinki)** — there is no Mumbai or Singapore location, and the
  US/Hillsboro location costs roughly 20% more. Because of the missing Indian
  region, treat Hetzner as the *budget* option, not the *latency* option.
- **Hetzner payment.** Credit card (VISA / Mastercard / AMEX / **UnionPay**),
  PayPal, or SEPA / bank transfer. No UPI, no crypto, and Apple Pay or any
  wallet linked to a card is rejected. A UnionPay debit card works but is
  **not** auto-charged — you must pay the invoice manually, and a late invoice
  escalates to wire transfer only.
- **Lightsail Mumbai** is the pragmatic pick if you want both a real Indian
  region and a predictable bill. It is the only Mumbai option here that is not
  $24/mo.
- **Oracle Always Free** is genuinely free and Ampere A1 is fast, but Mumbai
  free-tier capacity is rationed almost to zero. Check before planning around it.

Verify current prices in the provider's console before you commit — they move,
and Hetzner has just changed them twice.

```bash
adduser openalgo
usermod -aG sudo openalgo
```

SSH in, then hardenable the box before doing anything else:

```bash
sudo apt update && sudo apt -y upgrade
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow 22/tcp      # SSH
sudo ufw allow 80/tcp      # ACME challenge + HTTP redirect
sudo ufw allow 443/tcp     # HTTPS
sudo ufw --force enable

# key-only SSH
sudo sed -i 's/^#\?PermitRootLogin.*/PermitRootLogin no/' /etc/ssh/sshd_config
sudo sed -i 's/^#\?PasswordAuthentication.*/PasswordAuthentication no/' /etc/ssh/sshd_config
sudo systemctl restart ssh

sudo apt install -y git curl ca-certificates
```

**Ports 5000, 8765 and 5555 stay closed.** They are reached over the loopback
interface through Caddy.

### 5.2 Clone and build

```bash
git clone https://github.com/Narasimha722/openalo_indian_markets_mvp.git
cd openalo_indian_markets_mvp
cp .sample.env .env
```

Build the image from **your** source. `install/docker-run.sh` pulls
`marketcalls/openalgo:latest` from Docker Hub, which does **not** contain this
fork's scanner, backtest and strategy work.

```bash
docker build -t openalgo:latest .
```

Expect 6–12 minutes. To speed up repeat builds, add a BuildKit cache mount to the
`uv sync` layer in `Dockerfile` — worth doing once you start iterating.

### 5.3 Configure `.env`

```bash
nano .env
```

Minimum changes to `.sample.env`:

```ini
ENV_CONFIG_VERSION = '1.0.7'

# --- Secrets from §4 -----------------------------------------------------
APP_KEY       = '<64 hex chars>'
API_KEY_PEPPER = '<64 hex chars>'
FERNET_SALT   = '<64 hex chars>'

# --- Broker -------------------------------------------------------------
VALID_BROKERS  = 'fyers'                      # or dhan, zerodha, upstox, deltaexchange, ...
BROKER_API_KEY     = 'your_key'
BROKER_API_SECRET  = 'your_secret'
REDIRECT_URL  = 'https://trade.example.com/fyers/callback'

# --- Public identity ----------------------------------------------------
HOST_SERVER   = 'https://trade.example.com'
CORS_ALLOWED_ORIGINS = 'https://trade.example.com'
CSP_UPGRADE_INSECURE_REQUESTS = 'TRUE'

# --- Flask / proxy ------------------------------------------------------
FLASK_ENV     = 'production'
FLASK_DEBUG   = 'False'                      # hard-refused on a non-loopback bind, never enable
FLASK_HOST_IP = '0.0.0.0'                    # so the container is reachable from Caddy
FLASK_PORT    = '5000'
WEBSOCKET_HOST = '0.0.0.0'
WEBSOCKET_PORT = '8765'
WEBSOCKET_URL  = 'wss://trade.example.com/ws'

# --- Security -----------------------------------------------------------
TRUST_PROXY_HEADERS = 'TRUE'                 # Caddy is in front: set this
DISABLE_SESSION_EXPIRY = 'false'             # 'true' for 24/7 crypto brokers
LOGIN_RATE_LIMIT_MIN  = '5 per minute'
LOGIN_RATE_LIMIT_HOUR = '25 per hour'

# --- Resources (2–4 GB box) --------------------------------------------
STRATEGY_MEMORY_LIMIT_MB = '512'
SHM_SIZE = '512m'
```

Two things people get wrong here:

- `TRUST_PROXY_HEADERS = 'TRUE'` is correct **because Caddy is in front**, so
  `X-Forwarded-For` and `CF-Connecting-IP` come from your proxy. It makes the
  login rate limiter and IP ban list see the real client. Leave it `FALSE` and
  every client looks like `127.0.0.1` — one attacker gets everyone's rate limit.
- `FLASK_HOST_IP = '0.0.0.0'` inside the container. The container is only
  published on `127.0.0.1` by compose, so this is not an exposure; it is what
  lets the host's Caddy reach it.

Also set ownership. `docker-compose.yaml` bind-mounts `./.env`, and the container
runs as UID 1000. If the file is not owned by UID 1000 the app cannot rotate
`FERNET_SALT` and you get the pre-flight crash loop from §4.

```bash
sudo chown 1000:1000 .env
sudo chmod 600 .env
```

### 5.4 Start

```bash
docker compose up -d
docker compose logs -f --tail=100      # first run: migrations, then gunicorn
```

Verify the container is healthy before touching DNS:

```bash
curl -fsS http://127.0.0.1:5000/auth/check-setup
```

### 5.5 Caddy as the TLS terminator

Caddy gets Let's Encrypt certificates automatically and handles the WebSocket
upgrade with no extra directives. Install:

```bash
sudo apt install -y debian-keyring debian-archive-keyring apt-transport-https
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' \
  | sudo gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' \
  | sudo tee /etc/apt/sources.list.d/caddy-stable.list
sudo apt update && sudo apt install -y caddy
```

`/etc/caddy/Caddyfile`:

```caddyfile
trade.example.com {
    encode zstd gzip

    # Never log webhook URLs — they carry credentials in the path.
    log {
        output file /var/log/caddy/access.log
        format json
    }

    # Live market data feed.
    handle /ws {
        reverse_proxy 127.0.0.1:8765 {
            flush_interval -1        # stream ticks immediately, no buffering
        }
    }

    handle {
        reverse_proxy 127.0.0.1:5000 {
            flush_interval -1        # required for Server-Sent Events
        }
    }

    header {
        Strict-Transport-Security "max-age=63072000; includeSubDomains; preload"
        X-Content-Type-Options    "nosniff"
        Referrer-Policy           "strict-origin-when-cross-origin"
        -Server
    }

    request_body {
        max_size 100MB
    }
}
```

`flush_interval -1` is not optional. Without it Caddy coalesces response chunks
and the streaming endpoints (quotes, scanner progress, log tails) arrive in
bursts or stall entirely.

```bash
sudo caddy validate --config /etc/caddy/Caddyfile
sudo systemctl reload caddy
sudo systemctl status caddy
```

If ACME issuance fails, confirm DNS A/AAAA already resolves to this host and that
ports 80/443 are open. Caddy retries automatically, but fix DNS first.

### 5.6 Nginx instead of Caddy

The official installer uses nginx + certbot. If you would rather use the
supported path, `sudo bash install/install-docker.sh` writes the whole vhost for
you — including the `set $openalgo_loggable 0` guard that keeps webhook
credentials out of the access log, and `proxy_read_timeout 86400s` on the
`/ws` locations. Reuse those two ideas if you hand-write a Caddyfile as above.

### 5.7 Post-install hardening

```bash
# Fail2ban
sudo apt install -y fail2ban
sudo systemctl enable --now fail2ban

# unattended security upgrades
sudo apt install -y unattended-upgrades
sudo dpkg-reconfigure -plow unattended-upgrades

# swap, if the box has 2 GB
sudo fallocate -l 2G /swapfile && sudo chmod 600 /swapfile
sudo mkswap /swapfile && sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
```

---

## 6. Option B — This PC + Cloudflare Tunnel (free, no VPS)

Runs OpenAlgo on this Windows machine and publishes it through a Cloudflare
Tunnel. No inbound firewall hole, no public IP, free automatic TLS. `.cloudflared/`
in this repo already has the scaffolding and a template `config.yml`.

**Use this for:** a trial instance, a read-only analytics/monitoring copy, or a
backup target. Not for a 24/7 money-moving instance, because this PC sleeps and
loses power.

### 6.1 Install cloudflared

```powershell
winget install Cloudflare.cloudflared
cloudflared --version
```

### 6.2 Named tunnel (with your own domain)

Requires a domain on your Cloudflare account (see §10). If you only have a
`trycloudflare.com` quick tunnel, skip to §6.4.

```powershell
cloudflared tunnel login
cloudflared tunnel create openalgo
```

`cloudflared tunnel list` prints the credentials file path. Write
`.cloudflared/config.yml`:

```yaml
tunnel: openalgo
credentials-file: C:\Users\<you>\.cloudflared\<TUNNEL-ID>.json

ingress:
  - hostname: trade.example.com
    path: ^/ws
    service: http://127.0.0.1:8765
  - hostname: trade.example.com
    service: http://127.0.0.1:5000
  - service: http_status:404
```

> The tunnel credential JSON is a secret. It is already git-ignored. Never commit
> it, and never paste it into a chat or an issue.

DNS record (auto-created by the command below, or add it by hand):

```powershell
cloudflared tunnel route dns openalgo trade.example.com
```

### 6.3 `.env` for tunnel mode

Tunnel mode is materially different from the VPS in two places:

```ini
HOST_SERVER   = 'https://trade.example.com'
FLASK_HOST_IP = '127.0.0.1'     # loopback is fine — cloudflared is on this host
TRUST_PROXY_HEADERS = 'TRUE'    # cloudflared injects CF-Connecting-IP / X-Forwarded-For
CSP_UPGRADE_INSECURE_REQUESTS = 'TRUE'
WEBSOCKET_URL = 'wss://trade.example.com/ws'
CSP_CONNECT_SRC = "'self' wss://trade.example.com wss: ws: https://cdn.socket.io"
REDIRECT_URL   = 'https://trade.example.com/fyers/callback'
```

`CSP_CONNECT_SRC` must name your own host explicitly. The stock value in
`.sample.env` allows `wss:` (any host), so the UI works out of the box — but
tightening it to your domain costs nothing and closes a hole.

Run as a Windows service so it survives reboots and logouts:

```powershell
# Requires an elevated PowerShell prompt
cloudflared service install
Set-Service -Name cloudflared -StartupType Automatic
```

### 6.4 Quick tunnel (no domain, throwaway)

```powershell
cloudflared tunnel --url http://127.0.0.1:5000
```

Prints a `https://random-words.trycloudflare.com` URL. The hostname changes on
every restart, so `REDIRECT_URL`, `HOST_SERVER` and the broker's redirect
whitelist all have to be edited each time. Fine for an afternoon of testing,
useless as a deployment.

### 6.5 Keep the PC awake

```powershell
# Prevent sleep while plugged in
powercfg /change standby-timeout-ac 0
powercfg /change hibernate-timeout-ac 0

# Also disable the "sleep when the laptop lid closes" lid action (0 = do nothing)
powercfg /setacvalueindex scheme_current sub_buttons lidaction 0
powercfg /setactive scheme_current
```

---

## 7. Option C — Railway / Render

Both build `Dockerfile` from your GitHub repo. The current remote is
`github.com/Narasimha722/openalo_indian_markets_mvp`.

### 7.1 Known limitations (decide before you start)

1. **Ephemeral filesystem.** `db/`, `keys/` and `strategies/` are wiped on every
   deploy and every restart. You must move the SQL databases to Postgres and
   accept losing `keys/` (re-login with the broker) and the DuckDB Historify
   store.
2. **One public port.** The WebSocket feed is not reachable without a second
   service. See §1.1.
3. **Cold builds.** 6–12 minutes. Every dependency bump is a long build.
4. **Region.** Pick Mumbai if offered; otherwise the extra RTT applies to every
   broker call.

### 7.2 What `DATABASE_URL` can and cannot move

Most of the app's SQLAlchemy modules read `DATABASE_URL` and pool normally on
Postgres (`database/action_center_db.py`, `analyzer_db.py`, `apilog_db.py`, …).
But **not everything is configurable**:

| Database | Configurable | Notes |
|---|---|---|
| `openalgo.db` (auth, users, settings, tokens) | `DATABASE_URL` | Yes → Postgres |
| `logs.db` | `LOGS_DATABASE_URL` | Yes |
| `latency.db` | `LATENCY_DATABASE_URL` | Yes |
| `health.db` | `HEALTH_DATABASE_URL` | Yes |
| `sandbox.db` | `SANDBOX_DATABASE_URL` | Yes |
| `market_scanner_live.db` | **No** — hardcoded `sqlite:///` in `database/market_scanner_db.py:25` | Lost on every restart |
| `historify.duckdb` | **No** — `HISTORIFY_DATABASE_PATH` defaults to `db/historify.duckdb` | Historify is unavailable on PaaS |

A Postgres URL looks like:

```
postgresql://user:password@host:5432/dbname?sslmode=require
```

`DATABASE_URL` and the others point at the **same** database. `start.sh` runs
`upgrade/migrate_all.py` on every boot, so schema changes are applied
automatically — make sure the managed Postgres allows connections from the
platform before the first deploy or migrations will fail and the container will
crash-loop.

### 7.3 Railway

```bash
npm i -g @railway/cli
railway login
railway link
railway add --database postgres
railway variables set \
  HOST_SERVER="https://openalgo-production.up.railway.app" \
  REDIRECT_URL="https://openalgo-production.up.railway.app/fyers/callback" \
  APP_KEY="<64 hex>" \
  API_KEY_PEPPER="<64 hex>" \
  FERNET_SALT="<64 hex>" \
  VALID_BROKERS="fyers" \
  BROKER_API_KEY="..." \
  BROKER_API_SECRET="..." \
  TRUST_PROXY_HEADERS="TRUE" \
  FLASK_ENV="production" \
  FLASK_DEBUG="False" \
  CSP_UPGRADE_INSECURE_REQUESTS="TRUE"
railway up
```

Railway injects `PORT` and `RAILWAY_PUBLIC_DOMAIN`; `start.sh` sees `HOST_SERVER`
and generates `/app/.env` from these variables on first boot. That generated file
is `ENV_CONFIG_VERSION 1.0.4` and omits several keys that `.sample.env` now
carries (for example `DISABLE_SESSION_EXPIRY`, `ORDER_UPDATES_ENABLED`, the
`BROKER_KEEPALIVE_*` group). **Diff the generated `.env` against `.sample.env`
after the first deploy** and set anything missing as a platform variable.

Healthcheck path: `/auth/check-setup`.

### 7.4 Render

| Setting | Value |
|---|---|
| Type | Web Service |
| Environment | Docker |
| Branch | your deploy branch (see below) |
| Health check path | `/auth/check-setup` |
| Region | Mumbai / Singapore if offered |
| Instance | ≥ 2 GB RAM, ≥ 1 GB disk |

Render injects `PORT` and provides `RENDER_EXTERNAL_HOSTNAME`. The Docker
runtime is used automatically because a `Dockerfile` is present.

**Do not deploy `main` directly.** This branch carries the six-task work, the
large backtest artifacts and the LFS candle data; every push would trigger a
12-minute rebuild. Create a dedicated branch:

```bash
git switch -c deploy/production
git push origin deploy/production
```

Point Render at `deploy/production`, and merge into it deliberately.

### 7.5 Second service for the WebSocket feed (optional)

On Railway, add a second service from the same repo with an override:

```dockerfile
# railway-ws.Dockerfile
FROM openalgo-base AS ws
USER root
CMD ["/app/.venv/bin/python", "-m", "websocket_proxy.server"]
```

The base image must be the same commit, and the two services must share
`DATABASE_URL` and the identical `API_KEY_PEPPER`/`FERNET_SALT` — the WS proxy
verifies API keys against the same auth database and derives the same Fernet key.
Give it its own hostname, then set `WEBSOCKET_URL = 'wss://<ws-host>'` on the
main service. Budget for a second instance's cost and one more thing to keep in
sync.

---

## 8. Option D — Heroku (student credit)

The student pack gives **$13/month for 24 months = $312 total**. Heroku has no
free tier, so the credit is applied against a paid plan.

```bash
heroku login
heroku create trade-openalgo
heroku addons:create heroku-postgresql:essential-0
heroku config:set \
  HOST_SERVER="https://trade-openalgo.herokuapp.com" \
  REDIRECT_URL="https://trade-openalgo.herokuapp.com/fyers/callback" \
  APP_KEY="$(python3 -c 'import secrets; print(secrets.token_hex(32))')" \
  API_KEY_PEPPER="$(python3 -c 'import secrets; print(secrets.token_hex(32))')" \
  FERNET_SALT="$(python3 -c 'import secrets; print(secrets.token_hex(32))')" \
  VALID_BROKERS="fyers" \
  BROKER_API_KEY="..." BROKER_API_SECRET="..." \
  TRUST_PROXY_HEADERS="TRUE" \
  CSP_UPGRADE_INSECURE_REQUESTS="TRUE"
heroku container:push web
heroku container:release web
```

### 8.1 Read this before you connect a real broker

- **No persistent filesystem, and no way to buy one.** `keys/` and `strategies/`
  disappear on every slug push and every dyno cycle. Broker session tokens are
  encrypted into `db/` — both are wiped, so you re-authenticate with the broker
  after every deploy. If the broker needs a manual approval step or a daily OTP,
  this becomes unusable.
- **Dyno region is US or EU.** Every broker API call crosses an ocean. Fyers and
  Zerodha will be slow and, on some brokers, will rate-limit or reject by source
  IP.
- **The `$PORT` restriction** in §1.1 applies. No path routing, one hostname.
- **A slug is ~2 GB.** Build and push time is minutes each time.

**Verdict:** use Heroku for a demo, a public read-only dashboard, or a strategy
sandbox that never touches real money. Do not run the live scanner + strategies +
Historify setup on it. If you have already spent the Azure or Heroku credit and
still need this app working properly, put the money into a $4–6/month VPS
(Option A) — it is a better deal than any of the PaaS options for this
particular application.

---

## 9. Option E — Microsoft Azure (student credit)

$100 credit, no card, 12 months. It is a large amount of money and Azure can
host this app, but the persistent-state problem is the hard part.

- **Compute:** Azure Container Apps (serverless, scales to zero) or App Service
  for Containers. Container Apps is the closest fit to the Dockerfile; pick the
  Mumbai region.
- **WebSocket:** same one-public-port problem. A second Container App running
  only `websocket_proxy.server` with its own FQDN is the clean answer.
- **Persistence:** Azure Files (SMB) mounted into the container. **Do not put
  SQLite on an SMB share** — SQLite requires POSIX advisory locks that SMB does
  not provide reliably, and you will get silent corruption. Either:
  - set the SQL databases to **Azure Database for PostgreSQL Flexible Server** via
    `DATABASE_URL` and friends, and accept losing `keys/` and `historify.duckdb`;
    or
  - use a managed disk (Premium SSD v2 with proper mount options) and keep SQLite
    local. More work, but preserves everything.
- **Credit caveat:** the $100 expires in 12 months and a Container App with
  always-on streaming plus a Postgres instance burns it faster than you expect.
  Set a budget alert on day one.

**Verdict:** worth using the credit for the *databases* and the free tier, but
for a container this stateful, a plain Linux VPS is simpler and cheaper.

---

## 10. Domain and TLS from the student pack

### 10.1 What you can get

| Offer | What you get | Use it for |
|---|---|---|
| Namecheap | 1 year `.me` free, 1 year free SSL | `.me` is a poor fit for a trading server; use it for a landing page |
| Name.com | 1 free domain/year, 25+ TLDs (`.live`, `.studio`, `.software`, `.app`, `.dev`) | **`.dev`/`.app` force HTTPS via HSTS preload** — a good default here |
| .TECH | 1 free `.tech` domain/year | Fine; avoid for anything user-facing |
| Cloudflare (free plan, not in the pack) | Free authoritative DNS + free edge TLS + tunnels | Required for Option B; free forever regardless of student status |

Two students-package details worth knowing:

- Namecheap's "free SSL" is a paid-certificate refund coupon, not a cert you
  install. If you use Caddy or certbot you do not need it at all — Let's Encrypt
  is free and automatic.
- Name.com's offer requires your account email to be unique or it will treat the
  request as a duplicate. Use a dedicated email if you hit that.

`.app` and `.dev` are on the HSTS preload list, so browsers force HTTPS even on
the first visit. That is strictly good for this app.

### 10.2 DNS records

**Option A (VPS)** — point the apex at the server:

| Type | Name | Value | TTL |
|---|---|---|---|
| A | `@` | `<vps-ip>` | 300 |
| AAAA | `@` | `<vps-ipv6>` (only if the VPS has routable IPv6) | 300 |
| CNAME | `ws` | `trade.example.com` | 300 |

Wait for propagation before running `certbot`/Caddy, or ACME will fail:

```bash
dig +short trade.example.com
curl -fsS https://ipinfo.io/ip   # must match
```

**Option B (Cloudflare Tunnel)** — nameservers for the domain must be on
Cloudflare first, then:

```powershell
cloudflared tunnel route dns openalgo trade.example.com
```

creates a CNAME to `<TUNNEL-ID>.cfargotunnel.com` automatically.

### 10.3 Update the broker redirect URL

The broker's console whitelists your callback. For a public deployment it becomes:

```
https://trade.example.com/<broker>/callback
```

e.g. `https://trade.example.com/fyers/callback`. This must match `REDIRECT_URL`
in `.env` **exactly**, including the scheme and trailing-slash behaviour. Get it
wrong and the OAuth round trip lands on a 404 and the tokens are never issued.

Some Indian brokers only accept **exact-match** redirect URLs and some reject
URLs with a path. If your broker refuses a sub-path, deploy on the apex domain.

---

## 11. Security

OpenAlgo's threat model is "an attacker on the internet can place real orders
with your broker". Everything below follows from that.

### 11.1 Never do these

| Don't | Why | Do instead |
|---|---|---|
| `FLASK_DEBUG='True'` on a public host | Werkzeug's debugger is a remote code execution primitive. The app hard-refuses this combination unless `FLASK_DEBUG_ALLOW_EXTERNAL='true'` | `FLASK_DEBUG='False'`, `FLASK_ENV='production'` |
| `ZMQ_HOST='0.0.0.0'` | Publishes the raw, unauthenticated tick feed to anyone who can reach the port. `db/__init__.py` tracks this as a critical audit finding | Keep `127.0.0.1`. It is an internal bus |
| Publish `5000`, `8765` or `5555` on a VPS | Bypasses TLS, your rate limits and every security header | Bind to `127.0.0.1` and front with Caddy/nginx |
| `TRUST_PROXY_HEADERS='TRUE'` with no proxy in front | Any client can spoof `X-Forwarded-For` and defeat the IP ban list and per-IP rate limits | Set it only when a real reverse proxy or Cloudflare sits in front |
| `CORS_ALLOWED_ORIGINS='*'` | Any website can call your API from a logged-in browser | Set it to `HOST_SERVER` exactly |
| Commit `.env`, `keys/`, or the tunnel credential JSON | Broker keys and the Fernet key material leak to Git history permanently | `.gitignore` already covers `.env`, `*.env`, `keys/`. Verify with `git log --all -- .env` before your first push to a new remote |
| `FLASK_HOST_IP='0.0.0.0'` on a bare-metal install with no firewall | Direct internet exposure of gunicorn | Loopback bind + reverse proxy |

### 11.2 Exposing it: prefer not to

Best to worst:

1. **Never leave the VPS on a public IP.** WireGuard/Tailscale, or a Cloudflare
   Tunnel from the VPS to the same domain. Nothing is publicly reachable.
2. **Cloudflare Access** (free, up to 50 users) in front of the hostname. The
   app's own login then sits behind an identity provider. This is the strongest
   option and costs nothing.
3. **IP allowlist at the firewall.** A static home IP works; most Indian ISPs
   use CGNAT so you may not have one.
4. **Long random password + TOTP + tight rate limits** and accept the risk.

Whichever you pick, the app's own controls still apply:

```ini
LOGIN_RATE_LIMIT_MIN  = '5 per minute'
LOGIN_RATE_LIMIT_HOUR = '25 per hour'
RESET_RATE_LIMIT      = '15 per hour'
SESSION_EXPIRY_TIME   = '03:00'          # daily forced logout, IST
DISABLE_SESSION_EXPIRY = 'false'
CSRF_ENABLED          = 'TRUE'
CSP_ENABLED           = 'TRUE'
CSP_UPGRADE_INSECURE_REQUESTS = 'TRUE'
```

For 24/7 crypto brokers (Delta Exchange) set `DISABLE_SESSION_EXPIRY = 'true'`,
otherwise you are logged out at 03:00 IST while holding positions.

### 11.3 Credential and key hygiene

- Put `.env` in **1Password** (free for a year via the student pack) or **Doppler**
  (free Team plan for students) and inject it at deploy time. Do not keep it only
  on the server.
- `chmod 600 .env`, `chown 1000:1000 .env` (the container's UID), `chmod 700 keys/`.
- Enable **TOTP two-factor** on the OpenAlgo account from Settings. The Fernet
  KDF consumes `API_KEY_PEPPER`, so enable TOTP *before* you ever rotate the
  pepper, not after.
- Rotate broker API keys at your broker on a schedule, and immediately after any
  suspected exposure.
- Never put a broker key in a URL, a TradingView webhook field you screenshot, or
  a chat. The nginx installer goes out of its way to keep `/strategy|/flow|/chartink/webhook`
  out of access logs; keep that guard if you write your own proxy config.

### 11.4 Log hygiene

```ini
LOG_TO_FILE='True'
LOG_LEVEL='INFO'
LOG_RETENTION='14'                     # days
TRAFFIC_LOG_RETENTION_DAYS='30'
```

`logs.db` records API traffic, and broker access tokens are not logged — but
`log/` on a public server is reconnaissance for an attacker. `LOG_LEVEL='DEBUG'`
in particular prints request detail. Keep it `INFO` in production.

### 11.5 Pre-deploy security scan

```powershell
pip install detect-secrets
detect-secrets scan --all-files
```

`.secrets.baseline` is already committed, and `.pre-commit-config.yaml` runs this
on commit. Add `--baseline .secrets-baseline` if you want to compare.

---

## 12. Data, databases and backups

### 12.1 Decide your database topology first

| Where you deploy | `DATABASE_URL` | `keys/` | Historify DuckDB |
|---|---|---|---|
| A, B (VPS / tunnel) | `sqlite:///db/openalgo.db` (default) | persistent volume | works |
| C, D, E (PaaS) | managed Postgres | **lost on deploy** | unavailable |

Do not migrate an existing local `db/openalgo.db` to Postgres casually. It holds
Argon2 password hashes and Fernet-encrypted broker tokens; you want to re-enter
the broker credentials on the new host rather than trust a hand-converted file.

### 12.2 SQLite backup that is actually consistent

SQLite is running in **WAL mode** — `db/` contains `-wal` and `-shm` sidecars.
`cp db/openalgo.db backup.db` while the app is running produces a file that may be
missing recent commits. Use the online backup API:

```bash
docker compose exec openalgo /app/.venv/bin/python - <<'PY'
import sqlite3, time, pathlib
stamp = time.strftime("%Y%m%d-%H%M%S")
out = pathlib.Path(f"/app/db/backups/{stamp}"); out.mkdir(parents=True, exist_ok=True)
for src in pathlib.Path("/app/db").glob("*.db"):
    dst = sqlite3.connect(str(out / src.name))
    with sqlite3.connect(str(src)) as s:
        s.backup(dst)
    dst.close()
    print("backed up", src.name)
PY
```

That covers every `*.db` including WAL contents. Copy the **whole** `db/`
directory plus `keys/` to off-host storage, and treat `db/backups/` itself as
excluded (`.gitignore` already lists it).

```cron
# 03:40 IST daily — after the session-expiry logouts at 03:00
40 3 * * * /usr/local/bin/openalgo-backup.sh >> /var/log/openalgo-backup.log 2>&1
```

Back up at least these off-host: `db/`, `keys/`, `strategies/`, `.env`
(encrypted — 1Password), and `log/` if you care about audit history.
`db/historify.duckdb` can be tens of GB; back it up on its own slower cycle.

### 12.3 Restore

```bash
docker compose down
cp -r /backup/db/. db/
cp -r /backup/keys/. keys/
sudo chown -R 1000:1000 db keys
sudo chmod 700 keys
docker compose up -d
```

If you restore `db/` you **must** restore the matching `.env` — the `API_KEY_PEPPER`
and `FERNET_SALT` in that `.env` are what decrypt the tokens in that database.
A restored database with a fresh pepper gives you undecryptable broker tokens and
unusable password hashes, and there is no recovery.

---

## 13. Post-deploy verification

Run these in order. Each one that fails tells you which section to go back to.

```bash
# 1. Container is healthy
docker compose ps
curl -fsS https://trade.example.com/auth/check-setup

# 2. Web UI and API docs load
curl -fsS -o /dev/null -w '%{http_code}\n' https://trade.example.com/
curl -fsS -o /dev/null -w '%{http_code}\n' https://trade.example.com/api/docs

# 3. TLS is real (not a self-signed fallback)
echo | openssl s_client -connect trade.example.com:443 2>/dev/null \
  | openssl x509 -noout -issuer -dates

# 4. WebSocket upgrade reaches port 8765
curl -i -N -H "Connection: Upgrade" -H "Upgrade: websocket" \
     -H "Sec-WebSocket-Version: 13" -H "Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==" \
     https://trade.example.com/ws | head -5
# expect: HTTP/1.1 101 Switching Protocols

# 5. Ports 5000 / 8765 / 5555 are NOT reachable from the internet
nmap -p 5000,8765,5555 trade.example.com   # expect: filtered
```

Then, in the browser:

1. Log in to `https://trade.example.com` and complete the setup wizard.
2. **Enable TOTP** (§11.3).
3. Log in to your broker. This proves `REDIRECT_URL`, the certs in `keys/`, and
   the redirect whitelist all line up.
4. Confirm the ticker/live feed updates. If it does not, §1.1 — the WebSocket
   path is the usual culprit.
5. Place **one order in analyzer/sandbox mode** (`sandbox`), never a live order,
   until the whole chain is verified.
6. Check `http://trade.example.com/market-scanner` — Task 2 of this fork, and a
   good end-to-end test of the scanner's background jobs.

---

## 14. Updates and rollback

### 14.1 Options A and B (your own server)

```bash
cd /opt/openalgo_indian_markets_mvp
git fetch --all
git checkout <pinned-tag-or-sha>       # pin; do not track main blindly
docker build -t openalgo:$(git rev-parse --short HEAD) .
docker compose up -d                   # start.sh runs migrate_all.py
docker compose logs -f --tail=200
```

Keep the previous tag so rollback is one command:

```bash
docker tag openalgo:<good-sha> openalgo:latest
docker compose up -d
```

Migrations are idempotent and forward-only. There is no automatic down-migration,
so **take a §12.2 backup before every upgrade**, and never skip a version.

### 14.2 Railway / Render / Heroku

All three auto-deploy on push to the selected branch. That is the risk: a bad push
becomes a bad production instance with no review.

- Point the platform at a dedicated `deploy/production` branch (§7.4).
- Require review before merging into it.
- Re-pasting `APP_KEY` / `API_KEY_PEPPER` / `FERNET_SALT` is *required* — do not
  let a platform regenerate them, and never "fix" a problem by rotating them.
- Roll back by redeploying the previous successful deploy (Railway/Render both
  keep a deploy history).

### 14.3 Backup the deployment definition

Keep your own `deploy/` directory in the repo (it is small, reviewable, and
survives a lost VPS):

```
deploy/
  caddy/Caddyfile
  env.production.example      # secrets as placeholders only
  backup.sh
  cloudflared/config.yml.example
  README.md                   # IPs, DNS table, what is where
```

Never the real `.env`. The value of this directory is that rebuilding a dead
server is a 20-minute job, not a half-day one.

---

## 15. Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| Container restart loop, "STARTUP BLOCKED — compromised APP_KEY" | `.env` still has the sample `APP_KEY`/`API_KEY_PEPPER` from `.sample.env`, and the in-container rotation cannot write to the read-only mount | `docker compose down`, generate a fresh `APP_KEY`, `chown 1000:1000 .env && chmod 600 .env`, `docker compose up -d`. Do **not** rotate `API_KEY_PEPPER` if the DB has users |
| `[auth_db] WARNING: FERNET_SALT not set or invalid` | `FERNET_SALT` missing or unwritable `.env` | Set `FERNET_SALT` as an env var / in `.env` with correct ownership |
| `Permission denied: .env.tmp` | `.env` not owned by UID 1000 | `sudo chown 1000:1000 .env` |
| Login page loads, live feed never connects | WebSocket path not proxied, or `WEBSOCKET_URL` is `ws://` | Proxy `/ws` to 8765 with `flush_interval -1`; set `WEBSOCKET_URL = 'wss://<host>/ws'`; add your host to `CSP_CONNECT_SRC` |
| Streaming endpoints stall, then dump in bursts | Proxy response buffering | Caddy `flush_interval -1`; nginx `proxy_buffering off` |
| `429 Too Many Requests` on login, from a single user | `TRUST_PROXY_HEADERS='FALSE'` behind a proxy — every client looks like the proxy IP | Set `TRUST_PROXY_HEADERS='TRUE'` |
| OAuth callback lands on 404 | `REDIRECT_URL` ≠ broker whitelist, or broker rejects a path | Make them byte-identical; deploy on the apex domain if the broker refuses sub-paths |
| "Docker Desktop required" / build fails on `apt` 404 | Stale base image references an EOL Debian | Already fixed in this `Dockerfile` (trixie). `docker build --pull --no-cache` if your cache predates the change |
| `RLIMIT_NPROC` / thread exhaustion | Too many BLAS threads in a small container | Set `OPENBLAS_NUM_THREADS`, `OMP_NUM_THREADS`, `MKL_NUM_THREADS`, `NUMBA_NUM_THREADS` to `1`–`2` |
| Chromium/`/chart` fails in the Telegram bot | Headless Chromium missing | Already installed in the runtime image; confirm `BROWSER_PATH=/usr/bin/chromium` |
| Data gone after a PaaS redeploy | Ephemeral filesystem | §12.1 — move to Postgres, accept losing `keys/` |
| gunicorn restarts, workers die under load | Memory limit too low for the number of strategies | Raise the VPS RAM; lower `STRATEGY_MEMORY_LIMIT_MB`; raise `SHM_SIZE` to 25% of RAM |
| Certbot/Caddy cannot get a certificate | DNS not propagated, or 80/443 blocked | `dig +short <host>`, `ufw status`, then retry |

---

## 16. Cloud environment variable reference

Minimum set for any PaaS target. `start.sh` detects `HOST_SERVER` and renders
`/app/.env` from these.

| Variable | Required | Value / note |
|---|---|---|
| `HOST_SERVER` | **yes** | `https://trade.example.com` — this is the switch that triggers `.env` generation |
| `REDIRECT_URL` | **yes** | `https://trade.example.com/<broker>/callback` |
| `APP_KEY` | **yes** | `secrets.token_hex(32)`. Rotating logs everyone out |
| `API_KEY_PEPPER` | **yes** | `secrets.token_hex(32)`. **Never rotate on a populated DB** |
| `FERNET_SALT` | **yes** | `secrets.token_hex(32)`. **Never rotate on a populated DB** |
| `BROKER_API_KEY` / `BROKER_API_SECRET` | **yes** | From the broker console |
| `BROKER_API_KEY_MARKET` / `BROKER_API_SECRET_MARKET` | XTS brokers only | |
| `VALID_BROKERS` | yes | e.g. `fyers` |
| `DATABASE_URL` | PaaS only | `postgresql://…?sslmode=require` |
| `LOGS_DATABASE_URL`, `LATENCY_DATABASE_URL`, `HEALTH_DATABASE_URL`, `SANDBOX_DATABASE_URL` | optional | default to SQLite; on PaaS point them at the same Postgres |
| `TRUST_PROXY_HEADERS` | recommended | `TRUE` behind a real proxy |
| `CORS_ALLOWED_ORIGINS` | recommended | Exactly `HOST_SERVER` |
| `CSP_UPGRADE_INSECURE_REQUESTS` | recommended | `TRUE` |
| `DISABLE_SESSION_EXPIRY` | crypto brokers | `true` for 24/7 markets |
| `WEBSOCKET_URL` | if WS reachable | `wss://trade.example.com/ws` |
| `MCP_HTTP_ENABLED` | optional | `True` + `MCP_PUBLIC_URL` to enable Remote MCP (see `docs/userguide/remote-mcp.md`) |
| `PORT` | **injected by the platform** | Do not set it. `start.sh` honours it for gunicorn |
| `FLASK_DEBUG` | **never** | `False` |
| `ZMQ_HOST` | **never change** | `127.0.0.1` |

### 16.1 Diff the generated `.env`

The `.env` that `start.sh` writes on PaaS is stamped `ENV_CONFIG_VERSION 1.0.4`;
`.sample.env` is at `1.0.7`. After the first deploy, pull the generated file and
compare:

```bash
docker compose exec openalgo cat /app/.env > /tmp/deployed.env
diff <(sort /tmp/deployed.env) <(sort .sample.env) | grep '^[<>]'
```

Anything missing gets set as a platform variable. `utils/env_check.py` also
prints an explicit upgrade instruction when it sees a version mismatch, so read
the first-boot log.

---

## 17. Student Pack benefits used here

| Benefit | How it is used here | Cost |
|---|---|---|
| **Domain** (Name.com / Namecheap / .TECH) | The public hostname for the dashboard and broker callback | $0 for 1 year |
| **1Password** (1 year) | Store `.env`, broker keys, the Fernet salt, the Cloudflare tunnel credential | $0 for 1 year |
| **Doppler** (free Team) | Alternative to 1Password for injecting secrets at deploy time | $0 while a student |
| **GitHub** (Pro) | Private repo, Codespaces to run the Docker build without touching this PC, Actions for CI on push | $0 while a student |
| **GitHub Codespaces** | Build and test the image on a machine that is not the trading server | $0 while a student |
| **JetBrains / PyCharm** | Editing strategies in `strategies/` over SSH | $0 while a student |
| **GitHub Copilot** | Strategy development | $0 while a student |
| **Azure** ($100 credit) | Optional: Option E, or a managed Postgres for the PaaS targets | $100, expires in 12 months |
| **Heroku** ($13/mo × 24) | Optional: Option D, demo instances only | $312 total, expires in 24 months |
| **MongoDB** ($50) | Not applicable — OpenAlgo uses SQLAlchemy + SQLite/Postgres, not MongoDB | — |
| **Namecheap free SSL** | Not needed — Caddy/certbot issue free Let's Encrypt certs automatically | — |
| **GitHub Pages** | Optional static landing page that links to the dashboard. Do **not** put secrets or broker keys in a Pages site | $0 |

### Total cost, recommended path

| Item | Cost |
|---|---|
| Domain (`.dev`/`.app` via Name.com) | $0 (student) |
| Cloudflare DNS + TLS | $0 |
| 1Password | $0 (student) |
| **VPS — Hetzner CX23, EU (best value)** | **≈ €6.50/mo ≈ $7.50** (incl. IPv4) |
| **VPS — AWS Lightsail Mumbai (best latency)** | **≈ $12/mo** |
| DigitalOcean / Vultr Mumbai | ≈ $24/mo |
| Oracle Always Free Ampere A1 | $0, if Mumbai capacity exists |
| **Total** | **$7.50–12/month**, or $0 on Oracle |

That is well under one month of Heroku credit, and Option A is the only path in
this document that runs the live feed, the strategies and Historify on persistent
disk. If the Hetzner EU location's round trip to your broker is too slow, the
Lightsail Mumbai line is the extra $4.50/month that buys it.

---

## Related documentation

| Topic | File |
|---|---|
| Documentation map | `docs/INDEX.md` |
| Ubuntu server install (nginx path) | `docs/installation-guidelines/getting-started/ubuntu-server-installation.md` |
| Docker reference | `docs/docker/README.md`, `DOCKER_README.md` |
| REST API | `docs/api/README.md` |
| Remote MCP | `docs/userguide/remote-mcp.md` |
| Live scanner (Task 2, this fork) | `docs/api/market-scanner.md` |
| Security audits | `docs/audit/README.md`, `SECURITY.md` |
| Six-task roadmap and handoff | `docs/plans/2026-09-11-six-task-roadmap.md` |
| Environment variable reference | `.sample.env` |
