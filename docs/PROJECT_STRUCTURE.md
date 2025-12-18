# Project Structure Guide

This document provides a detailed overview of the **OntoSage 2.0** project structure.

## Root Directory

| File/Folder | Description |
|-------------|-------------|
| `docker-compose.yml` | Main Docker Compose configuration for the core services. |
| `docker-compose.*.yml` | Specialized Docker Compose files for different environments (Agentic, Buildings, DBs). |
| `startup.ps1` | PowerShell script for automated deployment and startup. |
| `README.md` | Quick start guide and project overview. |
| `Abacws/` | Contains the legacy/integration components for the Abacws system (API, Visualiser). |
| `Assets/` | Stores static assets, datasets, and data processing notebooks. |
| `bldg1/`, `bldg2/` | Configuration and data specific to different building deployments. |
| `code-executor/` | Service for securely executing generated Python code (Analytics Agent). |
| `data/` | Shared data directory for services. |
| `deploy/` | Deployment scripts and configuration files. |
| `docs/` | Project documentation (Architecture, Guides, References). |
| `frontend/` | React-based user interface application. |
| `monitoring/` | Configuration for Prometheus and Grafana monitoring. |
| `ollama-health/` | Health check sidecar service for Ollama. |
| `orchestrator/` | The core FastAPI application managing the LangGraph agents. |
| `rag-service/` | Service handling Retrieval-Augmented Generation and Vector DB interactions. |
| `scripts/` | Utility scripts for health checks, setup, and maintenance. |
| `shared/` | Shared code libraries or utilities used across multiple services. |
| `tests/` | Automated test suite. |
| `volumes/` | Docker volumes for persistent data storage (Database data, Ollama models). |
| `whisper-stt/` | Service for Speech-to-Text processing using OpenAI Whisper. |

## Service Directories

### `orchestrator/`
The brain of the system.
- `app/`: Main application code.
  - `agents/`: Definitions for Dialogue, SPARQL, SQL, Analytics, and Visualization agents.
  - `core/`: Core logic, configuration, and shared utilities.
  - `models/`: Pydantic models and database schemas.
  - `api/`: API route definitions.

### `rag-service/`
Handles knowledge retrieval.
- `app/`: Application code.
  - `embeddings/`: Logic for generating text embeddings.
  - `vector_store/`: Interface for Qdrant vector database.
  - `retriever/`: Logic for semantic search and context retrieval.

### `frontend/`
The user interface.
- `src/`: Source code.
  - `components/`: Reusable UI components (Chat interface, 3D viewer).
  - `hooks/`: Custom React hooks.
  - `services/`: API client services.
  - `types/`: TypeScript type definitions.

### `code-executor/`
Sandboxed execution environment.
- `app/`: Application code.
  - `sandbox/`: Logic for isolating and running Python code safely.

### `whisper-stt/`
Voice processing.
- `app/`: Application code.
  - `audio/`: Audio processing utilities.
  - `model/`: Whisper model management.

## Data & Configuration

### `Assets/`
- `*.json`: Raw and processed datasets for buildings.
- `*.ipynb`: Jupyter notebooks used for data cleaning and preparation.

### `volumes/`
*Note: This directory is often excluded from version control but is crucial for local state.*
- `qdrant_data/`: Vector database storage.
- `postgres_data/`: PostgreSQL database storage.
- `ollama/`: Local LLM models.

## Key Configuration Files

- `.env`: Environment variables (API keys, ports, service URLs).
- `pyproject.toml` / `requirements.txt`: Python dependency definitions (found in service subfolders).
- `Dockerfile`: Build instructions for each service (found in service subfolders).
