# `tests/` — Automated Test Suite (pytest)

Automated tests run with `pytest`. Two broad classes:

- **Deterministic** — no external services; mocks/fixtures only. These run in CI
  on the Python 3.10 / 3.11 / 3.12 matrix.
- **Live e2e** — POST to a *running* orchestrator on `localhost:8000`. Excluded
  from CI; run them manually after `docker-compose up -d`.

> **Folder rule:** everything here is a pytest module (`test_*.py`) or its
> fixtures/helpers. Runnable QA *scripts* live in [`../scripts/`](../scripts/README.md).
> For interactive, response-grading QA across personas/intents, use
> **`../scripts/ontosage_qa_suite.py`**.

---

## Running

```bash
pytest tests/ -v                       # everything (live tests need the stack up)
pytest -m unit                         # fast, no external services
pytest -m integration                  # requires Docker services
pytest tests/test_routing_accuracy.py -v
pytest tests/ --cov=orchestrator --cov-report=html
```

## CI deterministic suite (the gate — `.github/workflows/ci.yml`)

Runs on every push/PR across 3.10/3.11/3.12 (**251 tests**). Includes, among others:

`test_phase3_4_services.py`, `test_coreference_rewrite.py`, `test_blended_persona.py`,
`test_compound_query_e2e.py`, `test_intent_graph_autowire.py`, `test_multi_tenant_fixture.py`,
`test_routing_accuracy.py`, `test_state_persistence.py`, `test_swap_building.py`,
`test_unregistered_intent_safety_net.py`, `test_workflow_wiring.py`,
`test_survey_aligned_phases.py`, `test_phase_a_fixes.py`, `services/test_ttl_validator.py`,
`test_turn_memory.py`, `test_conversation_memory_e2e.py`.

A separate CI job runs `test_integration_mock_building.py` (mocked LLM + real services).

## Live e2e tests (NOT in CI — need the running stack)

These POST to `localhost:8000` via the shared `fixtures/live_chat_client.py`:

| File | Covers |
|---|---|
| `test_capability_e2e.py` | Capability semantic routing, end-to-end |
| `test_capability_edge_cases.py` | Adversarial / boundary inputs route safely |
| `test_floor_plan_e2e.py` | Floor-plan query path (PDF → manifest → response) |
| `test_non_regression_intents.py` | One canonical query per intent — routing didn't regress |
| `test_ontology_integrity.py` | Discovery → SPARQL → GraphDB integrity |

## Benchmarks (runnable, not gated)

| File | Measures |
|---|---|
| `rag_benchmark.py` | Answer **quality** across 30 canonical building questions |
| `performance_benchmark.py` | System **performance** under realistic load |

## Layout

| Path | Contents |
|---|---|
| `conftest.py` | Shared fixtures + pytest config |
| `fixtures/` | `live_chat_client.py`, ontology fixtures, building fixtures (`buildings/bldg2`) |
| `services/` | Service-level tests (e.g. `test_ttl_validator.py`) |
| `agents/`, `unit/`, `integration/`, `edge/`, `semantic/`, `perf/` | Grouped suites by layer |
| `baselines/`, `results/` | Reference baselines and generated reports |
| `example_queries.py` | Sample queries used by some tests |

## What runs where — quick guide

- **Pre-commit / PR confidence** → the CI deterministic list above (fast, offline).
- **Before a deploy / after pipeline changes** → the live e2e tests + the
  `scripts/ontosage_qa_suite.py` battery against a running stack.
- **Performance/quality tracking** → the two benchmarks.
