# VPS Deployment (TailorTom Backend)

Deploy the API, Celery worker, Redis, Postgres, and Caddy on a single VPS (e.g. DigitalOcean Droplet). The frontend stays on Vercel and calls `https://api.tailortom.org`.

---

## 1. Auto-deploy on git push to main

Render rebuilt on every push to main. On a VPS you get the same behavior with **GitHub Actions**.

### Setup

1. **On the VPS:** Clone the repo and set up the app once (see “Initial server setup” below). Note the path where the repo lives (e.g. `/opt/tailortom` or `~/TailorTom`).

2. **SSH access for GitHub:** On your machine, generate a key pair for deploys (or use an existing one):
   ```bash
   ssh-keygen -t ed25519 -C "github-deploy" -f ~/.ssh/tailortom_deploy -N ""
   ```
   Add the **public** key to the VPS:
   ```bash
   ssh-copy-id -i ~/.ssh/tailortom_deploy.pub user@your-vps-ip
   ```
   Copy the **private** key content:
   ```bash
   cat ~/.ssh/tailortom_deploy
   ```

3. **GitHub repo secrets:** In the repo: **Settings → Secrets and variables → Actions**. Add:
   - `DEPLOY_HOST` – VPS IP or hostname (e.g. `165.232.123.45`)
   - `DEPLOY_USER` – SSH user (e.g. `root` or `deploy`)
   - `SSH_PRIVATE_KEY` – full contents of the private key (e.g. from `cat ~/.ssh/tailortom_deploy`)
   - `DEPLOY_PATH` – path to the repo on the server (e.g. `/opt/tailortom`)

After this, every **push to `main`** runs the workflow: it SSHs into the VPS, runs `git pull` and `docker compose up -d --build`, so the server runs the latest main.

---

## 2. Auto-restart when the app or workers crash

Docker Compose is already configured to restart containers if they exit:

- **api**, **worker**, and **redis** use `restart: unless-stopped`.

So if the API or a worker crashes, Docker restarts it. No extra setup needed.

---

## 3. Route https://api.tailortom.org to the backend

Caddy in this repo acts as a reverse proxy and gets a free TLS certificate from Let’s Encrypt.

### Steps

1. **DNS**  
   At your DNS provider, add a record for the API:
   - **Type:** `A`
   - **Name:** `api` (or `api.tailortom.org` if your provider uses full names)
   - **Value:** your VPS public IP  
   So `api.tailortom.org` resolves to that IP.

2. **Firewall**  
   Open HTTP and HTTPS on the VPS:
   ```bash
   # Ubuntu/Debian (ufw)
   sudo ufw allow 80
   sudo ufw allow 443
   sudo ufw enable
   ```

3. **Start the stack (including Caddy)**  
   From the repo root on the VPS (with `.env` in place):
   ```bash
   docker compose up -d --build
   ```
   Caddy will listen on 80 and 443, request a certificate for `api.tailortom.org`, and proxy to the API container.

4. **Use the API**  
   Point the frontend (e.g. on Vercel) to `https://api.tailortom.org`. No need to open port 8000 publicly unless you want to; Caddy handles HTTPS and forwards to the API.

### Optional: stop exposing the API on port 8000

To avoid direct access to the API on port 8000, in `docker-compose.yml` change the api service ports to:

```yaml
ports:
  - "127.0.0.1:8000:8000"
```

Then only Caddy (on the same host) can reach the API.

---

## Initial server setup (one-time)

1. Install Docker and Docker Compose on the VPS (e.g. [Docker’s install script](https://docs.docker.com/engine/install/)).

2. Clone the repo and create `.env` at the **repo root**:
   ```bash
   git clone https://github.com/your-org/TailorTom.git /opt/tailortom
   cd /opt/tailortom
   cp env.vps.example .env
   # Edit .env: OPENAI_API_KEY, ADMIN_PASSWORD, REDIS_URL=redis://redis:6379/0,
   # CELERY_QUEUE_NAME=hosted, POSTGRES_PASSWORD, DATABASE_URL (see below)
   ```

3. **Database (PostgreSQL):** In `.env` set a strong Postgres password and the connection URL:
   - `POSTGRES_USER=tailortom` (or leave default)
   - `POSTGRES_PASSWORD=<strong-password>`
   - `POSTGRES_DB=tailortom`
   - `DATABASE_URL=postgresql://tailortom:<same-password>@postgres:5432/tailortom`
   Schema is created by SQLAlchemy + Alembic (run `alembic upgrade head` on first deploy, or from API startup).

4. Start the stack:
   ```bash
   docker compose up -d --build
   ```

5. Configure GitHub Actions and DNS as in sections 1 and 3 above.
