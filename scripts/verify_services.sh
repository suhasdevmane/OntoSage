#!/usr/bin/env bash
# OntoSage Service Health Verification Script
# Checks all active services and reports their status.
# Usage: bash scripts/verify_services.sh

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

PASS=0
FAIL=0
WARN=0

check_http() {
    local name="$1" url="$2" timeout="${3:-5}"
    printf "  %-25s " "$name"
    if response=$(curl -sf --max-time "$timeout" "$url" 2>&1); then
        echo -e "${GREEN}OK${NC}"
        ((PASS++))
        return 0
    else
        echo -e "${RED}FAIL${NC}  ($url)"
        ((FAIL++))
        return 1
    fi
}

check_tcp() {
    local name="$1" host="$2" port="$3" timeout="${4:-3}"
    printf "  %-25s " "$name"
    if (echo > /dev/tcp/"$host"/"$port") 2>/dev/null; then
        echo -e "${GREEN}OK${NC}"
        ((PASS++))
        return 0
    elif timeout "$timeout" bash -c "echo > /dev/tcp/$host/$port" 2>/dev/null; then
        echo -e "${GREEN}OK${NC}"
        ((PASS++))
        return 0
    else
        echo -e "${RED}FAIL${NC}  ($host:$port)"
        ((FAIL++))
        return 1
    fi
}

check_docker() {
    local name="$1" container="$2"
    printf "  %-25s " "$name"
    local status
    status=$(docker inspect --format='{{.State.Status}}' "$container" 2>/dev/null || echo "missing")
    local health
    health=$(docker inspect --format='{{if .State.Health}}{{.State.Health.Status}}{{else}}no-healthcheck{{end}}' "$container" 2>/dev/null || echo "unknown")

    if [[ "$status" == "running" ]]; then
        if [[ "$health" == "healthy" ]]; then
            echo -e "${GREEN}running (healthy)${NC}"
            ((PASS++))
        elif [[ "$health" == "no-healthcheck" ]]; then
            echo -e "${GREEN}running${NC}"
            ((PASS++))
        else
            echo -e "${YELLOW}running ($health)${NC}"
            ((WARN++))
        fi
    else
        echo -e "${RED}$status${NC}"
        ((FAIL++))
    fi
}

echo -e "${CYAN}================================================${NC}"
echo -e "${CYAN}  OntoSage Service Health Check${NC}"
echo -e "${CYAN}================================================${NC}"
echo ""

# ── Docker container status ──
echo -e "${CYAN}[1/5] Docker Container Status${NC}"
check_docker "Orchestrator"        "ontosage-orchestrator"
check_docker "RAG Service"         "rag-service-graphdb"
check_docker "Code Executor"       "code-executor"
check_docker "Redis"               "redis-memory-store"
check_docker "Qdrant"              "qdrant-vector-db"
check_docker "GraphDB"             "graphdb"
check_docker "PostgreSQL"          "postgres-user-data"
check_docker "MongoDB"             "mongo-chat-history"
check_docker "Data Publisher"      "data-publisher"
check_docker "File Server"         "file-server-artifacts"
echo ""

# ── HTTP health endpoints ──
echo -e "${CYAN}[2/5] HTTP Health Endpoints${NC}"
check_http "Orchestrator /health"  "http://localhost:8000/health"
check_http "RAG Service /health"   "http://localhost:8001/health"
check_http "Code Executor /health" "http://localhost:8002/health"
check_http "GraphDB repositories"  "http://localhost:7200/rest/repositories"
check_http "Qdrant health"         "http://localhost:6333/healthz"
echo ""

# ── Database connectivity ──
echo -e "${CYAN}[3/5] Database Connectivity${NC}"
check_tcp "Redis (6379)"           "localhost" 6379
check_tcp "PostgreSQL (5433)"      "localhost" 5433
check_tcp "MongoDB (27017)"        "localhost" 27017
check_tcp "MySQL host (3306)"      "localhost" 3306

# Verify MySQL sensordb accessible
printf "  %-25s " "MySQL sensordb table"
if docker exec ontosage-orchestrator python -c "
import pymysql
conn = pymysql.connect(host='host.docker.internal', port=3306, user='root', password='mysql', database='sensordb')
cur = conn.cursor()
cur.execute('SELECT COUNT(*) FROM sensor_data')
count = cur.fetchone()[0]
print(count)
conn.close()
" 2>/dev/null; then
    echo -e "${GREEN}OK${NC}"
    ((PASS++))
else
    echo -e "${YELLOW}SKIP${NC}  (cannot exec into orchestrator)"
    ((WARN++))
fi
echo ""

# ── GraphDB ontology ──
echo -e "${CYAN}[4/5] GraphDB Ontology Check${NC}"
printf "  %-25s " "GraphDB 'bldg' repo"
if response=$(curl -sf --max-time 5 "http://localhost:7200/rest/repositories/bldg/size" 2>&1); then
    echo -e "${GREEN}OK${NC}  (triples: $response)"
    ((PASS++))
else
    echo -e "${YELLOW}WARN${NC}  (repo may not exist yet)"
    ((WARN++))
fi
echo ""

# ── End-to-end smoke test ──
echo -e "${CYAN}[5/5] E2E Smoke Test (chat endpoint)${NC}"
printf "  %-25s " "POST /api/v1/chat"
if response=$(curl -sf --max-time 30 -X POST "http://localhost:8000/api/v1/chat" \
    -H "Content-Type: application/json" \
    -d '{"message":"hello","conversation_id":"healthcheck-test"}' 2>&1); then
    echo -e "${GREEN}OK${NC}"
    ((PASS++))
else
    echo -e "${YELLOW}WARN${NC}  (chat may require auth or LLM)"
    ((WARN++))
fi
echo ""

# ── Summary ──
echo -e "${CYAN}================================================${NC}"
TOTAL=$((PASS + FAIL + WARN))
echo -e "  Total checks: $TOTAL"
echo -e "  ${GREEN}Passed: $PASS${NC}"
[[ $WARN -gt 0 ]] && echo -e "  ${YELLOW}Warnings: $WARN${NC}"
[[ $FAIL -gt 0 ]] && echo -e "  ${RED}Failed: $FAIL${NC}"
echo -e "${CYAN}================================================${NC}"

if [[ $FAIL -gt 0 ]]; then
    echo -e "${RED}Some services are down. Check docker-compose logs.${NC}"
    exit 1
elif [[ $WARN -gt 0 ]]; then
    echo -e "${YELLOW}All core services OK, but some checks need attention.${NC}"
    exit 0
else
    echo -e "${GREEN}All services healthy!${NC}"
    exit 0
fi
