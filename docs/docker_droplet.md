# Deploy with Docker on a DigitalOcean Droplet

This guide runs the API in **Docker** on a **Droplet** so you keep a **stable public IP** (assign a **Reserved / Floating IP** in the DigitalOcean control panel) and full control over the VM.

---

## 1. Create the Droplet

1. **DigitalOcean → Droplets → Create**
2. **Image:** Ubuntu 22.04 LTS (or 24.04)
3. **Plan:** smallest that fits your load (1 GB RAM minimum; 2 GB safer under load)
4. **Datacenter:** same region as Managed DB / Redis if you use them
5. **Authentication:** SSH keys (recommended)
6. **Optional:** enable **Monitoring**
7. Create the Droplet and note its **public IPv4**

### Reserved IP (stable address)

1. **Networking → Reserved IPs → Reserve Reserved IP**
2. Assign it to this Droplet  
   If you replace the Droplet later, **reassign** the same reserved IP to the new Droplet so partners’ IP allowlists stay valid.

---

## 2. Install Docker on the Droplet

SSH in as root or a sudo user:

```bash
sudo apt-get update
sudo apt-get install -y ca-certificates curl gnupg
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | sudo tee /etc/apt/sources.list.d/docker.list
sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo usermod -aG docker "$USER"
```

Log out and back in (or `newgrp docker`) so `docker` works without `sudo`.

---

## 3. Get the code on the server

**Option A — git clone**

```bash
sudo mkdir -p /opt/ktr-kiosk-backend
sudo chown "$USER:$USER" /opt/ktr-kiosk-backend
cd /opt/ktr-kiosk-backend
git clone <YOUR_REPO_URL> .
```

**Option B — build on CI and pull image**  
Build and push to Docker Hub / DO Container Registry, then on the Droplet only `docker pull` and run with `docker compose` — not covered in detail here; the `Dockerfile` in this repo is the build context.

---

## 4. Configure environment variables

Create `/opt/ktr-kiosk-backend/.env` (see `app/core/config.py`, `.env.example`, and `sandbox/deploy.md`).

**Minimum pattern:**

- `POSTGRES_DB_URL` — `postgresql+asyncpg://user:pass@host:25060/db?ssl=require` (Managed Postgres)
- `REDIS_HOST` — full URL, e.g. `rediss://default:password@host:25061/0`
- PhonePe **API** only: `PHONEPE_BASE_URL`, `PHONEPE_CALLBACK_URL`, `PHONEPE_QR_INIT_ENDPOINT`, `PHONEPE_TRANSACTION_ENDPOINT`

Per-store Petpooja, PhonePe merchant/salt, and PineLabs credentials belong in **PostgreSQL**, not in `.env` (seed with SQL after tables exist).

**Important:** `pydantic-settings` reads **environment variables**. Values in `.env` loaded by Docker Compose are injected into the container — **do not commit `.env`**.

Optional: set worker count:

```bash
WEB_CONCURRENCY=2
```

---

## 5. Build and run

```bash
cd /opt/ktr-kiosk-backend
docker compose build
docker compose up -d
docker compose ps
docker compose logs -f api
```

The API listens on **`0.0.0.0:8080`** inside the container; Compose maps **`8080:8080`** to the Droplet.

Test:

```bash
curl -sS http://127.0.0.1:8080/
```

From your laptop (firewall allowing):

```bash
curl -sS http://YOUR_DROPLET_IP:8080/
```

---

## 6. Firewall (UFW)

```bash
sudo ufw allow OpenSSH
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
# If you expose the API directly on 8080 (no Nginx yet):
sudo ufw allow 8080/tcp
sudo ufw enable
sudo ufw status
```

For production, prefer **only 80/443** open and put **Nginx** on the host (or another container) that proxies to `127.0.0.1:8080`, then close `8080` from the public internet.

---

## 7. HTTPS with Nginx + Let’s Encrypt (recommended)

1. Point your domain **A record** to the Droplet (or Reserved IP).
2. Install Nginx and Certbot on the **host** (not inside the API container).
3. Nginx `server` block: `proxy_pass http://127.0.0.1:8080;` for `location /`.
4. `certbot --nginx -d api.yourdomain.com`
5. Set `PHONEPE_CALLBACK_URL` and other public URLs to `https://api.yourdomain.com/...`

Then **remove** public access to port 8080 in UFW if Nginx terminates TLS on 443.

---

## 8. Updates after code changes

```bash
cd /opt/ktr-kiosk-backend
git pull
docker compose build --no-cache
docker compose up -d
```

---

## 9. Database migrations

SQL files live under `scripts/`. Run them against Managed Postgres when you add new tables/columns (`cash_pin`, takeaway columns, etc.). The app also runs `create_all` on startup for **new** tables in some cases; one-off SQL is still recommended for production.

---

## Files in this repo

| File | Role |
|------|------|
| `Dockerfile` | Python 3.12, Gunicorn + Uvicorn workers, port 8080 |
| `docker-compose.yml` | Builds image, maps 8080, loads `.env` |
| `.dockerignore` | Keeps image small and avoids leaking secrets |

---

## Troubleshooting

| Issue | What to check |
|-------|----------------|
| Container exits immediately | `docker compose logs api` — missing env vars often crash Pydantic at import |
| 502 from Nginx | API not listening: `curl http://127.0.0.1:8080/` on Droplet |
| DB connection errors | `POSTGRES_DB_URL` uses `postgresql+asyncpg`, SSL params, correct firewall from DO DB to Droplet |
