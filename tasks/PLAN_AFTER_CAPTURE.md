# Plan: what happens after the clean capture lands

**Written 2026-08-23, while `baseline_20260822_233258` is still running.** Fixing the steps and
the decision rules *before* seeing the numbers, so the interpretation is not chosen to suit
them. Every gate this project has run so far was read after the fact, and twice the reading was
wrong (BUG-176, BUG-177).

**Standing constraint: nothing is committed or pushed without explicit approval, and no
building is active in the committed tree (Workflow rule 8).**

---

## Step 0 — Is the run gradeable at all? (5 min, blocking)

Before any comparison, three checks. If any fails, the run is discarded like the last one — a
number from an unhealthy run is worse than no number.

| Check | Pass condition | Why |
|---|---|---|
| Container identity | `docker inspect ... StartedAt` is *earlier* than the first captured row and unchanged since | The last run was invalidated by a mid-run recreate, and every row still looked individually valid |
| Quarantine | `failed + degraded` is a small tail (timeouts), not a block | A wall of failures means the stack wobbled |
| Config constancy | No source edit and no `up -d` between first and last row | Rows must all describe one configuration |

Only the third is new, and it is the one that caught nothing last time because I wasn't
checking it.

## Step 1 — Run the regression gate (10 min)

```bash
python scripts/baseline_regression_gate.py \
    --before scripts/outputs/baseline/baseline_20260822_135157.csv \
    --after  scripts/outputs/baseline/baseline_20260822_233258.csv --partial
```

`baseline_20260822_135157` is the right comparand: same `--every 5` stratification, captured
after the routing work and before the floor change, so **the floor is the only answer-affecting
difference**. V6-T03 and the freshness gate also landed in between but neither can change an
answer — the record gained fields, and the gate is advisory. If the gate reports changes that
cannot be explained by the floor, that assumption is wrong and it is the first thing to chase.

## Step 2 — Decide on the 0.55 floor (the real decision)

The gate sorts every changed answer into unchanged / improved / tightened / REGRESSION. What
matters is whether the losses are attributable.

**Predicted, from the sweep on the 55 labelled questions still reaching the document lane:**
about a quarter of document-citing answers become an honest "no relevant passage", roughly
**2.6 removed-wrong for every 1 removed-right**. Headline combined coverage should fall by
**5-7 points**, of which ~72% is wrong answers leaving.

| Outcome | Decision |
|---|---|
| Losses classify as `tightened`, naming `retrieval_floor`, ratio ≥ 2:1 | **Keep 0.55.** Report the coverage drop with its decomposition, prominently. |
| Losses are `REGRESSION` — no gate named | **Investigate before keeping.** Means CAVEAT-226's attribution isn't firing on these paths; an unexplained loss is a regression whatever caused it. |
| Ratio materially below 2:1 on live data | **Revert to 0.50.** The labelled-set prediction did not hold, and the sweep was the whole argument. |
| Answers changed that never touch a document | **Stop.** Something other than the floor moved, and I don't know what. |

A revert is a one-line change to `MODEL_SCORE_FLOORS` plus its pinned test — cheap, and I would
rather take it than defend a number.

## Step 3 — Report the coverage number honestly (30 min)

Whatever survives, the headline figure moves, and this project's coverage numbers are
research-facing. The write-up must state, in one place:

- combined coverage before and after;
- the split of the change into *wrong answers removed* and *right answers lost*;
- that the second number is a real cost, not an artefact.

A coverage figure quoted across this change without the decomposition is misleading in the
direction that flatters the system. `shared/config.py` already carries the sweep; the results
table needs the live equivalent.

---

## Then, in priority order

### A. Finish what the freshness gate started (highest value, ~2-3 h)

The gate is live and advisory and it is already saying something uncomfortable and true: a CO2
answer phrased "right now" rests on a 2.6-day-old reading. Three things follow.

1. **The gate-impact report** (V6-T55's third criterion). A script that reads the capture's
   evidence records and lists every question the freshness gate *would* change if enforced,
   with its age and modality. That report is what you decide enforcement on — not me.
2. **The three unwired gates need their inputs**, in this order by value:
   - `completeness` ← coverage is never computed. `completeness.py::assess()` exists and takes
     the declared cadence; nothing calls it.
   - `spatial_adequacy` ← every source's grade defaults to `NONE`. `spatial_adequacy.py`
     exists; nothing classifies.
   - `calibration` ← no source declares a state; needs TTL, so it is genuinely blocked, not
     merely unwired.
   Each is the same shape as the freshness gap: decision logic delivered, input absent.
3. **The narration should cite the age.** The answer says "right now" while the record says
   3702 minutes. Advisory means the record is right and the prose is wrong, and that gap is
   visible to a reader today.

### B. TODO-072 cold build — **needs your go-ahead** (~1-1.5 h, stack down)

Scripted and defined: [`COLD_START_VERIFICATION.md`](./COLD_START_VERIFICATION.md) +
`scripts/cold_start_verification.py`. It uses a scratch building id so your three buildings'
volumes are untouched, and `data-publisher` is scaled to zero so nothing can write into
bldg1's real snapshot. But it takes the stack down and brings it back, twice through a cold
GraphDB warm-up. I will not start it without you saying so.

### C. Backlog, smallest first

- **TODO-229** — report-intake lane emits no evidence record (an eleventh lane; fail-closed
  today, which is the chokepoint working, but it should declare itself).
- **TODO-181** — retype 420 legacy instances carrying undefined `brick:` classes across three
  buildings. Harmless at query time, non-conformant.
- **CAVEAT-160** — temp-0 compile wobble flipping answer↔clarify between runs.
- **BUG-147** — the live join-rate assertion still owed on a fix that landed in V4-T13.

### D. Not mine to start

- **V5-T44** multi-model benchmark — blocked on the hosted quota window, and on a paid plan for
  the 12 models returning HTTP 403.
- **V5-T34/T35** bldg3 and bldg1 pillar legs — each needs a building swap.

---

## What I will not do without asking

- commit or push anything;
- start the cold build, or any other run that takes the stack down;
- switch a gate from advisory to enforcing;
- publish a coverage number without its decomposition.
