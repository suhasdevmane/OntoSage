This project is under development. Drop a message to access all models from huggingface and all versions of datasets. 




Create a python virtual environment to access different APIs.
```
python -m venv ./abacws-chatbot-venv
```
to activate environment
```
./abacwsenvs/Scripts/activate
c:/_PHD_/Github/abacws-chatbot/abacws-chatbot-venv/Scripts/activate.bat
```

Upgrade pip
```
 python.exe -m pip install --upgrade pip
```

Install dependencies
pip install -r requirements.txt
python -m spacy download en_core_web_sm

# To start this project use docker-compose file and turn ON all services using
```
docker-compose up
```
# To see all services and access GUI oprn index.html in your browser

# Abacws Data Visualiser
Web application made to visualise IoT data for devices in the Abacws building at Cardiff University.\
This repository contains the API and the Visualiser tool, both of which are deployed using [docker](https://www.docker.com/).

Production deployments for these tools can be found at the following locations:
- [API](https://abacws.ggrainger.uk/api/)
- [Visualiser](https://abacws.ggrainger.uk/)

## Docs
You can view the documentation for the two separate services in their respective README files.
- [API](./api/README.md)
- [Visualiser](./visualiser/README.md)

## Docker compose for Abacws Data Visualiser
We recommend using docker compose to deploy this to your own server alongside [traefik](https://traefik.io/traefik/).\
An example compose file can be seen below.

# thingsboard/tb-postgres
ThingsBoard is an open-source IoT platform for data collection, processing, visualization, and device management.

Before starting Docker container run following commands to create a directory for storing data and logs and then change its owner to docker container user, to be able to change user, chown command is used, which requires sudo permissions (command will request password for a sudo access):
```
$ mkdir -p ~/.mytb-data && sudo chown -R 799:799 ~/.mytb-data
$ mkdir -p ~/.mytb-logs && sudo chown -R 799:799 ~/.mytb-logs
```
Execute the following command to run this docker seperately:

$ docker run -it -p 9090:9090 -p 1883:1883 -p 7070:7070 -p 5683-5688:5683-5688/udp -v ~/.mytb-data:/data -v ~/.mytb-logs:/var/log/thingsboard --name mytb --restart always thingsboard/tb-postgres

Where:
```
docker run - run this container
-it - attach a terminal session with current ThingsBoard process output
-p 9090:9090 - connect local port 9090 to exposed internal HTTP port 9090
-p 1883:1883 - connect local port 1883 to exposed internal MQTT port 1883
-p 7070:7070 - connect local port 7070 to exposed internal Edge RPC port 7070
-p 5683-5688:5683-5688/udp - connect local UDP ports 5683-5688 to exposed internal COAP and LwM2M ports
-v ~/.mytb-data:/data - mounts the host's dir ~/.mytb-data to ThingsBoard DataBase data directory
v ~/.mytb-logs:/var/log/thingsboard - mounts the host’s dir ~/.mytb-data to ThingsBoard logs directory
--name mytb - friendly local name of this machine
--restart always - automatically start ThingsBoard in case of system reboot and restart in case of failure.
thingsboard/tb-postgres - docker image
```

After executing this command you can open http://{yor-host-ip}:9090 in your browser. You should see ThingsBoard login page. Use the following default credentials:
```
Systen Administrator: sysadmin@thingsboard.org / sysadmin
Tenant Administrator: tenant@thingsboard.org / tenant
Customer User: customer@thingsboard.org / customer
You can always change passwords for each account in account profile page.

```
## Add your data to the thingsboard devices to talk to the building in natural language and receive data from the database.

<div align="center">

# OntoBot

Abacws SmartBot platform: a full-stack setup for IoT data visualisation, knowledge graph querying, and conversational AI. It orchestrates 3D visualisation, APIs, Rasa chatbot with custom actions, semantic stores (Jena Fuseki, GraphDB), data tools (ThingsBoard, pgAdmin, Adminer, Jupyter), and AI services (NL2SPARQL, Ollama/Mistral) via Docker Compose.

</div>


## Contents

- Overview
- Architecture at a glance
- Quick start
- Services & endpoints
- Health checks & scripts
- Development workflow
- Troubleshooting & tips
- License


## Overview

OntoBot brings together building IoT telemetry, semantic web components, and a conversational interface. The system lets you:

- Visualise building/device data in 3D
- Query RDF stores (SPARQL) and expose REST APIs
- Interact via a Rasa chatbot with custom action server
- Manage IoT devices and telemetry via ThingsBoard
- Run notebooks and data analysis in Jupyter
- Leverage AI helpers (NL2SPARQL, local LLM via Ollama)


## Architecture at a glance

High‑level components (see `docker-compose.yml` for full details):

- Visualiser (React + Nginx) and 3D API (Express) backed by MongoDB
- ThingsBoard (IoT) with a dedicated Postgres instance and pgAdmin
- Semantic stores: Jena Fuseki and GraphDB
- Microservices (Flask) and lightweight file server (Flask)
- Rasa stack: Rasa, Action Server, Duckling
- AI services: NL2SPARQL (T5 Flask), Ollama (Mistral model)

All services are networked inside the `ontobot-network` and expose convenient localhost ports for development.


## Quick start

Prerequisites:

- Docker Desktop (Windows/macOS) or Docker Engine (Linux)
- Optional: Python 3.9+ for local scripts (not required when using Docker)

Start all services:

```powershell
# From the repo root
docker-compose up -d
```

Stop all services:

```powershell
docker-compose down
```

Rebuild a service (example: frontend):

```powershell
docker-compose up rasa-frontend --build
```


## Services & endpoints

This table summarises primary UIs and health endpoints. These reflect the compose file in this repo.

- Visualiser (React + Nginx)
  - UI: http://localhost:8090/
  - Health: http://localhost:8090/health
- API (Express)
  - Base: http://localhost:8091/
  - Health: http://localhost:8091/health
- ThingsBoard (IoT)
  - UI: http://localhost:8082/
- pgAdmin
  - UI: http://localhost:5050/
- Jena Fuseki
  - Ping: http://localhost:3030/$/ping
- GraphDB
  - UI: http://localhost:7200/
- Jupyter
  - UI: http://localhost:8888/
- Adminer
  - UI: http://localhost:8282/
- Microservices (Flask)
  - Health: http://localhost:6001/health
- Rasa Server
  - Version: http://localhost:5005/version
- Rasa Action Server
  - Health: http://localhost:5055/health
- Duckling
  - Root: http://localhost:8000/ (page contains "Duckling")
- File Server (Flask)
  - Health: http://localhost:8080/health
- NL2SPARQL (T5)
  - Health: http://localhost:6005/health
- Ollama (Mistral)
  - Version: http://localhost:11434/api/version

Notes:

- ThingsBoard is exposed on host port 8082 to avoid clashes with the file server (8080).
- Health endpoints consistently return HTTP 200 with a small JSON body, except UI pages which render HTML.


## Health checks & scripts

Compose healthchecks are configured for core services (API, Visualiser, Microservices, Rasa, Action Server, Duckling, NL2SPARQL, Ollama, http_server). Docker will mark a service healthy once its endpoint responds.

For a quick, cross‑platform sweep of everything:

- Windows PowerShell: `scripts/check-health.ps1`
  - Run: `pwsh -NoProfile -File scripts/check-health.ps1`
- Bash (Linux/macOS/WSL): `scripts/check-health.sh`
  - Run: `TIMEOUT=5 ./scripts/check-health.sh`

Each prints Service, Status, URL, and a short body snippet.


## Development workflow

- Frontend (development server): http://localhost:3000
  - Container: `rasa-frontend` (auto‑reload via volume mount)
- API & Visualiser
  - Source under `Abacws/api` and `Abacws/visualiser` (Dockerfiles included)
- Rasa + Actions
  - Config under `rasa-ui/` (volumes mounted into containers)
- Microservices & File server
  - `microservices/` and `rasa-ui/file_server.py` (simple Flask apps)

Optional local Python setup (for scripts/tools):

```powershell
python -m venv ./.abacws-venv
./.abacws-venv/Scripts/Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```


## ThingsBoard notes

- Defaults (change in production):
  - Postgres DB: `thingsboard`
  - Postgres user: `thingsboard`
  - Postgres password: `thingsboard`
- Common management commands:
  - Logs: `docker-compose logs -f mytb`
  - Start/stop: `docker-compose start mytb` / `docker-compose stop mytb`
- Data & logs on host (Linux/WSL paths used by compose):
  - `~/.mytb-data` and `~/.mytb-logs`


## Troubleshooting & tips

- Port 8080 conflict: this repo maps ThingsBoard UI to 8082; ensure you use http://localhost:8082
- Containers not healthy: run the health script or open the health URLs directly
- Networking: all services are attached to `ontobot-network` for internal DNS resolution
- Inspect container IPs (if needed):
  - `docker network inspect ontobot-network`
  - `docker ps --format "table {{.ID}}\t{{.Names}}\t{{.Networks}}"`


## License

This project is provided under the terms of the repository’s LICENSE file. Unless otherwise noted, third‑party components retain their respective licenses.


use system- postgreSQL

Server-mytb

Username- thingsboard

password-  postgres
