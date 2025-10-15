# Deploy Directory

Action Plan Ref: #8 Repository Refactor

This directory will hold production-focused assets (minimal Docker Compose, env templates, deployment scripts) distinct from development/training artifacts.

## Planned Contents
- `docker-compose.min.yml` – Slim runtime (Rasa, Actions, Fuseki, Analytics, Decider, File Server)
- `.env.example` – Minimal variable surface
- `compose.override.example.yml` – Optional performance tuning / GPU blocks
- `k8s/` (future) – Helm chart or raw manifests

## Rationale
Separating deploy-time artifacts from experimental scripts and datasets improves reproducibility, reduces container context size, and aligns with multi-environment promotion (dev → staging → prod).

## Next Steps
1. Extract current production subset from root compose files
2. Provide a make/PowerShell task wrapper for smoke checks
3. Add image tagging + SBOM generation (optional)
