# Deployment Guide

This guide covers the deployment of **OntoSage 2.0** using Docker Compose.

## Prerequisites

- **Docker Desktop** (Windows/Mac) or **Docker Engine** (Linux)
- **NVIDIA GPU Drivers** (Optional, for local LLM acceleration)
- **PowerShell** (Windows) or **Bash** (Linux/Mac)

## Quick Start

The easiest way to deploy is using the automated startup script.

### 1. Configure Environment

Copy the appropriate environment template to `.env`:

**For Local Models (Free, requires decent hardware):**
```bash
cp .env.local .env
```

**For Cloud Models (OpenAI, paid):**
```bash
cp .env.cloud .env
```
*Edit `.env` to add your `OPENAI_API_KEY` if using cloud models.*

### 2. Run Startup Script

**Windows (PowerShell):**
```powershell
./startup.ps1 -Provider local  # or -Provider cloud
```

**Linux/Mac (Bash):**
```bash
./scripts/check-health.sh
docker-compose up -d
```

## Manual Deployment

If you prefer to run Docker Compose commands manually:

```bash
# Build and start core services
docker-compose up -d --build

# If using Agentic features (Ollama/Open WebUI)
docker-compose -f docker-compose.agentic.yml up -d
```

## Service Endpoints

| Service | URL | Description |
|---------|-----|-------------|
| **Frontend** | `http://localhost:3000` | Main User Interface |
| **Orchestrator API** | `http://localhost:8000` | Backend API & Swagger Docs |
| **RAG Service** | `http://localhost:8001` | Retrieval Service |
| **Code Executor** | `http://localhost:8002` | Sandbox Service |
| **Whisper STT** | `http://localhost:8003` | Speech-to-Text Service |
| **Ollama** | `http://localhost:11434` | Local LLM Server |
| **Grafana** | `http://localhost:3001` | Monitoring Dashboard (if enabled) |

## Troubleshooting

- **Ollama Model Download**: The first run may take a while as it downloads the LLM (several GBs). Check logs with `docker logs -f ollama`.
- **Port Conflicts**: Ensure ports 3000, 8000, 5432, 3306 are free. You can change ports in `.env`.
- **GPU Issues**: If using local models, ensure Docker has access to your GPU.
