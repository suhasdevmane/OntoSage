# `scripts/` — Operational & QA CLI Tools

Standalone, runnable command-line tools (not pytest). Run them from the repo
root with the stack up (`docker-compose up -d`) unless noted otherwise.

> **Folder rule:** anything here is a script you *run* (`python scripts/x.py`).
> Automated pytest suites live in [`../tests/`](../tests/README.md).

---

## ⭐ QA / live system testing

These send real questions to the running orchestrator and grade the responses.

| Script | What it does |
|---|---|
| **`ontosage_qa_suite.py`** | **THE canonical QA battery.** Unified merge of `survey_live_test` + `pipeline_test_openwebui`: every persona × every intent, single- and multi-intent, multi-turn co-reference + carry-forward, all pipeline components, edge cases. Writes a **timestamped** `results/qa_run_<ts>.json` + `.md` per run (nothing overwritten). **Use this to check OntoSage and triage bugs.** |
| `survey_live_test.py` | Legacy "Survey v4" — 95-question deterministic check across intents (`/chat`). Superseded by `ontosage_qa_suite.py`; kept for the historical baseline. |
| `pipeline_test_openwebui.py` | Legacy heavy harness — 100+ questions, 10 personas, multi-turn chains, coverage matrices (`/v1/chat/completions`). Superseded by `ontosage_qa_suite.py`. |
| `forecast_live_test.py` | Focused live test of the forecasting pipeline (model selection, horizon, metrics). |
| `evaluate_survey_questions.py` | Bulk evaluator — runs hundreds/thousands of questions from a CSV through the system. |
| `review_test_suite.py` | Live review suite: routing, capability KB, multi-intent, persona, edge, performance. |
| `ttl_gap_audit.py` | Audits a representative sample of questions to find ontology/SPARQL coverage gaps. |

**Quick start:**
```bash
python scripts/ontosage_qa_suite.py            # full battery → results/qa_run_<timestamp>.{json,md}
python scripts/ontosage_qa_suite.py --quick    # ~1/3 sample, fast smoke
python scripts/ontosage_qa_suite.py --category analytics       # one category
python scripts/ontosage_qa_suite.py --persona facility_manager # one persona
```

## 🏢 Building lifecycle

| Script | What it does |
|---|---|
| `onboard_building.py` | Building onboarding CLI — interactive or `--non-interactive`; validates the ontology and generates a building config. (CI exercises the non-interactive path.) |
| `swap_building.py` | **Canonical "switch the active building" CLI** (Phase 12C). Validates TTL ↔ namespace consistency, updates `.env`, archives the old dir, flushes the response cache. `--to <id> --dry-run` / `--archive`. |

## 🎛️ Tuning, calibration & corpus

| Script | What it does |
|---|---|
| `calibrate_intent_routing.py` | Calibrate per-building `capability_routing` thresholds for the active embedding provider. |
| `capture_baseline.py` | Snapshot pre-flight baseline artefacts (capability semantic-routing migration). |
| `export_production_corpus.py` | Export production traffic from Qdrant `user_memory` as a G1 six-tuple corpus. |
| `fine_tune_manager.py` | Federated model fine-tuning manager. |
| `cache_sensor_map.py` | Build/refresh the sensor label-map cache used to humanise UUIDs in responses. |

## 🗄️ Migration (historical — kept for context)

| Script | What it does |
|---|---|
| `phase2_enable_and_validate.py` | **Historical** — controlled a feature flag removed in Phase 3 cleanup. |
| `phase3_cleanup.py` | Phase 3 cleanup — removed legacy keyword routing once semantic routing became the single source of truth. |

## 🔧 Shell / SQL helpers

| File | What it does |
|---|---|
| `switch-model.ps1` / `switch-provider.ps1` | PowerShell helpers to switch the LLM model / `MODEL_PROVIDER`. |
| `verify_services.sh` | Bash health-check across the service stack. |
| `sql/` | Admin SQL (e.g. report-intake triage views). |

---

### Output convention
The QA suite writes to `../results/` with a per-run timestamp (`qa_run_YYYYMMDD_HHMMSS.json` + `.md`). That folder is git-ignored — results are local artefacts for your review, not committed.
