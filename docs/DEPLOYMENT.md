# Easy-Deploy Guide

**OntoSage** is built on an "Easy-Deploy" philosophy, allowing you to deploy a research-grade Agentic AI system for your smart building in minutes.

## Prerequisites

- **Docker Desktop** (Windows/Mac) or **Docker Engine** (Linux)
- **NVIDIA GPU Drivers** (Recommended for local LLM acceleration)
- **Git**

## 🚀 Quick Start (Zero-Knowledge Deployment)

OntoSage comes pre-configured with sensible defaults. You don't need to be a DevOps expert to get it running.

### 1. Clone the Repository
```bash
git clone https://github.com/suhasdevmane/OntoBot.git
cd OntoBot
```

### 2. Choose Your Mode
OntoSage supports two primary modes:
*   **Local Mode (Privacy-First)**: Runs entirely offline using Ollama (DeepSeek/Llama). No data leaves your network.
*   **Cloud Mode (Performance-First)**: Uses OpenAI's GPT-4 for maximum reasoning capability.

Copy the appropriate configuration:
```bash
# For Local Mode (Default)
cp .env.local .env

# For Cloud Mode
cp .env.cloud .env
# Edit .env and add your OPENAI_API_KEY
```

### 3. Launch with One Command
We use a unified Docker Compose configuration for the entire agentic stack.

```bash
docker-compose -f docker-compose.agentic.yml up -d
```

*Note: The first run will automatically download necessary AI models (approx. 10-20GB for local mode). Please be patient.*

## 🌐 Accessing the System

Once the containers are running, access the services via your browser:

| Service | URL | Description |
|---------|-----|-------------|
| **Open WebUI** | `http://localhost:3001` | **Main Interface** (Chat, Voice, Charts) |
| **Orchestrator API** | `http://localhost:8000/docs` | Backend API Swagger Documentation |
| **GraphDB Workbench** | `http://localhost:7200` | Ontology Management & Visualization |
| **RAG Service** | `http://localhost:8001/docs` | Knowledge Retrieval API |
| **Code Executor** | `http://localhost:8002/health` | Sandbox Status |

## 🔧 Custom Configuration (Optional)

While OntoSage works out-of-the-box, you can customize it for your specific building.

### Connecting Your Building Data
See the **[Building Onboarding Guide](BUILDING_ONBOARDING.md)** to learn how to mount your own `.ttl` ontology and SQL database without changing the code.

### Environment Variables
Key settings in `.env`:
- `OLLAMA_MODEL`: Change the local model (default: `deepseek-r1:32b`).
- `OPENAI_API_KEY`: Your API key for cloud models.
- `GRAPHDB_REPOSITORY`: Name of your building's repository in GraphDB.

## 🛠️ Troubleshooting

- **"Ollama is pulling model..."**: If the chat isn't responding immediately, check the Ollama logs:
  ```bash
  docker logs -f ollama-deepseek-r1
  ```
- **Port Conflicts**: If port 3001 or 8000 is taken, modify the `ports` section in `docker-compose.agentic.yml`.
- **GPU Not Detected**: Ensure you have the NVIDIA Container Toolkit installed if running in Local Mode on Linux/WSL2.
