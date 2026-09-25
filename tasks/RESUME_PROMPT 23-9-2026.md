# Resume prompt — OntoSage production plan

Paste everything between the rules below into a new chat to pick this work up.
Last updated **2026-09-23** after the third session of Waves 1–2.

---

Resume the OntoSage production plan. Everything below is the state I paused at — read the
listed files before doing anything, and correct me if any of it has gone stale.

## Read first, in this order

1. `CLAUDE.md` — the orientation block at the top is current as of 2026-09-23; the workflow
   rules at the bottom govern how to work here (especially rule 8, park before any commit).
2. `tasks/PRODUCTION_TRACKER.csv` — the live plan. 32 rows. `Status`, `Depends_on`, `Notes`.
3. `tasks/FIX_TRACKER.csv` — the live defect log, ~888 rows. Read the OPEN ones.
4. `docs/PRODUCTION_PLAN_2026-09-22.md` — the plan the tracker came from, including the two
   standing decisions **D1** (all data is treated as real; `ontosage:isSimulated` is gone) and
   **D2** (no role-based access gating for now).
5. `tasks/lessons.md` — read **#133, #135, #136, #138, #139, #140, #141**. They are the
   working method, not trivia.

## Where things stand

- **14 of 32 rows DONE**, 2 PARTIAL (W1-04, W2-03). Waves 0–2 are essentially complete.
- `pytest -m unit` — **12,594 pass / 48 skip / 3 xfail / 0 fail** with bldg1 ACTIVE.
- Answerability gate — **50 of 51** (`python scripts/regression_answerability.py`). The one
  failure is **BUG-866**, pre-existing and narrowed but not fixed.
- **NOTHING IS COMMITTED.** Last commit is `5dfad54`; ~227 files are modified or new. The work
  lives in the working tree — do not reset, clean, or stash without asking me.
- bldg1 is the ACTIVE building and the stack should be up (`curl localhost:8000/health`). If
  it is not, follow the "Run building N" procedure in `CLAUDE.md`.
- The PARKED suite number is still owed — it has never been re-measured this month, and it is
  the number that actually gates a commit.

## The working method that made this session productive

**Before building what a tracker row asks for, ask the running system the question and grep for
the capability by its PURPOSE rather than its name.** Six rows in a row turned out to be asking
for something already built, where only the routing to it was missing. The deliberation lane was
the "multi-read lane"; `deliberation/coverage_audit.py` was W1-05's "one SPARQL"; 
`evidence/matched_comparison.py` was W1-04's comparison arithmetic. A lane that works and a lane
nobody can reach produce the identical symptom.

Also: verify every number against the store before accepting it (a floor comparison was checked
against MySQL directly), and treat the measuring instruments as suspects — the answerability
gate's own classifier was wrong three times in one day.

## What I recommend doing next, and why

**Start with BUG-879.** It is the highest-leverage open item: the aggregate lane refuses any
question that names a place (`summary_ok` requires `not names_a_place(question)`), and that one
gate is what still blocks BOTH partial rows:

- **W1-04** — two-period comparison works at building scope and declines for a named room.
- **W2-03** — with binding fixed, the system now asserts *"Floor 3 is warmer than Floor 4"*
  twice in bold from a **0.06 °C** difference against a 3.9 °C spread (**BUG-885**). The
  interval arithmetic that would stop this already exists in `evidence/matched_comparison.py`
  and still has one caller.

Fix BUG-879 and both rows become small. Its tracker row names the approach and the guard to
keep (place-scoped SUMMARY questions must still not be claimed).

After that, the ready rows by value: **W5-01** (rolling session summary — I asked for this
explicitly: a long conversation must still answer a question about turn 3), then **W3-05**,
**W3-02**, **W3-04**, **W6-01**.

## Non-negotiables

- **Never commit or push without my explicit approval.** Before any commit: down the stack,
  park bldg1 (`input/` → `bldg1/`, `.env` → `.env1`, `docker-compose.yml` →
  `docker-compose.bldg1.yml`), run `pytest -m unit` IN THE PARKED STATE, then ask me.
- Keep both trackers current as you go (Workflow rule 7) — a new defect gets a row, a fixed one
  gets its row updated with the verification.
- Never write Python source through a shell heredoc; the escapes arrive mangled.
- Run the answerability gate before and after any routing change, and read the answers behind
  any number that looks clean.

## Blocked on me — ask if these matter

- **W0-08** — confirm the three defibrillator positions.
- **W3-01** — is a real outdoor weather feed available, or should it be modelled?
- **CAVEAT-875** — evidence-pack question #1 answers only about half the time (caused by
  BUG-873's remnant, BUG-874). Relevant before that pack is shown to anyone.

Start by telling me what you find in the trackers and whether the state above still holds.

---

## Note for the article being written in parallel

The supervisor-facing evidence is `docs/supervisor_evidence_pack/` (73 screenshots, `README.md`,
`INDEX.md`, `answers.jsonl`, `review.json`). Two things to carry into the write-up:

- **CAVEAT-875** — pack question #1 is recorded GOOD but answers about half the time. The
  screenshot is a true record of one run; the question is not reliably answerable.
- The pack's headline count is **51 answerable of 73**, and the answerability gate re-derives
  that from the stored answers rather than from the verdicts — which is how a mislabelled
  verdict was caught (lessons.md #131).
