# Decider Service

Single endpoint that decides whether to perform analytics for a user question and, if yes, which analytics function to apply.

- POST /decide
  - Request: { "question": "..." }
  - Response: { "perform_analytics": boolean, "analytics": string|null }

When ML models are absent, the service falls back to robust rule-based logic.

## Training

1) Generate dataset from the T5 corpus:
- Run data/generate_decider_data.py to create data/decider_training.auto.jsonl

2) Train models:
- python training/train.py --data data/decider_training.auto.jsonl
- Models and vectorizers will be saved under decider-service/model/

## Run

- Build and run via Docker:
- docker build -t decider-service .
- docker run -p 6009:6009 decider-service

Or use uvicorn locally:
- uvicorn app.main:app --reload --port 6009

## Env overrides

- DECIDER_PERFORM_MODEL_PATH
- DECIDER_PERFORM_VECT_PATH
- DECIDER_LABEL_MODEL_PATH
- DECIDER_LABEL_VECT_PATH
