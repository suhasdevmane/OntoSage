# Coding Guide — Phase B3 Inter-Rater Reliability

This guide is the *operational* version of `taxonomy_v1.md`. Two human coders use it independently on the 300-question IRR sample. Disagreements are resolved in a discussion round; only post-discussion codes are released.

## Workflow

1. Open `taxonomy/irr_samples.csv` (300 rows)
2. For each row, fill **six** columns: `domain_l1`, `query_type_l2`, `intent`, `temporal`, `spatial`, `complexity`
3. Save your annotated copy as `irr_samples_coderA.csv` (or `_coderB.csv`)
4. Do NOT discuss codes with the other coder until both files are saved
5. Cohen's Kappa is computed per dimension by `scripts/B_corpus_classification.py --irr`
6. Target Kappa per dimension: ≥ 0.70

## Decision rules (top-down — apply in order)

### 1. Is the question building-related?
- **No** (off-topic, gibberish, fewer than 3 meaningful words): `domain_l1 = OTHER`, fill the rest with the OTHER defaults from `taxonomy_v1.md`. Done.
- **Yes**: continue.

### 2. Pick `domain_l1`
- Use the table in `taxonomy_v1.md`
- If two domains apply, pick the one that the *answer* would primarily report on
- "I want a temperature reading in the conference room" → `THERMAL` (answer is a temperature, not a location)
- "Where is the meeting room?" → `WAYFINDING`
- "How is air quality in the gym?" → `AIR_QUALITY`

### 3. Pick `query_type_l2`
- Apply the priority order: `ANOMALY > RECOMMENDATION > DIAGNOSTIC > COMPARISON > HISTORICAL > STATUS > CAPABILITY`
- "Is CO2 too high?" → `ANOMALY` (not `STATUS`)
- "Why is room 5.04 warm?" → `DIAGNOSTIC`
- "Should I open the window?" → `RECOMMENDATION`
- "Compare A and B" → `COMPARISON`
- "Show me last week" → `HISTORICAL`
- "What is X right now" → `STATUS`
- "Can the building do X" → `CAPABILITY`

### 4. Pick `intent`
- Same word can have multiple intents — choose the *purpose* the user is pursuing
- `INFORMATIONAL` is the default; only escalate if there's a clear cause-seeking, action-seeking, or future-prediction signal

### 5. Pick `temporal`
- "now / current / right now" → `REALTIME`
- "yesterday / last … / for the past …" → `HISTORICAL`
- "will be / forecast / going to" → `PREDICTIVE`
- Time-invariant facts (square footage, certifications, building hours) → `STATIC`

### 6. Pick `spatial`
- A specific room or zone is named → `ROOM`
- A floor or wing is named → `FLOOR`
- "the building" or no scope at all but obviously building-wide → `BUILDING`
- A device is named or implied (e.g., "this thermostat") → `POINT`
- "across our buildings" or "campus" → `CAMPUS`
- No spatial cue at all → `UNSPECIFIED`

### 7. Pick `complexity`
- One value or one row needed → `LOOKUP`
- Mean / sum / count / groupby over many rows → `AGGREGATION`
- Two or more datasets joined, or analytics / planner step needed → `MULTI_STEP`

## Hard rules

- Do **not** invent codes. If a query truly doesn't fit, mark `domain_l1 = OTHER` and note in the disagreement log.
- Do **not** annotate based on what *you* would mean by the question — annotate the surface form.
- If the question is in ALL CAPS or has typos, it does **not** affect the coding. Read for intent.
- If you genuinely cannot decide between two codes, write your second guess in a `coder_notes` column for the discussion round.

## Discussion round

After both coders submit, the IRR script flags any row where the two coders disagree on any dimension. Coders meet for ~90 minutes, walk through disagreements, and produce a single reconciled code. Only the reconciled codes feed Phase B4 statistics.
