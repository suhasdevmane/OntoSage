# Hand-read codebook (frozen 2026-09-18)

W06 of `tasks/IMPROVEMENT_PLAN_2026-09-18.md`. This file is the codebook every hand read of the
147-question bank (`phase0_*_read.jsonl`) and of the fresh tail (`fresh_tail_*`) follows. Its
SHA-256 is recorded in `CODEBOOK.sha256`; a read made under a different hash is a different
instrument and must say so. **Change this file only by making a new one** — a codebook that can
be edited after the labels exist can be fitted to them.

The full defect-class write-ups (evidence, counts, examples) stay in `phase0_read.md` §C1–C22.
This file is the part a reader needs while labelling.

## 1 · The unit, and what a reader may look at

One unit = one question and the answer the system streamed for it, as a facility manager saw it.
A reader may check any figure or claim **against the building's own data** (graph, registers, the
store rows the answer names). A reader may not use another run's verdict for the same question
while labelling — a *blind* read sees only the question and the answer.

## 2 · The three verdicts

| verdict | meaning |
|---|---|
| `GOOD_ANSWER` | answers what was asked, from data the building holds; every figure and claim is traceable to something the answer names; nothing is invented; about the right subject |
| `GOOD_DECLINE` | declines, and the decline is **true and about the right thing**: the building genuinely does not hold it, or the referent is genuinely ambiguous and the answer asks which. A decline that denies data the building holds is **not** a good decline |
| `WEIRD` | anything else. A reader would not accept the answer: wrong subject, wrong lane, false absence, an invented conclusion, an instruction to add data, internal jargon, a fragment |

An honest decline is a correct answer, never a failure. **A wrong decline is `WEIRD`.**

## 3 · The five-dimension rubric

Any FAIL makes the answer `WEIRD`.

| dimension | the question it asks |
|---|---|
| `answers_question` | does it answer what was asked, rather than apologise, template, name its own machinery, or tell the reader to add data? |
| `figures_traceable` | is every figure traceable to something the answer itself names? |
| `honest_absence` | if it states an absence, is that absence stated honestly and about the right thing? |
| `no_invented_claim` | is it free of conclusions the cited evidence cannot support? |
| `right_subject` | is the whole answer, footers included, about the subject asked about? |

## 4 · Labels a reader may attach to a `WEIRD` row

`causes` (zero or more): `FALSE_ABSENCE` · `WRONG_REGISTER` · `UNGROUNDED` · `INCOMPLETE` ·
`WRONG_LANE_OTHER` · `ADD_DATA_INSTRUCTION` · `USER_ATTRIBUTION` · `ROOM_WORDING` ·
`SAYS_SIMULATED` · `OTHER`.

`confidence`: `high` · `med` · `low`. **`high` is the headline** — the collapsed count moves with
`low`/`med` labels (14 → 1 across six runs) and must not be quoted alone.

`class` (one, optional) — the defect class in `phase0_read.md`:

| id | one line |
|---|---|
| C1 | absence guard rewrote a valid decline (alias matched inside another word) |
| C2 | fetch-budget refusal for a whole-building, multi-measurement question |
| C3 | narration hygiene: "the data you provided", raw field names, provenance flags, repetition |
| C4 | metadata / discovery RAG fallback: "the ontology you provided", false absence |
| C5 | "I understood the question but could not put an answer together" — lane jargon, no content |
| C6a | shelf-life / meter-boundary footer on an answer it does not describe |
| C6b | deictic referent ("this room", "here") resolved to an arbitrary sensor or declined |
| C7 | register narration misreads a status, date or field, or invents a conclusion |
| C8 | register chosen on one bare word; the lane declines with that register's statistics |
| C9 | the building holds the data and no lane reaches it (false absence) |
| C10 | document lane returns a bare fragment or internal token as the whole answer |
| C11 | catch-all "documents do not answer this" for an out-of-scope or planning request |
| C12 | open-domain question answered from general model knowledge, unlabelled |
| C13 | deliberation lane: unmapped phrase blocks the query; ranking picks out-of-band spaces |
| C14 | compare / trend fallback claims "no measured series", lists snake_case names |
| C16 | anomaly question answered from user reports, UUIDs as place names |
| C17 | future or hypothetical question answered by the current-reading lane |
| C18 | report lane answers a non-report question and recommends metadata edits |
| C19 | assorted shortcut misroutes |
| C20 | referent gate treats a descriptive phrase as a named space |
| C22 | recommend lane produces generic advice not grounded in the building |
| NEW:* | a defect no class above describes — name it, then add a class in the next codebook |

## 5 · Protocol

1. Read question, then answer. Decide the verdict from §2–§3 **before** looking at any prior label.
2. Where a claim can be checked against the building's data in under a minute, check it. Where it
   cannot, label on what the answer itself shows and mark `confidence: low`.
3. Record `verdict`, `causes`, `class`, `confidence`, and one line of `evidence` quoting the
   phrase or figure that decided it.
4. One reader. Until a second annotator exists every agreement statistic here is **intra-rater**
   and says so.

## 6 · What this codebook cannot do

It does not make a single reader independent of themselves. Labels made by the same reader who
also fixed the defects are exposed to the fix's own framing. That limit is stated in every
document that quotes a number from these reads.
