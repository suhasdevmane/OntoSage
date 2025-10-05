# OntoBot Port Reference

Unified host port scheme (only one building stack runs at a time). Internal container ports are listed where they differ or are noteworthy.

| Service | Host Port | Container Port | Compose Files | Notes |
|---------|-----------|----------------|---------------|-------|
| Rasa | 5005 | 5005 | bldg1, bldg2, bldg3 | Core conversational engine (/version) |
| Rasa Action Server | 5055 | 5055 | bldg1, bldg2, bldg3 | Custom actions (/health) |
| Duckling | 8000 | 8000 | bldg1, bldg2, bldg3 | Entity extraction |
| Rasa Frontend | 3000 | 3000 | bldg1, bldg2, bldg3 | React dev server |
| Rasa Editor | 6080 | 6080 | bldg1, bldg2, bldg3 | Editor API (/health) |
| HTTP File Server | 8080 | 8080 | bldg1, bldg2, bldg3 | Serves artifacts (/health) |
| Analytics Microservices | 6001 | 6000 | bldg1, bldg2, bldg3 | Host offset; internal Flask app (/health) |
| Decider Service | 6009 | 6009 | bldg1, bldg2, bldg3 | Decision endpoint (/health) |
| Jena Fuseki | 3030 | 3030 | all | SPARQL triple store ($/ping) |
| ThingsBoard UI | 8082 | 9090 | bldg1, bldg2, bldg3 | ThingsBoard web UI |
| ThingsBoard HTTP Transport | 8081 | 8081 | bldg1, bldg2, bldg3 | Device HTTP telemetry ingress |
| MQTT (TB) | 1883/1884* | 1883 | bldg1 (1883), bldg2 (1883), bldg3 (1884) | bldg3 uses 1884 host for clarity |
| CoAP (TB) | 5683-5688 / 5689-5694* | 5683-5688 | bldg1, bldg2, bldg3 | bldg3 uses shifted host range |
| TB Alt Ports | 7070/7071* | 7070 | bldg1 (7070), bldg2 (7070), bldg3 (7071) | Minor differentiation in bldg3 |
| TimescaleDB | 5433 | 5432 | bldg2 | SQL telemetry (Timescale extension) |
| Postgres (TB metadata) | 5434 | 5432 | bldg3 | TB entities when using Cassandra telemetry |
| Cassandra | 9042 | 9042 | bldg3 | Telemetry backend (CQL) |
| MySQL (legacy) | 3307 | 3306 | bldg1, bldg2 | Legacy / migration DB |
| pgAdmin | 5050 / 5051 | 80 | bldg1, bldg2 (5050), optional bldg3 (5051) | Web admin UI |
| NL2SPARQL | 6005 | 6005 | extras, all stacks | T5 model service (/health) |
| Ollama (Mistral) | 11434 | 11434 | extras, all stacks | LLM runtime (EXPOSE added) |
| GraphDB (optional) | 7200 | 7200 | extras | Alternate RDF store |
| Jupyter Lab (optional) | 8888 | 8888 | extras | Notebook environment |
| Ontology Viewer (optional) | 8089 | 8089 | extras | Supplementary UI |
| Adminer (optional) | 8282 | 8080 | extras | DB browser; container internal 8080 |

*Ports with asterisk vary slightly in bldg3 for coexistence history; since only one stack runs, they could be normalized later if desired.

## Rationale
- Host offset for analytics (6001→6000) avoids conflicts if future internal services also use 6000.
- Unified host ports simplify documentation and local scripts.
- External protocol ports (MQTT/CoAP) retain slight variation for historical separation; safe to normalize.

## Suggested Future Normalizations (Optional)
| Current | Suggested | Reason |
|---------|-----------|--------|
| MQTT bldg3 host 1884 | 1883 | Consistency across stacks |
| CoAP bldg3 host 5689-5694 | 5683-5688 | Consistency, reduce cognitive load |
| TB 7071 (bldg3) | 7070 | Consistency |

Apply only if you no longer need to differentiate historical captures.

## Health Endpoints Quick List
```
Rasa:                /version
Action Server:       /health
Analytics:           /health
Decider:             /health
File Server:         /health
Fuseki:              $/ping
NL2SPARQL:           /health
Ollama:              ollama ps (CLI) or HTTP /api/tags
```

## Updating This File
If you change any compose mapping or add a new service, update this table to keep operator knowledge current.
