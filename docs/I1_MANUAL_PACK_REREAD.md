# I1 — re-reading the 73-question evidence pack (manual runbook)

This needs a real browser against the running stack. There is no way to do it from a terminal
session without one, so it's left for you to run.

## What exists already

- `scripts/capture_evidence_screenshots.py` — drives a real Chromium browser through Open WebUI,
  asks each question in a fresh chat, waits for the full answer, and saves a screenshot + the
  answer text. This is what built the original pack.
- `scripts/combine_evidence_packs.py` — merges two capture runs into one, de-duplicated by
  question (a question asked in both keeps the later capture).
- The two question lists the original 73 came from: `docs/evidence_questions.txt` (26) and
  `docs/evidence_questions_50.txt` (50) — three questions appear in both and are kept once.
- The existing pack to compare against: `docs/supervisor_evidence_pack/` (`INDEX.md`,
  `review.json`, `screenshots/`).

## One-time setup

```bash
pip install playwright   # if not already installed
playwright install chromium
```

## Steps

1. **Make sure the stack is up** and `bldg1` is active (`docker compose ps`, `curl
   http://127.0.0.1:8000/health`).
2. **Flush the three caches** so every answer is a genuine first pass, not a stale cache hit:
   ```bash
   for p in "resp_cache:*" "cache:sparql*" "cache:intent:*"; do
     docker exec redis-memory-store sh -c "redis-cli --scan --pattern '$p' | xargs -r redis-cli DEL"
   done
   ```
3. **Run the capture** (pick a role whose account exists in `user_credentials_bldg1.csv`, e.g.
   `facility01`):
   ```bash
   python scripts/capture_evidence_screenshots.py \
     --user facility01 \
     --questions docs/evidence_questions.txt \
     --out docs/supervisor_evidence_pack_rerun_26
   python scripts/capture_evidence_screenshots.py \
     --user facility01 \
     --questions docs/evidence_questions_50.txt \
     --out docs/supervisor_evidence_pack_rerun_50
   ```
   Each run takes a while — the original pack's median answer time was 100s, slowest 273s, over
   73 questions total.
4. **Combine the two runs**:
   ```bash
   python scripts/combine_evidence_packs.py \
     --packs docs/supervisor_evidence_pack_rerun_26 docs/supervisor_evidence_pack_rerun_50 \
     --out docs/supervisor_evidence_pack_rerun
   ```
5. **Read each answer by hand** against the question it was asked. For every one, you're deciding:
   does this answer actually answer the question, honestly, grounded in the building's own data?
   Write a verdict (`GOOD` / `WEAK` / `does not answer it` / `do not rely on`, matching the
   existing pack's vocabulary) in a `review.json` the same shape as the one in
   `docs/supervisor_evidence_pack/review.json`.
6. **Compare question-by-question against the old pack's verdicts** (`docs/supervisor_evidence_pack/INDEX.md`).
   What you're looking for:
   - A question that was `WEAK`/`does not answer it` before and is `GOOD` now — a real improvement,
     worth naming in `CLAUDE.md`'s next status update.
   - A question that was `GOOD` before and is worse now — a real regression, worth a new tracker row.
   - Anything that changed WITHOUT any code change targeting it — note it as the known
     answer-to-answer variance this project calls CAVEAT-891, not a mystery to chase.
7. **Write up the delta** — a short markdown file (model it on
   `docs/phase0/conversations_2026-10-02_read.md` for the tone) saying what moved, what didn't, and
   what's still wrong. That file is the actual deliverable; the raw captures are its evidence.

## What NOT to do

- Don't trust a single run — this project's own history has at least one case of the SAME question
  answering differently twice in a row (lesson in `tasks/lessons.md`, search "CAVEAT-891"). If a
  verdict surprises you, re-ask it once before writing it down.
- Don't let a label disagree with the stored answer beside it — lesson #131 in `tasks/lessons.md`
  is a prior instance of exactly that mistake, found by the regression gate reading the stored
  text rather than trusting the verdict.
