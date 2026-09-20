# Readiness after Stage 2 — 18 September 2026

**Written for:** the owner, deciding whether to record the system and to arrange a supervisor demo
on building 1. Plain words first; numbers, sources and limits after. Everything here was measured
on the running system today unless it says otherwise, and each number names where it came from.

---

## 1 · The answer

**You can record the scripted demo. You cannot yet hand the keyboard to a supervisor. And "all weaknesses covered" is not something I can say.**

| | verdict | why |
|---|---|---|
| **Record the 44-question script** (`docs/demo_script_questions.txt`) | **Yes, following the runbook** | On the final build, read in full: **37 good, 4 correct declines, 3 weird (1 high-confidence).** Six register answers were checked against their source tables and are right; the seventh is the wrong one below. |
| **Fix one scripted question first** | **Do it before recording** | *"Which refuge points are defective, and who owns them?"* says the register has no ownership field. It has one (*Building Fire Warden Coordinator*). Wrong in all three rehearsals (BUG-835). Drop "and who owns them". |
| **Let a supervisor ask what they like** | **No** | Held-out unscripted questions: **21 of 38 weird (55%), 13 with high confidence**; asked again on the same build, 19 of 38. About one answer in two would not be accepted by a reader. |
| **Tell them "all weaknesses are covered"** | **No** | §6 lists what is still weak. Rewording a failed question does not reliably rescue it: of 14 rewordings written after their siblings failed, **11 were weird too**. |

**So, when.** Recording can happen as soon as the runbook's pre-flight passes (restart the stack at
least 15 minutes before, `redis_hygiene --check`, wait out the post-boot sweep) and the presenter
follows the script. **Expect one to three blemishes per pass** (a template "recommendation", a slow
answer, an occasional narration slip): the same script gave 3, 4 and 3 weird answers in three
rehearsals, and they were not always the same three. A supervisor session where *they* choose the
questions should wait for the work in §6, in the order listed on the plan; do not schedule it
against a date until the held-out rate has been re-measured after those fixes.

**Three things only you can do:** decide Redis production policy (CAVEAT-801); approve the commit and
push (nothing is committed; buildings must be parked first, Workflow rule 8); and replace the
placeholders before deployment (§5: one query lists them).

---

## 2 · What Stage 2 was, and where each package stands

Stage 2 of `tasks/IMPROVEMENT_PLAN_2026-09-18.md` is the set of instruments that decide whether
Stage 1's work counts as progress. You also asked for data to be added where needed; that is the
plan's Stage 3 (W25/W26), and it is covered in §5.

| package | what it is | state |
|---|---|---|
| **W01** freeze + landmines | Redis headroom; no second compose project; an approved checkpoint | **Redis: done and verified** (2.135 GB → 5.7 MB of a 2 GB cap; a gate and a purge tool now exist). **Second compose project: measured, no conflict** — the `kg` (GeoLLM) stack uses different ports and ~2 GB of 46 GB; it is your other project, so it was left running. **Checkpoint SHA: not done** — it needs your approval to commit. |
| **W02** control arm | the same build asked the same questions twice, to measure how much it disagrees with itself | **Done, on the held-out set (not the 147-question bank).** Same build, same 40 questions, 21:03 and 21:26. On the 38 not asked earlier, **4 changed verdict: 10.5% (95% CI 2.6–21.1%)**. Weird share 55.3% then 50.0% (3 gained, 1 lost, p = 0.63: no change). **18 of the 21 weird answers were weird both times**, so the failures are systematic, not noise. Wording differs far more than verdicts do, and twice a *fact* changed: two floors' planned-maintenance dates were swapped in one run, and a forecast worked in one run and was refused in the other. |
| **W03** decompose the outcome | split "weird share" into correct answers and correct declines, tested separately, offline | **Done.** `scripts/decompose_outcomes.py` reproduces p = 0.824 (answers) and p = 0.024 (declines) exactly, with 5 tests including one proving it imports nothing that can reach a network. |
| **W04** record the lane and the rules | every answer says which lane produced it and which routing rules put it there | **Done and verified live.** `ontosage_route` now rides beside `ontosage_intent` on every `/v1` response, streamed and not. 42 of 42 replayed answers carried both, and 44 of 44 in the final demo run. |
| **W06** frozen codebook, blind read, grader κ | the labelling method pinned so it cannot drift | **Partly done.** Codebook frozen and pinned by SHA-256 (`docs/phase0/CODEBOOK.md`). The automatic grader's agreement with the hand labels, on 86 rows it was **not** tuned on (tail A + first demo rehearsal): **κ = 0.31, weird-precision 44%, recall 57%**. On the 294 rows it was tuned on: κ = 0.42, precision 95%. It over-flags on new material, so **it cannot stand in for the hand read**. A *blind* re-read by an independent second reader is **not possible from here** and is not claimed; every label is one reader's, and that reader also made the fixes. |

---

## 3 · What testing the unscripted tail found

The regression probe (60 cases) and the demo script (44) are the questions that were fixed until
they passed, so they are near-green **by construction** (58 of 60 and 41 of 44 acceptable on the
final build), and even so the script's own answers moved from run to run. Neither says how the first
twenty minutes of free questioning go. So two sets of unscripted questions were written in a supervisor's register, and
run through the demo path (`/v1`, streamed, signed in as `facility01@example.com`), then read by hand
against the frozen codebook.

| | tail A (42 questions) | tail B (40 questions) |
|---|---|---|
| purpose | found the defects | held out: written **before** any fix, run once **after** |
| before the fixes | **17 good answers · 5 correct declines · 20 weird (48%)**; 11 of the 20 high-confidence | — |
| after the fixes | **not re-run** (it is where the defects were found, so a re-run measures the fixes, not the system) | **21 of 38 weird (55%), 13 of them high-confidence (34%)**; 12 good answers, 5 correct declines. Asked again on the same build: 19 of 38 (50%), 10 high-confidence |

**Read this row carefully.** Tail B is a *different* set of questions from tail A, so 48% → 55% is
not a regression and 55% is not "the fixes made it worse". What it does say: **after everything done
today, roughly one unscripted question in two still gets an answer a reader would not accept, and
about one in three a reader would reject with confidence.** The fixes were real and narrow, and
nothing measured here shows that they moved that rate.

**Two of tail B's questions were accidentally asked while checking a fix**, and are therefore not
held out: *"How many people are in the building at the moment?"* and *"What was the total energy use
last month?"* They are excluded from the tail-B headline (n = 38), not quietly counted.

Reading tail B and the demo rehearsals exposed six more defects, fixed the same evening and checked
by hand on the final build (11 questions, all read):

| what a reader saw | cause | fix |
|---|---|---|
| *"Which rooms have the **worst** air quality right now?"* → the room with the **lowest** CO2 (BUG-823, P1) | the ranking always minimised, ignoring the word "worst" | reads the question's own words; now scored as maximise CO2 and PM2.5 |
| *"Compare this week's electricity use with last week"* on a Friday → **"fell 34%… an unintended outage"** (BUG-820, P2) | week 38 held five days and week 37 seven; the shorter total was read as a fall. **Present in both demo rehearsals; I labelled run 1 good in error.** | compared as a rate per day, with "week 38 covers only 117 of 168 hours" stated → *"fell 4.7% per day"* |
| *"The toilet on floor 2 is leaking"* → filed with **no location** and answered "I couldn't tell where this is" (BUG-822) | the code that decided not to ask "where?" never passed the place to the record | the stated place is kept: "Location: floor 2" |
| a garbled correction note under correct answers: *"exception — recorded as approved exception"*, *"appears in ?, ?"* (BUG-819, 824) | my own W19 guard from Stage 1 | it now recognises words in any order, and never prints a note it cannot cite |
| *"Room1.06 is free"* (BUG-821) | the graph id printed as the name | "Room 1.06" |

**Not measured on tail B:** these fixes were made after tail B ran (twice, on the same build). They
are checked by hand on 11 questions and by tests, not by re-running the held-out set.

The 20 weird answers in tail A had **distinct** causes, not one. Fixed this session (each with tests):

| what a supervisor saw | cause | fix |
|---|---|---|
| *"How busy is the building right now?"* → the whole answer was `**BUG-606**` | the narration prompt was **64,436 characters** for a 16,384-token model; Ollama drops from the *front*, so the model saw only the tail — which held a developer ticket id | occupancy summarised in code; a prompt budget that cuts the *middle* and says so; tracker ids stripped at the model boundary **and** scrubbed from every answer |
| *"How much electricity did the building use yesterday?"* → "no electricity usage data" | (1) the phrase "how much electricity" matched no concept; (2) once it did, the retrieval returned **air-quality sensors** because the repair step bailed on a name the catalogue lacks; (3) once repaired, the answer was the sum of the **six latest readings** (17 kWh), not the day (513 kWh) | vocabulary in the CSV source; class-based repair; the total computed in code, with the period it covers |
| *"How many people are in the building at the moment?"* → "no readings available" | the store column came back as `?database` (the prompt's own pattern) and only `?storage` was recognised, so all 250 sensors read `Storage: N/A` | one recogniser, both names |
| *"Is the heat pump running?"* → "I couldn't tell which asset you meant" | the asset-state lane knows lifts, AV and network; the classifier sent it a heat pump | a routing rule that hands such a turn to the data pipeline |
| *"Are there any showers?"* → answered from a **deleted** document | the document index never removed a file's chunks when the file was deleted | reconcile deletions (guarded); showers now answered from the authored topic |
| *"Who is the building's first aider?"* → contradicted itself | two authored statements disagreed about where the defibrillators are | data corrected to the equipment records |

Not fixed, and declared in §6.

---

## 4 · Verification battery

Everything below ran on 18 September against `bldg1`, as `facility01@example.com`, streamed through
`/v1` (the path Open WebUI uses), with both caches flushed before each run.

| check | result |
|---|---|
| **Demo script, 44 questions, final build (run 3)** | **37 good · 4 correct declines · 3 weird (1 high-confidence)**. Questions 1–22 were asked before, and 23–44 after, an **unplanned Docker restart** (all containers came back at ~22:09) from identical source. 44 of 44 rows carry lane and route. Latency p50 28 s, p90 58 s, slowest 129 s (the post-restart sweep was running). |
| Demo script, first two rehearsals, relabelled | run 1: 37 / 4 / 3 · run 2: 36 / 4 / 4. **Two labels were corrected after checking source data** (refuge-point ownership; the partial-week comparison): `docs/phase0/demo_rehearsal_2026-09-18_corrections.md` |
| Register answers checked against their source tables | work orders, permits, hazard controls, fire-safety assets, openings and HVAC regimes **correct**; refuge-point ownership **wrong**. The "good" counts are an **upper bound** for answers I did not check against data. |
| Regression probe, 60 cases | **58 / 60 first-pass** in 22.9 min, no retries. The two: BUG-783 (known, unchanged) and the calibration case, where the answer contains the right date as "17 Nov 2025" and the check accepts only the long month (CAVEAT-834, not edited away). Latency: p50 15.5 s, p95 49.4 s (*n < 20*), slowest 108.7 s, 0 timed out. |
| Live re-check of the six evening fixes | 11 questions on the final build, all read: HVAC clean, week comparison by rate, leak keeps "floor 2", "Room 1.06", "worst air quality" now ranks the high end, lift and maintenance answers without stray notes |
| **Unit suite** (`-m unit`, building 1 active) | **8,206 passed · 1 failed · 48 skipped · 3 expected failures** (14 min). The one failure pinned the old wording of the capability veto that today's single-predicate change replaced (BUG-818); I updated that assertion and it passes (re-run with its neighbours: 214 tests). **The full suite was not re-run after that one-test edit.** **Not run parked** (Workflow rule 8): do that at commit time. |
| Wording rule: never call the data synthetic, fake or simulated | Scanned every answer of the final battery (44 + 80 + 14): **no answer describes data that way.** The one hit for "simulated" is *"Simulated Trading Room"*, a real facility named in the building's own description (guardrail question *"Which rooms are computer laboratories?"*). |
| Redis | 6 MB of 2 GB after every run; harness residue purged |
| Coverage audit (`v12_coverage_audit.py`) | OK: every open item has an owner |

**Not run:** tail A a second time (it is where the defects were found), the 147-question bank, and
the bank-level control arm. **Not blind:** every label is one reader's, made knowing the earlier runs.

---

## 5 · Data added, and why so little

You asked for data to be added where a question needs it. Before authoring anything, each gap was
checked against what the building already holds, and the finding is uncomfortable: **most "missing
data" was not missing.** The graph holds 60+ register classes; the answers that said "not recorded"
were reading the wrong register or the wrong words. So:

* **Added or corrected (data):** the AED locations reconciled across three sources (BUG-799); the
  shower topic given its plural terms; the plant-equipment provenance comments reworded to plain
  language (they carried developer ticket ids inside `rdfs:comment` values a visitor could be shown).
* **Also added (vocabulary, not facts):** the drinking-water class now answers "free water", "buy
  bottles", "bottled water" (the scripted tap-water question was being answered as a room-booking
  question, then as a recommendation with no data; it now answers from the refill points in 1–2 s).
* **Gaps only the owner can fill, and were not invented:** tail B found the amenity catalogue records
  **no toilet on floor 2** (toilets on floors 0, 1 and 3 only) and records each **lift at one floor**
  rather than every floor it serves, so *"nearest lift to Room 4.01"* says "none on that floor, 3 floors
  down". Both look like catalogue gaps rather than facts about the building. They should be filled from
  the real building's plans; guessing a location for a toilet or a lift is a wrong-place error a person
  can act on.
* **Deliberately not added:** a cafe, vending machines and printers — checked live and the building
  **already answers** all three from existing topics; adding instances would have contradicted them.
  Nothing safety-critical (first aid, fire, certified accessibility facilities) was invented: a
  wrong location there can hurt someone.
* **A method finding, not a fix:** the same fact stated twice in authored text is a defect a supervisor
  will find. A 20-line scan of the authored answer texts found the AED conflict and a second (showers
  "on Floor 1" vs "the ground-floor changing area"). Worth keeping as a standing check.

**Placeholders to replace before deployment.** The graph flags every placeholder record
(`ontosage:isSimulated true`): **4,762 records across 52 classes**, so the replace list is one
query, not a memory. Of the datastores, only `database1` is declared real.

---

## 6 · What is still weak (declared, not hidden)

Ordered by how soon a supervisor would meet each one. Every row is in `tasks/FIX_TRACKER.csv`.

| weakness | what it looks like | measured on 18 Sep | tracker |
|---|---|---|---|
| **Free-form questions go wrong about one time in two** | false absence ("the building only records sensor counts"), a wrong reading, an "add a sensor" instruction | held-out tail B: **21 of 38 weird, 13 high-confidence**; the 14 rewordings written after tail A failed: **11 weird** | BUG-808..815, 825..832 |
| **Rewordings do not reliably rescue a failed question** | the workaround written for a failure fails too | guardrail run: 3 of 14 answered well | BUG-808..811 |
| Occupancy, per-room comfort, forecasts, heat-pump temperature, overdue maintenance | "no data" for data the building holds | tail B items 4, 38; guardrail items 2, 3, 4, 8, 12 | BUG-825, 826, 831 |
| Amenity and location questions ignore the floor or the type asked | lists toilets on floors 0, 1, 3 for floor 2; a menu of floors for "which floor is the server room on" | tail B items 13, 15, 16, 20 | BUG-827 |
| A confident conclusion the records do not support | "up to date with its fire safety inspections" beside an overdue dry riser | tail B item 26 | BUG-829 |
| Generic advice and uncited norms appended to numbers | "audit the airflow" on a 0.2 °C spread; "10–12 °C is typical" | 7 of the 44 scripted answers (13, 20, 27, 29, 33, 37, 39) | BUG-832 |
| The narrator sometimes slips on numbers and advice it has just been given | "Floors 2 and 5" beside a bullet giving Floor 5 an exception (run 2); "increase ventilation on Floor 5" where Floor 5 has the *lowest* CO2, and a "delta-T up to 53 °C" from max-minus-min (run 3); swapped maintenance dates (tail B) | scripted items 10, 28, 33 in different runs; tail B item 24 | CAVEAT-833 |
| **Latency** | p50 15.5 s and p95 49 s on the probe; single answers of 100–145 s (lift state, CO2 report) | probe 22.9 min for 60 cases; scripted run 19 min for 44 | CAVEAT-816 |
| Control lane names internal point identifiers | "the points this building lets me write are AHU-F5-SP …" | 2 scripted answers | CAVEAT-817 |
| Redis conversation policy | conversations never expire; eviction can drop sessions | policy unchanged; harness leak fixed | CAVEAT-801 |
| The model is not deterministic | the same build, asked twice, differs word for word | see §4 | — |

**What the numbers do not mean.** The 44 scripted answers are near-green because each was fixed
until it passed; that is what a rehearsal is, and it says nothing about the questions nobody
rehearsed. The held-out figure is the one to quote for unscripted use.

---

## 7 · What was not done

* **The bank-level control arm** (147 questions × 2). It costs ~3 hours of GPU and ~200 hand reads;
  the 38-question held-out version in §2 stands in for it and says so.
* **A blind second reader.** Every agreement figure here is one reader's; that reader also fixed the
  defects. State it whenever a number is quoted.
* **A commit.** Nothing is committed or pushed. The committed tree still has no active building.
* **Register selection (W20) and typed composition (W23).** Still the largest source of weird answers
  on the stakeholder bank (defect classes C7, C8, C9). Today's fixes were chosen because each was
  measured on a question a supervisor plausibly asks; they do not move the 96-question hand-read total
  in a way this document claims.

---

## 8 · Things you should decide

1. **Redis in production** (`CAVEAT-801`): conversations never expire by design and the eviction
   policy can evict sessions. Today's cleanup fixed the harness leak, not that.
2. **Commit and push**, when you are ready: it needs the buildings parked first (Workflow rule 8).
3. **Whether the `kg` project should run during a recording.** It is idle and harmless today.
