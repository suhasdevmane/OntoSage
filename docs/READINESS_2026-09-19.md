# Readiness after the two-day push — 19–20 September 2026

**Written for:** the owner, deciding whether and how to show this system to a supervisor who may ask
anything. Plain words first; numbers, sources and limits after. Every figure below was measured on
the running system and names its source.

---

## 1 · The answer

**Record the scripted demo now. A free question session is now defensible if the supervisor is
briefed: about one unseen question in four still gets an answer a reader would not accept, and one in
eleven gets a confidently wrong one.**

| | verdict | the measurement behind it |
|---|---|---|
| **Record the 44-question script** | **Yes** | 44/44 answered. One scripted answer was broken by a new safeguard during the push, found, fixed and re-asked live (§3). Three answers are slow (§5) |
| **Let a supervisor ask anything** | **With a briefing** | Last two unseen sets: **33 of 124 weird (26.6 %, ±8 points)**, 11 of them confidently wrong (8.9 %). Before the last two waves: 41.2 % and 21.8 % |
| **Say "every flaw is covered"** | **No** | §5 lists what is still wrong; §6 what only you can supply |

**What the push did, in one line:** it took a system that gave an unacceptable answer to three
unseen questions in five (61 %) to one that gives one to about one in four, and it took the register
lane from 70 % to 94 % correct against the source tables — by fixing *classes* of failure, after six
waves of fixing individual answers had stopped moving the rate.

---

## 2 · The numbers

Each row names the set and the method. Nothing is a projection.

| measure | start of the push | end of the push |
|---|---|---|
| **Unseen unscripted questions** (62 per set, drawn by seed from the 2,960-question stakeholder catalogue + 6,117-question survey, hand-labelled by one reader) | Tail C: **38 of 62 weird (61 %)**, 24 high-confidence | Tails K and L: **33 of 124 (26.6 %)**, 11 high-confidence (8.9 %) |
| **Register answers against truth computed from the source tables** (94 questions, no model involved) | **66/94 (70.2 %)** | **88/94 (93.6 %)**, 95 % CI 86.8–97.0. The baseline rescored under the same grader is unchanged |
| **Regression probe** (60 pinned cases, first pass, no retries) | 58/60 | **59/60**; p50 15.2 s, p95 47.7 s, slowest 98 s |
| **Unit suite** (`-m unit`, building active) | 8,206 pass | **12,314 pass**, 0 fail, on the exact final tree |
| **Offline concept reach** over 10,216 tuning questions | 30.2 % | 47.8 % |

**The unseen sets in the order measured** — each is a fresh draw, so they are not paired and each
carries about ±12 points on its own:

| set | D | E | F | G | H | I | J | **K** | **L** |
|---|---|---|---|---|---|---|---|---|---|
| weird | 38.3 % | 38.7 % | 43.5 % | 50.0 % | 32.3 % | 37.1 % | 48.4 % | **24.2 %** | **29.0 %** |

Pooled D–J (seven sets, 432 questions): **41.2 %**. Pooled K–L (124 questions): **26.6 %**. The
difference is 14.6 points, z = 3.2, p ≈ 0.002. **Between tail D and tail J the rate did not move**;
the drop coincides with the last two waves, which fixed failure *classes* rather than the answers a
wave had been shown (§4). Only tail K was run with the relevance gate off and then on: the gate is
responsible for three of its seventeen unacceptable answers.

---

## 3 · How the measurement was kept honest

* **Ten unseen sets (C–L), each drawn by seed before it was used**, from the real banks; each is
  used to *verdict once* and then spent — agents are briefed on its failures only after a fresh set
  exists. Tail M onwards can be drawn the same way.
* **A test fails if any held-out question appears in code or fixtures.** It fired four times during
  the push, each time from a briefing that quoted a question; each copy was paraphrased away.
  Earlier leaks are recorded in `docs/phase0/heldout_integrity_2026-09-19.md`.
* **One reader.** Every label is mine, and I also made the fixes. A decline counts as acceptable and
  a wrong-but-plausible answer does not.
* **Instruments were found wrong five times**: the probe failed a correct "8.0 hours" against "8"; the
  register grader read "6 of 16 have no lift status — the field is empty on each of them" as a false
  absence; a probe case demanded a note that exists only when bad readings exist; a regex escape
  written through a shell became a backspace; and a fail-open gate did nothing for a whole live run
  (§4).
* **A safeguard broke a scripted answer and was caught by rerunning the script.** The relevance gate
  replaced the correct two-sensor TVOC answer because it listed two averages. The label behind that
  fired on 2 of 372 labelled answers, so it no longer replaces anything; the answer was re-asked
  live and returned. The lesson is written into `tasks/lessons.md` (#124–#126).

---

## 4 · What was built, and why it plateaued then moved

Eleven parallel workstreams over nine waves, each verified live before the next.

| area | what it does now |
|---|---|
| **Sensor binding** | A room, floor, plant item or named place plus a quantity reaches its own series. A place with no such sensor says so |
| **Register composition** | Owner, overdue, open, "which have no X", counts by facet, a record id (WO-008, CLN-0010) — computed from the rows in code. "No X" reads both an empty field and a value that says none. A word like "owner" used as a *qualifier* no longer produces an owner list |
| **Aggregates** | Per-floor and whole-building answers from the store's own aggregates: highest CO2 this week, exceedance against a cited standard, per-floor headcount from the floor counters, hourly profiles, water volume with its method. A quantity the question does not name is never summarised |
| **Routing** | 54 ordered rules. Knowledge questions get labelled guidance; a hedged message never files a report; **a fault statement with a request attached ("the bin is overflowing, can you fix this?") files**; reservations and wishes get a scope statement |
| **Honesty of absence** | A lane that cannot answer no longer says the building holds nothing; a false "does not exist / does not have" about something the building holds is rewritten; the "covers all N sensors" refusal is now an honest decline unless the reader asked for every sensor |
| **Wording** | No internal identifiers, storage jargon, chopped words, orphaned sentences or "simulated"; no fragment, file name or class comment as an answer |
| **Relevance gate** | A last local-model check that an answer responds to the question, on the data lanes only; replaces off-topic answers with an honest decline. Off by setting `ANSWER_RELEVANCE_GATE=false` |

**Why it plateaued.** Roughly half of the unacceptable answers were a lane answering a *different*
question than the one asked, each for its own reason, so each fix removed a handful and a fresh set
exposed a handful of new ones. **What moved it** was removing whole classes: replacing the machine-shaped
"too wide" refusal with an honest decline (it was the most frequent single failure), answer-shape and
absence guards, question-must-name-its-quantity, and record-id selection. **The relevance gate was
built last and contributes least**: measured paired on tail K it fixed 3 of 17 and replaced no good
answer, against an offline estimate of 11 points. Both offline figures selected their own best case.

---

## 5 · What is still wrong

Measured on tails K and L, most frequent first.

| weakness | what it looks like | tracker |
|---|---|---|
| **Slow answers** | Six of 62 answers on tail L took 100–170 s; scripted demo item 38 (week-on-week electricity) took 157 s; p95 is 48 s | CAVEAT-816 |
| **Broken grammar in a decline** | "I did not find any investigations meet the gates…", "…in the building's a v readiness records", "I did not find all of the items … were in force" | BUG-836 |
| **A lane still answers a different question** | A sensor lane answering "where are refreshments available?" with a raw identifier; a comfort-advice paragraph for a productivity question | BUG-846, 850 |
| **A bare identifier as the answer** | "FSA-001" alone for "which fire-safety records are unsigned…"; deliberately not caught (a single code can be a complete answer) | BUG-837 |
| **Invented capability** | "the system can compare with the normal values it has learned from the data" — it does not learn | new |
| **Schema vocabulary leaking** | "the OperatingRegime class and its instances (REG-001…)" | BUG-836 |
| **Placeholder data incoherence** | Room occupancy averages ~14 where floor counters read ~29; two CO2 sensors in one room with different calibration dates; historical AHU spikes to 1,098 °C (the live stream is clean) | CAVEAT-847, 849 |

---

## 6 · What only you can supply

Nothing safety-critical was invented. These are needed from the real building:

* **Safety and access:** first-aid rota and room, AED positions, refuge points, fire exits, accessible
  toilets (both recorded are placeholders), and the exact position of the assembly point (recorded
  only as "the open area on Senghennydd Road, directly outside the main entrance"). Which side of
  the road, the distance, the fallback if the road is closed, and where wheelchair users muster.
* **Compliance:** refrigerant type, charge and leak-check dates; contractor insurance and RAMS approvals.
* **Operational:** term dates, a real closures calendar, EV charger and parking fees (the answer now
  says the fee is not recorded), stairwell floors served, survey results.
* **Reconcile where the building contradicts itself:** showers (Floor 1 vs the ground-floor plan),
  vending (Floors 1/3 vs the ground-floor zone), bike storage (basement vs outdoor racks), lift naming.
* **Room identity:** the graph disagrees with the architect's drawings for 132 rooms; the cascade was
  deliberately not landed in this push and needs four answers from you (`CAVEAT-841`).

**Before deployment:** replace the placeholder records. One query lists them (`ontosage:isSimulated true`).

---

## 7 · What to do, in order

1. **Record the scripted demo.** Allow time: three answers take 65–160 s. Ask in the order of
   `docs/demo_script_questions.txt`; the runbook `docs/RECORDING_RUNBOOK_2026-09-18.md` still applies.
2. **For a free session, brief the supervisor.** The shapes that work best: a room or floor by name
   plus a quantity ("CO2 in room 5.01 right now", "which floor is warmest"); a register by record id
   ("who owns CLN-0010?", "WS-28"); "which … are overdue / open / have no …"; per-floor comparisons;
   amenities by floor; questions about what the building does not measure (it declines honestly).
   Long multi-clause governance questions are the weakest shape.
3. **Clear the test records first.** Verification runs filed tickets: REP-2EA311, REP-384D16,
   REP-051956, REP-8AC1A1, REP-D72D1D, REP-26FFBF, REP-74EEAA, REP-31B6EB, REP-759E64, REP-20A30B,
   REP-83ECC0, REP-DACBCD, REP-CF00AB and alert 295c1794, plus one ticket per probe run ("The toilet on
   floor 2 is leaking"). Nothing was deleted; the reports are in `user_reports`.
4. **Keep the measurement loop running** after you stop watching: draw a fresh set, read it, brief on
   classes, never on questions.

---

## 8 · What was not done

* **A second annotator.** Every agreement figure is one reader's.
* **The 147-question bank** was not re-read; the unseen sets replace it as the honest instrument.
* **A commit.** Nothing is committed or pushed; the committed tree still has no active building
  (Workflow rule 8: park all buildings and run the suite parked before any commit).
* **Latency.** Measured (p50 15 s, p95 48 s, tail 170 s) but not reduced.

---

## 9 · Decisions waiting for you

1. **Redis in production** (`CAVEAT-801`): conversations never expire by design.
2. **Commit and push** when you are ready.
3. **Room identity** (`CAVEAT-841`): four questions, then the cascade lands as one change.
4. **Scripted or free supervisor session** (§7).
5. **Whether to keep the relevance gate on.** It adds about a second to data-lane answers and its
   measured benefit is small; it is the only piece that can replace a good answer (once, and fixed).
