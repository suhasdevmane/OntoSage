# Deployment Guide

This guide walks you through deploying OntoSage from scratch on a new server or workstation. OntoSage runs entirely in Docker — no Python environment or database installation is required on the host.

---

## Prerequisites

### Required

| Requirement | Minimum | Recommended | Notes |
|---|---|---|---|
| Operating System | Ubuntu 20.04 / Windows 10 / macOS 12 | Ubuntu 22.04 LTS | WSL2 supported on Windows |
| Docker Engine | 24.x | Latest stable | |
| Docker Compose | v2.x | v2.24+ | `docker compose` (without hyphen) |
| RAM | 8 GB | 16 GB | 8 GB minimum for OpenAI mode |
| Disk | 20 GB free | 50 GB free | More if using local LLMs |
| CPU | 4 cores | 8+ cores | |

### For Local LLM Mode (Optional)

| Requirement | Minimum | Recommended |
|---|---|---|
| GPU | NVIDIA 8 GB VRAM | NVIDIA 24 GB VRAM |
| CUDA | 11.8 | 12.x |
| NVIDIA Container Toolkit | Latest | Latest |

If you do not have a GPU, use OpenAI mode (`MODEL_PROVIDER=openai`) — it runs on any hardware.

---

## Installation

### 1. Install Docker

=== "Ubuntu / Debian"
    ```bash
    # Remove old versions
    sudo apt-get remove docker docker-engine docker.io containerd runc

    # Add Docker's official GPG key
    sudo apt-get update
    sudo apt-get install ca-certificates curl gnupg
    sudo install -m 0755 -d /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg

    # Install Docker Engine
    sudo apt-get update
    sudo apt-get install docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

    # Add your user to the docker group (no sudo required)
    sudo usermod -aG docker $USER
    newgrp docker
    ```

=== "Windows"
    1. Download and install [Docker Desktop for Windows](https://www.docker.com/products/docker-desktop/)
    2. Enable WSL2 integration in Docker Desktop settings
    3. Ensure WSL2 is set as the default (not Hyper-V backend)

=== "macOS"
    1. Download and install [Docker Desktop for Mac](https://www.docker.com/products/docker-desktop/)
    2. Allocate at least 8 GB RAM in Docker Desktop → Preferences → Resources

### 2. Clone the Repository

```bash
git clone https://github.com/suhasdevmane/OntoSage.git
cd OntoSage
```

### 3. Configure Environment

Copy the example environment file:

```bash
cp .env.example .env
```

Open `.env` in a text editor and set at minimum:

```bash
# ── LLM Provider ─────────────────────────────────────────────────────────
MODEL_PROVIDER=openai           # or: local (requires GPU + Ollama)
OPENAI_API_KEY=sk-...           # Your OpenAI API key (required if MODEL_PROVIDER=openai)
OPENAI_MODEL=gpt-4o-mini        # or gpt-4o, gpt-4-turbo

# ── Database ──────────────────────────────────────────────────────────────
MYSQL_ROOT_PASSWORD=changeme
MYSQL_DATABASE=ontosage
MYSQL_USER=ontosage
MYSQL_PASSWORD=changeme

POSTGRES_USER_USER=ontosage
POSTGRES_USER_PASSWORD=changeme
POSTGRES_USER_DB=ontosage_users

# ── GraphDB ───────────────────────────────────────────────────────────────
GRAPHDB_REPOSITORY=ontosage
GRAPHDB_SIMILARITY_INDEX=bldg_index
```

> **Security:** Never commit `.env` to version control. It is listed in `.gitignore` by default.

---

## Deployment Modes

OntoSage supports two primary deployment modes. Choose based on your infrastructure.

### Mode A: Cloud Mode (OpenAI — Recommended for Getting Started)

No GPU required. Uses OpenAI's API for LLM inference.

**`.env` settings:**
```bash
MODEL_PROVIDER=openai
OPENAI_API_KEY=sk-your-key-here
OPENAI_MODEL=gpt-4o-mini
```

**Start the stack:**
```bash
docker-compose up -d
```

This starts all services except Ollama (which requires the `local-gpu` profile).

**Expected startup time:** 2–5 minutes on first run (pulling images). Under 30 seconds on subsequent starts.

---

### Mode B: Local GPU Mode (Ollama — Privacy-First)

Runs entirely offline. No data leaves your server. Requires an NVIDIA GPU.

**Prerequisites:**

```bash
# Install NVIDIA Container Toolkit (Ubuntu)
distribution=$(. /etc/os-release;echo $ID$VERSION_ID)
curl -s -L https://nvidia.github.io/libnvidia-container/gpgkey | sudo apt-key add -
curl -s -L https://nvidia.github.io/libnvidia-container/$distribution/libnvidia-container.list | \
  sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list

sudo apt-get update
sudo apt-get install -y nvidia-container-toolkit
sudo systemctl restart docker
```

**Verify GPU is visible to Docker:**
```bash
docker run --rm --gpus all nvidia/cuda:12.0-base-ubuntu22.04 nvidia-smi
```

**`.env` settings:**
```bash
MODEL_PROVIDER=local
OLLAMA_BASE_URL=http://ollama-deepseek-r1:11434
OLLAMA_MODEL=deepseek-r1:32b
OLLAMA_GPU_LAYERS=-1
```

**Start the stack with GPU profile:**
```bash
docker-compose --profile local-gpu up -d
```

**Pull the model (first run only):**
```bash
docker exec ollama-deepseek-r1 ollama pull deepseek-r1:32b
```

> This downloads approximately 20 GB. Use a smaller model like `llama3.2:7b` if disk space is limited.

---

## Post-Startup Steps

### 1. Verify All Services Are Healthy

```bash
# Quick health check for all services
curl -s http://localhost:8000/health | python -m json.tool
curl -s http://localhost:8001/health
curl -s http://localhost:8002/health
curl -s http://localhost:6333/health

# Check Docker container status
docker-compose ps
```

All services should show `Up` or `healthy` status. If any service is `unhealthy`, check its logs:

```bash
docker-compose logs -f <service-name>
```

!!! note "Async jobs & production secrets"
    Long-running requests are dispatched to a Redis-backed job queue and polled via `GET /jobs/{job_id}` (see the [Runbook](RUNBOOK.md)). For production, set `STRICT_SECRETS=true` so the orchestrator refuses to start on default credentials (see [Security](SECURITY.md)).

### 2. Create a GraphDB Repository

Before ingesting your building ontology, create the repository in GraphDB:

1. Open `http://localhost:7200` in your browser
2. Click **Setup → Repositories → Create new repository**
3. Select **GraphDB Repository**
4. Set **Repository ID** to `ontosage` (must match `GRAPHDB_REPOSITORY` in `.env`)
5. Click **Create**

See the [GraphDB Setup Guide](GRAPHDB_SETUP.md) for detailed instructions including similarity index creation.

### 3. Load Your Building Ontology

Upload your building's Turtle (`.ttl`) file to GraphDB:

1. In the GraphDB workbench, go to **Import → RDF**
2. Select your `.ttl` file
3. Choose the `ontosage` repository
4. Click **Import**

Or via the REST API:

```bash
curl -X POST http://localhost:7200/repositories/ontosage/rdf-graphs/service \
  -H "Content-Type: text/turtle" \
  --data-binary @/path/to/building.ttl
```

### 4. Create the Similarity Index

Follow the [GraphDB Setup Guide](GRAPHDB_SETUP.md) to create the `bldg_index` similarity index. The RAG Service will not work without this step.

### 5. Access the Chat Interface

Open `http://localhost:3000` in your browser.

- Create a new account (first user becomes admin)
- Start a conversation and ask a question about your building

---

## Switching LLM Providers

You can switch between OpenAI and local Ollama at any time without rebuilding:

```bash
# Switch to local mode
./switch-provider.ps1 local     # Windows PowerShell
# or
MODEL_PROVIDER=local docker-compose restart orchestrator

# Switch to OpenAI mode
./switch-provider.ps1 openai    # Windows PowerShell
# or
MODEL_PROVIDER=openai docker-compose restart orchestrator
```

---

## Updating OntoSage

```bash
# Pull latest changes
git pull origin main

# Rebuild and restart changed services
docker-compose build orchestrator rag-service
docker-compose up -d orchestrator rag-service

# Or rebuild everything
docker-compose down
docker-compose build
docker-compose up -d
```

Your data (volumes) is preserved across updates.

---

## Production Deployment Considerations

### Reverse Proxy (nginx / Caddy)

For production, place a reverse proxy in front of Open WebUI and the Orchestrator API:

**nginx example:**
```nginx
server {
    listen 443 ssl;
    server_name ontosage.yourdomain.com;

    ssl_certificate /etc/letsencrypt/live/ontosage.yourdomain.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/ontosage.yourdomain.com/privkey.pem;

    location / {
        proxy_pass http://localhost:3000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_read_timeout 300s;
    }

    location /api/ {
        proxy_pass http://localhost:8000/;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

### Secrets Management

For production, use Docker Secrets instead of environment variables:

```yaml
# docker-compose.prod.yml
services:
  orchestrator:
    secrets:
      - openai_api_key
      - db_password

secrets:
  openai_api_key:
    external: true
  db_password:
    external: true
```

```bash
# Create secrets
echo "sk-your-key" | docker secret create openai_api_key -
echo "secure-password" | docker secret create db_password -
```

### Resource Limits

Add resource constraints in production:

```yaml
services:
  orchestrator:
    deploy:
      resources:
        limits:
          cpus: '2'
          memory: 4G
        reservations:
          cpus: '0.5'
          memory: 1G
```

### Backup Strategy

Critical data to back up:

```bash
# Backup GraphDB (ontology)
docker exec graphdb tar czf - /opt/graphdb/home > graphdb-backup-$(date +%Y%m%d).tar.gz

# Backup PostgreSQL (users and RBAC)
docker exec postgres-user-data pg_dump -U ontosage ontosage_users > users-backup-$(date +%Y%m%d).sql

# Backup volumes
tar czf volumes-backup-$(date +%Y%m%d).tar.gz ./volumes/
```

---

## Common Deployment Issues

### Port Already in Use

```
Error: port 8000 is already in use
```

Check what is using the port and either stop it or change the host port in `docker-compose.yml`:

```bash
# Find the process using port 8000
sudo lsof -i :8000    # Linux / macOS
netstat -ano | findstr :8000   # Windows

# Change the port in docker-compose.yml
ports:
  - "8001:8000"   # Use host port 8001 instead
```

### GraphDB Out of Memory

```
java.lang.OutOfMemoryError: Java heap space
```

Increase GraphDB heap size in `.env`:

```bash
GDB_HEAP_SIZE=8g
GDB_MAX_MEM=10g
```

Or in `docker-compose.yml` under the `graphdb` service.

### Orchestrator Cannot Reach GraphDB

```
ConnectionRefusedError: Cannot connect to graphdb:7200
```

Ensure both services are on the same Docker network (`ontobot-agentic`) and GraphDB's health check passes before the orchestrator starts. Add `depends_on` with `condition: service_healthy` if needed.

### Ollama Model Not Loading

```
Error: model not found
```

Pull the model manually:

```bash
docker exec ollama-deepseek-r1 ollama pull deepseek-r1:32b
docker-compose restart orchestrator
```

### Open WebUI Cannot Connect to Orchestrator

Check that `OPENAI_API_BASE_URL` in the Open WebUI environment points to the orchestrator container name, not `localhost`:

```bash
OPENAI_API_BASE_URL=http://ontosage-orchestrator:8000/v1   # correct
OPENAI_API_BASE_URL=http://localhost:8000/v1               # wrong (won't work between containers)
```

---

## Stopping and Uninstalling

```bash
# Stop all containers (data preserved)
docker-compose down

# Stop and remove volumes (DELETES ALL DATA)
docker-compose down -v

# Remove all OntoSage images
docker-compose down --rmi all
```
