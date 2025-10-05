#!/usr/bin/env bash
set -euo pipefail

echo "[entrypoint] Starting Ollama server..."
ollama serve &
SERVE_PID=$!

trap 'echo "[entrypoint] Caught signal, forwarding to Ollama (PID $SERVE_PID)"; kill $SERVE_PID; wait $SERVE_PID || true' INT TERM

echo "[entrypoint] Waiting for Ollama API to become ready..."
ATTEMPTS=0
until ollama list >/dev/null 2>&1; do
  ATTEMPTS=$((ATTEMPTS+1))
  if [ $ATTEMPTS -gt 120 ]; then
    echo "[entrypoint][ERROR] Ollama did not become ready within timeout." >&2
    exit 1
  fi
  sleep 1
done
echo "[entrypoint] Ollama is responsive after $ATTEMPTS seconds."

# Models to auto-pull (space or comma separated); default mistral:7b
RAW_MODELS=${AUTO_PULL_MODELS:-mistral:7b}
# Normalize separators (commas -> spaces)
RAW_MODELS=${RAW_MODELS//,/ }

echo "[entrypoint] Models to pull: $RAW_MODELS"

for MODEL in $RAW_MODELS; do
  if [ -z "$MODEL" ]; then
    continue
  fi
  echo "[entrypoint] Ensuring model '$MODEL' is available..."
  if ollama list | awk '{print $1}' | grep -Fxq "$MODEL"; then
    echo "[entrypoint] Model '$MODEL' already present, skipping pull."
  else
    if ollama pull "$MODEL"; then
      echo "[entrypoint] Pulled '$MODEL' successfully."
    else
      echo "[entrypoint][WARN] Failed to pull '$MODEL'. Continuing with remaining models." >&2
    fi
  fi
done

# Optional warmup: generate a trivial token to load into memory
if [ "${WARMUP_MODELS:-true}" = "true" ]; then
  for MODEL in $RAW_MODELS; do
    echo "[entrypoint] Warming up '$MODEL' (short dummy prompt)..."
    if ollama run "$MODEL" "Warmup." >/dev/null 2>&1; then
      echo "[entrypoint] Warmup for '$MODEL' complete."
    else
      echo "[entrypoint][WARN] Warmup failed for '$MODEL'." >&2
    fi
  done
fi

echo "[entrypoint] All setup steps completed. Waiting on Ollama server PID $SERVE_PID..."
wait $SERVE_PID
echo "[entrypoint] Ollama server exited with status $?"