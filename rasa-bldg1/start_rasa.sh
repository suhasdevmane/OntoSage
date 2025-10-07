Transformers\Mistral#!/usr/bin/env bash
set -euo pipefail
PIN_FILE="/app/shared_data/pinned_model.txt"
BASE_CMD=(rasa run --cors "*" --enable-api)
if [[ -f "$PIN_FILE" ]]; then
  MODEL_NAME=$(tr -d '\r\n' < "$PIN_FILE" || true)
  if [[ -n "$MODEL_NAME" && -f "/app/models/$MODEL_NAME" ]]; then
    echo "[start_rasa] Starting Rasa with pinned model: $MODEL_NAME"
    exec "${BASE_CMD[@]}" --model "/app/models/$MODEL_NAME"
  else
    echo "[start_rasa] Pinned model not found or invalid ('$MODEL_NAME'). Starting with latest available model."
    exec "${BASE_CMD[@]}"
  fi
else
  echo "[start_rasa] No pinned model. Starting with latest available model."
  exec "${BASE_CMD[@]}"
fi
