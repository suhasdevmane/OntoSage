# OntoBot Deploy Configs

This branch contains deployment-oriented configuration and container manifests only. Use it to provision and run OntoBot stacks without application source.

## Included

- Root compose files:
  - `docker-compose.bldg1.yml`, `docker-compose.bldg2.yml`, `docker-compose.bldg3.yml`
  - `docker-compose.extras.yml`, `docker-compose.pg.yml`, `docker-compose.ts.yml`, `docker-compose.cassandra.yml`
  - `docker-compose.rasatrain.yml`, legacy `docker-compose.yml`
- Service-specific compose/Dockerfiles:
  - `rasa-bldg1/`, `rasa-bldg2/`, `rasa-bldg3/` compose files
  - `microservices/Dockerfile`, `decider-service/Dockerfile`, `rasa-frontend/Dockerfile`
  - `rasa-bldg*/actions/Dockerfile`, `Transformers/*/Dockerfile`
- Sample environment file: `.env.example`

## Usage

1. Copy `.env.example` to `.env` and adjust values.
2. Choose a building stack and bring it up:

```powershell
# Building 1 (ABACWS)
docker-compose -f docker-compose.bldg1.yml up -d --build

# With optional language services
docker-compose -f docker-compose.bldg1.yml -f docker-compose.extras.yml up -d --build
```

3. Access services:
- Frontend: http://localhost:3000
- Fuseki: http://localhost:3030
- Analytics: http://localhost:6001/health
- Rasa: http://localhost:5005/version

Run only one building stack at a time to avoid port conflicts.

## Notes
- This branch intentionally omits application code and datasets.
- Point services at external NL2SPARQL / LLM endpoints if preferred (see `.env.example`).