# OntoSage — LLM Model Benchmarks (running log)

Record of local LLMs evaluated as OntoSage's primary reasoning model, over time.
Kept for reproducibility and for the paper. Append a new row/section per model tested;
never rewrite history — supersede with a dated entry.

**Hardware (all runs below):** NVIDIA GeForce RTX 4090 **Laptop** GPU, **16 GB VRAM**, Windows 11.
**Provider:** `MODEL_PROVIDER=local` (Ollama on host, `http://host.docker.internal:11434`).
**Embeddings:** `bge-large-en-v1.5` (1024-d), unchanged across LLM swaps.
**Grader:** heuristic (no `OPENAI_API_KEY` set) — same grader as the June 2026 baseline, so cross-run comparison is fair. PASS = `answered-with-data` ∪ `honest-capability-answer`.
**Harness:** `scripts/corpus_replay.py` (240-question stratified sample, 40 per latent level L1–L6, seed 42). Checkpointed CSVs in `scripts/outputs/replay/`.

---

## Summary table

| Date | Model | Size (GB) | GPU fit | Raw tok/s | Corpus pass | Sample | Avg lat | Median | 120s timeouts | Notes |
|---|---|---|---|---|---|---|---|---|---|---|
| 2026-06-18 | gemma4:26b | 18.2 | 74% (CPU offload) | 62 | 63.8% | 240 | — | — | — | pre-capability-KB baseline (paper §6.5 ≈ 63.9%) |
| 2026-07-19 | gemma4:26b | 18.2 | 74% (CPU offload) | 62 | **82.9%** | 240 | 17.7s | 0.9s | **10** | after capability KB + OCBV + graph resolver + bge-large |
| 2026-07-19 | gpt-oss:20b | 12.7 | **100% (full GPU)** | 109 | **91.7%** | 60 | 3.0s | 0.4s | **0** | fast sample; fully on GPU |
| 2026-07-19 | gpt-oss:20b | 12.7 | 100% (full GPU) | 109 | **93.3%** | 240 | 3.4s | 0.4s | **0** | authoritative run (`gptoss_full240`); **0 wrong**, 16 deflected (~11 correct control-declines + ~5 genuine gaps) |

### gpt-oss:20b full-240 breakdown (2026-07-19)

By latent level: L1 95% · L2 98% · **L3 100%** · L4 95% · L5 98% · **L6 75%**.
Grades: 114 answered-with-data + 110 honest-capability-answer (PASS) · 16 deflected · **0 wrong** · **0 timeouts**.

**All 16 fails are `deflected` (declined), none wrong or timed-out.** Categorised:
- **~11 correct control/actuation declines** — e.g. "how to control pressure?", "lower the curtains", "pipe music to the room", "automatically adjust temperature". OntoSage *correctly* refuses to operate the building (read-only by design); the heuristic grader marks these FAIL but they are the intended behaviour. **Excluding these, effective answer-quality ≈ 96.6%.**
- **~5 genuine gaps**, of which ~2–3 are actually answerable with existing data (quick wins):
  - `"wind strong?"` — a weather feed (`outside_weather_wind`) exists → routing/answer gap.
  - `"Can you show me a quiet spot to work?"` — answerable from noise sensors + spatial → gap.
  - `"how quickly does it detect a leak?"` — sensor-spec question.
  - `"Do you have a name?"` — persona/meta.
  - `"How much is a soda at the vending machines?"` — no such data (arguably a *correct* honest decline).

> Models listed in the Ollama library but **not installed** (so untested here): `gemma4:12b` (7.6 GB), `gemma4:e4b` (9.6 GB), `gemma4:e2b` (7.2 GB), `gemma4:31b` (20 GB). The `-mlx` variants are Apple-Metal only (won't run on Windows/NVIDIA). `e2b`/`e4b` = Gemma "effective 2B/4B" small variants.

---

## Decisions

- **2026-07-19 — Primary model set to `gpt-oss:20b`** (was `gemma4:26b`). Rationale: on 16 GB VRAM the 26b spills to CPU (74% GPU) and is ~6× slower; gpt-oss:20b fits fully (100% GPU), is faster *and* scored higher, and eliminated the analytics 120s timeouts (BUG-046). Default set in `shared/config.py`, `.env.example`, `docker-compose.yml`; admin-overridable via `OLLAMA_MODEL` / the AI & Models tab.

## Method notes

- Latency = wall time per `/v1/chat/completions` call (full pipeline: dialogue → SPARQL/SQL/analytics → response). `REQUEST_TIMEOUT=120s`; a timeout is graded `wrong`.
- Raw tok/s measured separately via `POST /api/generate` (`num_predict=160`), a pure generation-rate probe independent of the pipeline.
- GPU fit from `GET /api/ps` (`size_vram / size`). <100% ⇒ CPU offload ⇒ large latency penalty, worse on long system prompts.
- To reproduce: `python scripts/corpus_replay.py --sample 240` (auth auto-loads `PIPELINE_API_KEY` from `.env`).
