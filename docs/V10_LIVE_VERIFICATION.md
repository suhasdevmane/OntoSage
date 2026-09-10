# V10 — live verification of the seven W0 fixes

**Run:** 2026-09-07 · bldg1 active · local `gpt-oss:20b` · response cache flushed before each pass
**Why:** every W0 fix was verified by SPARQL, SQL and offline tests while no model was
available, and every tracker row said the live re-ask was OWED. Offline evidence shows the
DATA and the CODE are right. Only this shows the user gets a different answer.

---

## Verdict

**Six of seven confirmed fixed. One is fixed but its disclosure is unverified.**

The pass also found **three defects that every offline test had missed** — two in code I
wrote this session, one a silent truncation that made a guard under-report. That is the
result worth keeping: the offline suite went from 5,004 to 5,177 tests without catching any
of them.

| # | question | before | after | verdict |
|---|---|---|---|---|
| 1 | Is the lift working? | "This building has no lifts recorded in its model" | **"1 of 1 lift(s) are not operational: Main passenger lift (controller fault) (out of service since 14 days ago). Report or chase it with: Estates helpdesk, ext 1234."** | ✅ |
| 2 | How many sensors are there in total? | "Floors: **8**" in a six-storey building; 2,763 reporting > 2,720 declared | **"Floors: 8 — 6 storeys plus 1 rooftop, 1 parking level (Brick counts these as floors)"** and "Data streams that reported… not comparable to the sensor count above" | ✅ |
| 3 | What is this building and who runs it? | `privacy_refusal` — "it never tracks individuals" | **"Operated by: Cardiff University Estates"** | ✅ |
| 4 | Nearest accessible toilet to room 3.10? | "No toilet is reachable… adjacency is incomplete" | **"There is no accessible toilet recorded on 3.10's floor. The nearest is Accessible WC - Floor 4 — 1 floor up."** | ✅ *(after a fix, below)* |
| 5 | Which rooms are stuffy right now? | "I don't have the readings… What I can give you is a sensor-count table…" | **the honest decline**, naming the intent and the lane that ran | ✅ *(after a fix, below)* |
| 6 | Compare avg CO₂ floor 1 vs floor 3 | **157 ppm vs 111 ppm** + an HVAC recommendation | **835 ppm vs 790 ppm**, with 1,000 impossible readings excluded | ✅ figures · ⚠️ disclosure |
| 7 | Show me floor 3 | *(regression check)* | real spaces listed, **no invented rooms** | ✅ |

---

## What the live run found that offline testing could not

### 1. `3.10` was read as floor **ten** (my own W0-7 fix)

    "There is no accessible toilet recorded on 3.10's floor. The nearest is
     Accessible WC - Floor 4 (Fourth Floor) — 6 floors down."

Floor 4 is **one floor up** from floor 3. `Space` carries no `floor` field — the floor
lives on the **manifest** — so the fallback I wrote (the trailing number of the zone id)
was the only branch that ever ran, and `3.10`'s trailing number is `10`.

Every offline test passed because each supplies `from_floor` directly; not one exercised
the derivation. Fixed at the source: the floor is read from the manifest that contains the
space. A grammar guess where an authoritative source exists is the mistake the lexicon work
exists to stop making.

### 2. The meta-answer guard missed the answer it was written for

The guard shipped, 20 offline tests passed, and the first live re-ask returned the exact
prose it exists to suppress. Two gaps:

* **"What I can give you is…"** — the pivot list held `share|tell you|offer`. Three
  synonyms is not a vocabulary.
* **"If you'd like to check … just let me know"** never matched, because the model wrote a
  **right single quotation mark** and the pattern expects an apostrophe.

The second is a class, not an instance. A model writes curly quotes, en dashes and em
dashes wherever prose calls for them, so *every* pattern matching a contraction or a dash
in model output had the same hole. Typography is now normalised once, before matching.

### 3. The plausibility band map was silently truncated to 1,000 sensors

The log said `1000 sensor(s) carry a declared physical band`. That is not a count; it is
`SPARQLAgent._execute_query`'s `LIMIT 1000` safety cap — correct for a model-generated
query, wrong for an exhaustive map. The gate therefore had nothing to say about **65% of
the building's 2,841 instrumented uuids**.

The symptom was a *right-looking* answer: 797 ppm against 775 ppm, both plausible and a
vast improvement on 157/111, while a sensor reading **190 ppm** was still folded into the
average because its uuid fell outside the truncated map. The model happened to flag it —
luck, not the guard.

With an explicit `LIMIT`, coverage went **1,000 → 2,281** and the gate excluded 1,000
readings from that sensor. The answer moved to **835 vs 790 ppm**.

**A cap on an exhaustive query does not fail; it under-reports — and under-reporting from a
guard reads exactly like having nothing to report.** The loader now says so out loud when
the count is an exact multiple of 1,000.

---

## Outstanding

**The exclusion is not disclosed to the reader.** `exclude_impossible_readings` appends its
caveat to the SQL lane's prose; the `compare` and `analytics` lanes re-narrate from the rows
and drop it. A note is now appended after the whole dispatch so it survives whichever lane
writes the answer — **verified offline, not yet live**, because the comparison question
became unstable on the last attempt (below).

**The comparison question is slow and, once, degenerate.** It fetches ~1.8M rows across ten
tables; observed at 63 s, 94 s, and twice past the probe's 121 s client timeout. On the run
with a 7-minute timeout the model returned a wall of `"3.04? not present. 3.05? not
present."` — reasoning leakage on a long prompt, the BUG-188 class, not a defect introduced
here. Tracked separately.

**The "stuffy" question's underlying defect stands.** The guard turns a wrong answer into an
honest one; the generated SPARQL still returns sensor COUNTS for a question about readings.
That is a query defect, logged as a residual on BUG-443.
