# Transformers (Optional Services)

Optional AI services that can be enabled in `docker-compose.yml`.

## NL2SPARQL (T5)

- Purpose: Convert natural language questions into SPARQL queries.
- Service (commented in compose): `nl2sparql` on port 6005
- Health: GET `/health`
- Model: `Transformers/t5_base/trained/checkpoint-2` (mount via volume)
- Enable: uncomment the `nl2sparql` service block in `docker-compose.yml` and `docker-compose up -d nl2sparql`

## Ollama (Mistral)

- Purpose: Local LLM for summarization or general assistance.
- Service (commented in compose): `ollama` on port 11434
- GPU support via NVIDIA runtime; ensure drivers on host
- Enable: uncomment service block and run `docker-compose up -d ollama`

## Customize

- Swap models/checkpoints by adjusting volumes and environment variables in the compose service definitions.
- Add new endpoints or microservices here following the same pattern; keep healthchecks for reliability.