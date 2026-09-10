# Phase 0 — the release boundary, measured

**Date:** 9 September 2026
**Purpose:** the supervisor review's Phase 0 deliverable — *"Record what is verified in code,
what is merely documented and what remains unknown."*
**Source of the questions:** `docs/OntoSage_Architecture_Review_Corrected_v1.1.pdf`, pp. 17,
18, 28 (risk register R1–R9, Phase 0, "Questions that must be closed").

Every row below was checked against the running system or the source on 9 Sep 2026. The
review could not do this — it saw only a nine-page PDF and says so on p. 4. Its risks are
**predictions from a design description**; this document is what they turned out to be.

> **The review's own rule, applied here:** *"Inspect first; do not automatically add a
> parallel framework or treat a historical defect as still open."*

---

## 1 · Where an LLM runs — the call-site inventory (closes R6, T01)

**35 call sites.** The claim in my orientation note that classification is the only
generative step was **wrong at system scope**. It is true of the ARBITER lane only.

### Lanes that generate an artifact that is then EXECUTED

| Lane | Sites | Generates | Executed by | Control — verified |
|---|---|---|---|---|
| `sql_agent` | 522, 902, 961 | SQL | storage adapter | `validate_query()` — first token must be `SELECT`/`WITH`, forbidden-keyword regex. **Called in all six adapters** before `execute_query` |
| `sparql_agent` | 229, 1576, 1641 | SPARQL | GraphDB | `sparql_validator.enforce_limit()` |
| `analytics_agent` | 764, 933 | Python | `code-executor` | sandbox, below |

**The Python sandbox, verified live rather than read from the compose file:**

```
$ docker exec code-executor python -c "socket.create_connection(...)"
  blocked    internet DNS   (OSError)
  blocked    host MySQL     (gaierror)
  blocked    graphdb        (gaierror)
```

`cap_drop: ALL` · `read_only: true` · `no-new-privileges` · 2 GB / CPU capped ·
`networks: [executor-internal]` with `internal: true` · every secret blanked
(`SECRET_KEY=executor-holds-no-secrets`). Generated Python can compute and can reach
nothing.

### The remaining 27 sites

**Closed-vocabulary interpretation, validated in code:** intent classification
(`dialogue_agent:1087`), CQ-IR compilation (`deliberation/compiler:339`), multi-intent
detection, disambiguation, co-reference rewrite.

**Narration of already-computed numbers:** report, analytics summary, SQL/SPARQL summaries,
anomaly, capability, visualisation description, persona adaptation.

**Assessment.** The review's proposed control — *"prefer closed-vocabulary interpretation
followed by validated query builders"* — is already the design for the deliberation lane and
for the deterministic SQL path (`_build_uuid_union_query`). The generated-SQL path is the
**fallback** taken when no UUID group was resolved. That is a narrower boundary than the
review had to assume, and it is worth documenting rather than removing.

**B16 verdict:** the conditional test the review describes (*"generated-execution checks only
where applicable"*) **is applicable**, and the controls exist. What is missing is a test that
would fail if any of them were removed.

---

## 2 · Risk register — status against the code

| ID | Review's risk | Verified status on 9 Sep |
|---|---|---|
| **R1** | Failed-verification claim was published | **OPEN — confirmed.** `grounded` is read in exactly one place (`_orchestrator.py:5059`) and decides only whether the turn is filed in `agent_memory.store_success` or `store_failure`. **It gates publication not at all.** This is precisely why BUG-475's fabricated "install a CO₂ sensor" report went out carrying `grounded=False, confidence=0.20`. |
| **R2** | Correct numbers answer the wrong date / entity / operation / count | **PARTLY CLOSED.** Wrong-day fixed 8 Sep (BUG-480 — a named day now resolves to local midnight-to-midnight); row-limit-as-count fixed 8 Sep (BUG-479 — the fetch carries `rows_capped` and the narration is told). **Not closed:** there is no single normalized request object; the resolution lives in `dialogue_agent` and downstream consumers still re-derive. |
| **R3** | Retrieval failure becomes sensor absence | **PARTLY CLOSED.** BUG-475 stopped the report lane explaining an empty result; `absent_record_class` names a missing register honestly. **Not closed:** there is no typed outcome set — the seven states on review p. 8 collapse to "no data" everywhere else. |
| **R4** | Simulated evidence influences operational claims | **OPEN — confirmed, and worse than assumed.** See §3. |
| **R5** | Policy gaps in retrieval / derivatives / cache | **LARGELY CLOSED for the cache.** `response_cache._partition(building_id, role, user_id)` — role and user are in the key, added after a *measured* leak (an occupant received a facility manager's room-level reading). **Residual:** the key carries no policy version, so a GUI policy edit leaves prior answers servable for the 1-hour TTL. |
| **R6** | LLM boundary described inconsistently | **CLOSED by §1.** |
| **R7** | A lane computes but its answer is lost | **CLOSED — historical.** Audited all 37 intents: every node's bus keys are read on the response path. **0 uncollected.** The incident (observability, V6-T10) is fixed. **No test prevents regression** — that is the remaining work, not a repair. |
| **R8** | Objective or coverage weakness in ranking | **PARTLY OPEN.** `scorer.py` already separates `Hardness.HARD` from `SOFT`, which is half the review's proposed ranking contract. Missing: criterion registry with standard/edition, sensitivity reporting, and a declared missing-evidence rule. |
| **R9** | Second building needs code or prompt changes | **UNKNOWN — not tested this cycle.** bldg2/bldg3 exist and were onboarded, but not on the current revision. |

---

## 3 · R4 in detail — simulation governance is the largest open gap

Measured in the live graph:

```
ontosage:isSimulated true   →  3,004 points
ontosage:isSimulated false  →      0 points
no isSimulated declared     →  1,342 points
```

**Nothing in this building positively asserts that a point is measured.** The only
provenance signal present is the simulated flag; 1,342 points are silent, and silence reads
as measured to any default-permissive consumer.

Two further findings, both matching the review's prediction:

1. **`scorer.py` contains zero occurrences of** `simulated` / `provenance` / `admissible` /
   `eligible`. The ranker cannot exclude a simulated candidate. It is *displayed* in the
   dossier's evidence table (`dossier.py:324-331`, rendered `yes` / `no` / `undeclared`) and
   *never acted on*. This is exactly review B06: **"an attractive simulated candidate must
   not win an operational ranking, even after its values are transformed."**
2. **Provenance is resolved per STORE, not per observation** —
   `simulated=synthetic_lookup(e.stored_at)` (`dossier.py:190`), a function of the table
   name. Review p. 11: *"Apply provenance rules per observation or batch, not only per Point;
   stores or namespaces alone do not enforce them."*

**Consequence for the demo.** bldg1's `sensor_data` is a real snapshot extended by a
generated top-up (user-confirmed, by design). A ranking answer today can be won by a
SATURATE-provisioned point and the answer will say so only in a table the reader may not
read.

---

## 4 · Mixed-source requests — where the review disagrees with a change I shipped

On 8 Sep I inverted the capability short-circuit (W0-2/BUG-440) so documents are consulted
**after** the classifier and only over a weak intent. That fixed a structural question being
answered from a cleaning register with 6 of 48 rooms.

The review accepts the fix and names its limit (p. 5): *"It does not establish that documents
should always be ignored once any other lane can answer part of a request."*

**Verified:** `_promote_to_capability_from_documents` returns immediately unless the intent is
in `_DOC_OVERRIDABLE = ("general", "general_knowledge", "clarification", None)`. So
*"which rooms were stuffy yesterday, and what does the manual say to do about it?"* classifies
as a data intent, gets the observations, and **the procedure half is never attempted and never
mentioned**.

This is not a regression — before the inversion the document lane would have claimed the whole
question and answered it from prose, which is worse. It is the cost of "one question, one
lane", and the review's **bounded composition rule** is the right answer: support a few
documented combinations, keep evidence per sub-answer, and **say which part is unsupported**.

---

## 5 · The seven W0 questions (closes the review's "exact seven cases" gap)

The review notes on p. 16 that the source *"does not enumerate it fully."* From
`docs/V10_LIVE_VERIFICATION.md`:

| # | Question | The failure it protects against |
|---|---|---|
| 1 | Is the lift working? | asset status claimed absent while declared |
| 2 | How many sensors are there in total? | floor count wrong (8 in a six-storey building); streams vs declared sensors conflated |
| 3 | What is this building and who runs it? | privacy refusal on a structural question |
| 4 | Nearest accessible toilet to room 3.10? | `3.10` parsed as floor ten; accessibility inferred from lay terms |
| 5 | Which rooms are stuffy right now? | a non-answer substituted for an honest decline |
| 6 | Compare avg CO₂ floor 1 vs floor 3 | physically impossible readings included (157 ppm) |
| 7 | Show me floor 3 | invented room numbers |

Review's added requirement: **assert the final output, not only the route.**

---

## 6 · What remains unknown

- **R9 / portability.** No second-building run on the current revision.
- **Standards registry.** Which edition of which standard backs each comparison band
  (review p. 10). `scorer.py` cites bands; the registry behind them is not inventoried.
- **Freshness per modality.** The review objects (p. 27) to generalising bldg1's ~30-second
  row interval across every quantity. Not yet measured per modality.
- **Held-out evaluation set.** All 50 probe cases have been used to tune the implementation,
  so by the review's definition (p. 14) **none of them is held-out evidence.** This is the
  most uncomfortable finding in this document and it is not repairable by adding tests to the
  same set.
