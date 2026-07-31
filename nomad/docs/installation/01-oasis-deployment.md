# NOMAD Oasis Deployment Guide

## Server Environment

| Property | Value |
|----------|-------|
| **Host** | `researchmcp.duckdns.org` |
| **OS** | Debian 12 (bookworm), 6.1.0-48-cloud-amd64 |
| **RAM** | 3.8 GB |
| **CPU** | 2 vCPUs |
| **Swap** | 10 GB (critical — see below) |
| **Disk** | Cloud volume, ~30 GB free after deployment |
| **Docker** | 24+ with Compose v2 |
| **NOMAD version** | 1.4.2 |

---

## Pre-Flight Resource Check

**Always run this before starting or restarting services:**

```bash
free -h && echo '---CPU---' && nproc && echo '---Disk---' && df -h / && echo '---Swap---' && swapon --show
```

**Key thresholds for this host (3.8 GB RAM):**

| Metric | Safe | Danger |
|--------|------|--------|
| Free RAM (after existing services) | > 1 GB | < 500 MB → OOM risk |
| Swap | > 4 GB | 0 GB with < 6 GB RAM → certain OOM |
| Free disk | > 10 GB | < 5 GB → image pulls fail |

---

## Step 1: Swap Setup (Critical for 3.8 GB Host)

Without swap, the full NOMAD stack (elasticsearch, temporal, postgresql, app)
will trigger the kernel OOM killer during startup. **You will lose SSH access**
and have to reboot through the hosting dashboard.

```bash
# Create 10 GB swap file
sudo fallocate -l 10G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile

# Make permanent
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab

# Reduce swappiness so kernel prefers RAM
sudo sysctl vm.swappiness=10
echo 'vm.swappiness=10' | sudo tee -a /etc/sysctl.conf
```

**Why 10 GB:** The full stack needs ~2.5-3.0 GB steady state with
startup spikes to 3.5+ GB. With only 3.8 GB RAM, swap absorbs the spikes.
2 GB swap was tested and was insufficient.

---

## Step 2: Clone the Distro Template

```bash
git clone https://github.com/FAIRmat-NFDI/nomad-distro-template.git
cd nomad-distro-template
```

---

## Step 3: Generate Environment File

```bash
bash scripts/generate-env.sh
```

This creates `.env` with a random 64-char `NOMAD_SERVICES_API_SECRET`.

---

## Step 4: Adjust CPU Limits

The default `cpus: "4.0"` in `docker-compose.yaml` will fail on a 2-CPU host:

```
Range of CPUs is from 0.01 to 2.00, as there are only 2 CPUs available
```

**Fix:** Reduce worker CPU limits:

```bash
# Check which services have deploy.cpus
grep -B2 'cpus:' docker-compose.yaml

# If workers have deploy section, reduce:
sed -i 's/cpus: "4.0"/cpus: "1.5"/g' docker-compose.yaml
```

---

## Step 5: Set Per-Service Memory Limits

Without memory limits, a single container (elasticsearch at ~800 MB) can
consume enough RAM to starve the rest of the stack. Set hard caps.

**Tested values on 3.8 GB RAM / 2-CPU host with 10 GB swap:**

| Service | `mem_limit` | `memswap_limit` | Notes |
|---------|-------------|-----------------|-------|
| `elastic` | 512M | 2G | ES_JAVA_OPTS=-Xms512m -Xmx512m |
| `mongo` | 384M | 1G | |
| `postgresql` | 384M | 1G | |
| `temporal` | 512M | 2G | |
| `app` | 512M | 2G | |
| `north` | 384M | 1G | Optional |
| `worker` | 256M | 1G | |
| `proxy` | 128M | 512M | nginx |

**Use Python to modify YAML (avoid `sed` — it breaks on commented-out sections):**

```python
import yaml
with open('docker-compose.yaml') as f:
    data = yaml.safe_load(f)

limits = {
    'elastic': {'mem_limit': '512M', 'memswap_limit': '2G'},
    'mongo': {'mem_limit': '384M', 'memswap_limit': '1G'},
    'postgresql': {'mem_limit': '384M', 'memswap_limit': '1G'},
    'temporal': {'mem_limit': '512M', 'memswap_limit': '2G'},
    'app': {'mem_limit': '512M', 'memswap_limit': '2G'},
    'north': {'mem_limit': '384M', 'memswap_limit': '1G'},
}

for name, lim in limits.items():
    svc = data['services'].get(name)
    if svc:
        svc['mem_limit'] = lim['mem_limit']
        svc['memswap_limit'] = lim['memswap_limit']

with open('docker-compose.yaml', 'w') as f:
    yaml.dump(data, f, default_flow_style=False, width=200, sort_keys=False)
```

**⚠️ Warning:** This strips all YAML comments. Keep a `git checkout` undo handy.

---

## Step 6: Gradual Startup (Avoid OOM)

**Do NOT run `docker compose up -d` all at once.** Starting everything
simultaneously creates a memory spike that exceeds 3.8 GB.

Start services in dependency order:

```bash
# 1. Databases first (wait for healthy between each)
docker compose up -d elastic mongo
docker compose ps elastic mongo   # wait for healthy

# 2. postgresql (needed by temporal)
docker compose up -d postgresql
docker compose ps postgresql

# 3. temporal
docker compose up -d temporal
docker compose ps temporal

# 4. app + north
docker compose up -d app north
docker compose ps

# 5. Workers last (most CPU-intensive)
docker compose up -d worker
docker compose ps

# 6. Proxy last
docker compose up -d proxy
```

### OOM Crash Detection

**Symptoms:**
- SSH becomes unreachable during `docker compose up -d`
- After reboot, `docker compose ps` shows `postgresql` and `temporal` with
  `Exited (255)` — same timestamp
- Docker's `OOMKilled` says `false` (kernel OOM doesn't propagate to Docker)

**Diagnostic:**
```bash
docker inspect <container> --format '{{.State.ExitCode}} {{.State.FinishedAt}}'
# Exit 255 + matching timestamps across containers = kernel OOM
```

**Fix:**
1. Add swap (Step 1)
2. Use gradual startup (Step 6)
3. If the server becomes unreachable: reboot through hosting dashboard

---

## Step 7: Verify Deployment

```bash
# Check all containers healthy
docker compose ps

# Test health endpoint (direct)
curl -s http://localhost:8000/-/health

# Test health endpoint (via proxy)
curl -s http://localhost:8080/-/health

# Test GUI
curl -s -o /dev/null -w "%{http_code}" http://localhost:8080/nomad-oasis/gui/
```

---

## Step 8: Caddy Reverse Proxy Integration

Since ports 80/443 are occupied by another reverse proxy (Caddy, part of
the MCP stack on the same host), NOMAD's nginx proxy was moved to alternate
ports and Caddy routes `/nomad-oasis/*` to it.

### On the NOMAD host, Caddy runs separately. The key setup:

**1. Change NOMAD proxy ports (if 80/443 are taken):**

Edit `docker-compose.yaml`:
```yaml
proxy:
  ports:
    - "8080:80"    # was 80:80
    - "8443:443"   # was 443:443
```

**2. Connect the Caddy container to the NOMAD Docker network:**

```bash
# NOMAD creates a network named nomad_oasis_network
docker network connect nomad_oasis_network <caddy-container-name>
```

**3. Add route to Caddy config:**

```caddy
handle /nomad-oasis/* {
    reverse_proxy proxy:80 {
        flush_interval -1
    }
}
```

**DO NOT use `handle_path`** — it strips the prefix. NOMAD expects the
full `/nomad-oasis/` path to reach its nginx, which then strips it before
forwarding to `app:8000`.

The architecture:
```
Browser → Caddy (443) → /nomad-oasis/* → nginx (proxy:80) → app:8000
```

---

## Resource Usage (Real-World, 2-CPU / 3.8 GB VM)

| Service | Observed RAM | Notes |
|---------|-------------|-------|
| elastic | 800-900 MB | Significantly more than 512 MB hint |
| app | 450 MB | Steady after startup |
| mongo | 250 MB | Stable |
| north | 160 MB | Optional |
| worker (each) | 30-50 MB | Low unless actively processing |
| postgresql | ~200 MB | |
| temporal | ~500 MB | |
| proxy | ~50 MB | nginx |
| **Total** | **~2.5-3.0 GB** | Steady state |

**Minimum viable** (app + elastic + mongo only): ~1.5 GB steady state

---

## NOMAD Configuration

### configs/nomad.yaml

```yaml
services:
  api_host: "localhost"
  api_base_path: "/nomad-oasis"

oasis:
  is_oasis: true
  uses_central_user_management: true

plugins:
  entry_points:
    options:
      nomad_north_jupyter.north_tools:jupyter:
        north_tool:
          image: ghcr.io/fairmat-nfdi/nomad-north-jupyter:latest

meta:
  deployment: "oasis"
  deployment_url: "https://my-oasis.org/api"
  maintainer_email: "me@my-oasis.org"

logstash:
  enabled: false

temporal:
  enabled: true

mongo:
  db_name: nomad_oasis_v1

elastic:
  entries_index: nomad_oasis_entries_v1
  materials_index: nomad_oasis_materials_v1
```

---

## Common Issues

### 1. App shows "Control server error: /nonexistent"

```
[ERROR] Control server error: [Errno 13] Permission denied: '/nonexistent'
```

**Cosmetic only.** The app still serves HTTP on port 8000. Not a real issue.

### 2. "Failed client connect: dns error" for temporal

```
RuntimeError: Failed client connect: Server connection error:
...failed to lookup address information: Name or service not known
```

**Root cause:** temporal is dead (usually OOM). Never a DNS issue — Docker
Compose network provides DNS resolution. Fix the root cause (add swap,
gradual startup).

### 3. Port 80/443 already in use

**Solution:** Move NOMAD proxy to alternate ports (8080/8443) and integrate
behind the existing reverse proxy (see Step 8).

### 4. Services stuck in "Waiting"

Check dependent services are healthy:
```bash
docker compose logs elastic --tail 20
docker compose logs mongo --tail 20
```

---

## Useful Commands

```bash
# View logs
docker compose logs app --tail 50

# Restart a single service
docker compose up -d app

# Full restart (gradual)
docker compose up -d elastic mongo
docker compose up -d postgresql
docker compose up -d temporal
docker compose up -d app north
docker compose up -d worker proxy

# Nginx reload (needed after app container restart)
docker exec nomad_oasis_proxy nginx -s reload

# Check memory per container
docker stats --no-stream

# Execute command in app container
docker exec nomad_oasis_app python3 -c "print('hello')"
```
