#!/usr/bin/env bash
# Health sweep for OntoBot services (Linux/macOS/WSL/Git Bash)
# Usage:
#   TIMEOUT=5 ./scripts/check-health.sh
# or
#   ./scripts/check-health.sh  # defaults to TIMEOUT=5

set -u
TIMEOUT="${TIMEOUT:-5}"

endpoints=(
  "Visualiser|http://localhost:8090/health"
  "API|http://localhost:8091/health"
  "ThingsBoard|http://localhost:8082/"
  "pgAdmin|http://localhost:5050/"
  "Jena Fuseki|http://localhost:3030/$/ping"
  "GraphDB|http://localhost:7200/"
  "Jupyter|http://localhost:8888/"
  "Adminer|http://localhost:8282/"
  "Microservices|http://localhost:6001/health"
  "Rasa|http://localhost:5005/version"
  "Action Server|http://localhost:5055/health"
  "Duckling|http://localhost:8000/"
  "File Server|http://localhost:8080/health"
  "NL2SPARQL|http://localhost:6005/health"
  "Ollama|http://localhost:11434/api/version"
)

trim() { echo "$1" | tr -d '\r\n' ; }
shorten() { local s; s=$(echo -n "$1" | tr -d '\r\n'); echo -n "${s:0:120}"; [ ${#s} -gt 120 ] && echo -n '...'; }

for entry in "${endpoints[@]}"; do
  name="${entry%%|*}"
  url="${entry#*|}"
  # fetch body (ignore SSL bc local, expect http)
  body=""
  err=""
  if ! body=$(curl -sS --max-time "$TIMEOUT" "$url" 2> >(err=$(cat); typeset -p err >/dev/null)); then
    printf "%-16s %s  %s\n" "$name" "FAIL" "$url"
    continue
  fi
  code=$(curl -sS -o /dev/null -w "%{http_code}" --max-time "$TIMEOUT" "$url" || echo "000")
  printf "%-16s %s %s  %s\n" "$name" "$code" "$url" "$(shorten "$body")"
done
