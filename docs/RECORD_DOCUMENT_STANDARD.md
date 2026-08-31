# The Record Document standard

**How a document becomes data a building can compute over, with no code change.**

Status: **implemented** — `orchestrator/services/record_documents.py`, wired into
`document_indexer`. This document is its contract; 14 tests pin it.

---

## The problem it solves

OntoSage indexes documents into Qdrant and retrieves passages from them. That is enough to
answer *"what does the permit policy say about hot works?"* — the passage contains the
answer. It is not enough for *"which permits are open in the basement?"*, because that
question needs rows, and you cannot aggregate over prose.

Measured across the 37 stakeholder catalogues: **703 of 2,960 questions (23.8%)** are
capped by a system this building holds only as a document. bldg1 has a permit register and
a booking log as Markdown. Both are already tables. Nothing can count them.

Design contract 2 settles the direction — *a fact that can be an RDF triple belongs in the
ontology, not in a sidecar* — so the document must **become** triples. Contract 8 settles
the constraint — *onboarding a source is drop a file and register it, never a code change*
— so the lifting must be declarative.

---

## The shape of a record document

A record document is Markdown with **YAML front-matter** and, optionally, **declared
tables**. Prose around them is preserved and indexed exactly as today; the standard adds
structure, it does not replace retrieval.

```markdown
---
record_type: permit_to_work          # selects the lifting mapping
owner: "Estates Compliance Team"     # who is accountable for these records
authority: "Cardiff University Estates"
source_system: "Permit Register"     # the system of record this describes
effective_from: 2026-01-01
version: "4.1"
review_due: 2027-01-01
simulated: true                      # declared synthetic; never inferred
tables:
  - name: "Last ten permits issued"  # matched on the preceding heading
    maps_to: permits
---

# Permit to Work Register — Abacws Building

...prose, indexed as it is today...

## Last ten permits issued

| permit | type | date | area | status |
|---|---|---|---|---|
| PTW-2026-0412 | Hot works | 2026-08-23 | Level 3 riser | Closed |
```

Every front-matter key except `tables` is **required**. They are not decoration: `owner`
and `authority` are the two most-demanded fields in the entire catalogue corpus (13,964
mentions of owner), `effective_from` is the third of the three times the catalogues insist
on keeping separate, and `simulated` is what stops a synthetic record being rendered as a
real one.

---

## The lifting mapping

One mapping per `record_type`, shipped **with the ontology** rather than with any building
— `ontology/record_documents/permit_to_work.yaml`:

```yaml
record_type: permit_to_work
class: ontosage:Permit
iri_template: "permit/{permit}"        # relative to the building's namespace
columns:
  permit:  { predicate: ontosage:recordId,     datatype: xsd:string, required: true }
  type:    { predicate: ontosage:permitKind,   datatype: xsd:string, required: true }
  date:    { predicate: ontosage:effectiveFrom, datatype: xsd:date,  required: true }
  area:    { predicate: ontosage:locationText, datatype: xsd:string }
  status:  { predicate: ontosage:recordStatus, datatype: xsd:string, required: true,
             values: { open: [Open, Issued, Active], closed: [Closed, Completed] } }
```

`values` is the one piece of interpretation the standard allows, and it is deliberately a
**declared enumeration, not inference**: "Closed, fire watch completed" maps to `closed`
because the mapping says the phrase begins with a listed term, never because a model
judged it closed. A cell matching no listed value is a validation failure, not a guess.

Because the mapping ships with the ontology, **a second building drops a document of the
same shape and gets the same triples**. That is the building-agnostic requirement, met by
construction rather than by discipline.

---

## What happens at ingest

```
document_indexer
  ├─ prose  → chunk → Qdrant documents_<building>        (unchanged)
  └─ front-matter + declared tables
        → mapping for record_type
        → RDF
        → validate against the mapping
        → named graph  <building>/documents/<document-id>
```

Four rules govern the lifting half:

**1. Validate before insert.** Every row is checked against the mapping's declared shape
— required columns present, datatypes coercible, every enumerated cell matching a declared
value. A document that does not conform is indexed as prose, reported in the ingest log,
and **not partially lifted**. Half a register is worse than none: it answers "which
permits are open" with a number that is confidently short.

The validation is structural rather than SHACL. `pyshacl` is not a dependency of this
project, and a mapping-driven check is both deterministic and stated in the same file the
author already reads — adding a shapes graph would put the contract in two places.

**2. One named graph per document.** Re-ingesting replaces that graph rather than adding
to it. Accumulating instead of replacing is exactly how CAVEAT-039 grew sensor reference
fan-out to 68.9 and made a class-listing query return 1 sensor against a true 280.

**3. Lifted facts carry their provenance.** Every instance gets
`ontosage:derivedFromDocument`, the document version, and the mapping id. Answers built on
them cite the document and its effective date.

**4. Lifted facts never outrank authored TTL.** A document is a *statement about* a system
of record, not the record itself. In `precedence.py` terms, document-derived facts sit
below `authoritative`. Without that tier a stale Markdown table silently outranks a live
register — which is precisely what BUG-194 was, and it took a live probe to find it then.

---

## What this standard is not

**Not free-prose extraction.** Nothing asks a model to read a paragraph and emit triples.
The structure is declared by the author and mapped by a file; the only judgement is
matching a cell against a listed value. Free extraction is the fabrication path this
project guards against hardest, and it would re-extract on every question.

**Not a replacement for TTL.** Where a building already has structured data, author it as
TTL and register the datasource. This standard exists for records that arrive as documents
— registers, logs, assessments, schedules — which is most of what a facilities team holds.

**Not a licence to invent records.** A synthetic record document must set
`simulated: true`, and the answer must say so. bldg1 is a real building; its synthetic
packs are labelled in the document and in the evidence record.

---

## Adopting it for an existing document

bldg1's nine compliance documents are already tabular and need only front-matter and a
mapping. Worked example — `permit_to_work_register.md`:

1. Add the front-matter block above.
2. Confirm `ontology/record_documents/permit_to_work.yaml` covers every column.
3. Re-ingest. `POST /api/v1/admin/reindex` or restart.
4. Verify by SPARQL, then by question:

```sparql
PREFIX o: <http://ontosage.org/capabilities#>
SELECT ?p ?kind ?status WHERE { ?p a o:Permit ; o:permitKind ?kind ; o:recordStatus ?status }
```

> *"How many permits are open, and where?"* must answer by `COUNT`, not by quoting the
> register. If it still quotes, the lifting did not happen — check the ingest log for a
> validation failure rather than assuming the mapping ran.

One authoring note found while writing this: every permit in the register was `Closed`. A
register with nothing open cannot demonstrate the question it exists to answer, so three
open permits and one suspended were added. Live, on bldg1:

> **Q.** How many permits to work are currently open?
> **A.** There are **3 work permits currently open** in the building.

and the mirror case, which is the other half of the point:

> **Q.** Which contracts expire in the next six months?
> **A.** **Abacws Building holds no contract records** … the ontology defines
> `ontosage:Contract`, and this building has no instances of it. To make this answerable,
> add a contract record … no code change is needed.

---

## Record types V7 defines

| `record_type` | class | task | questions capped today |
|---|---|---|---:|
| `booking` | `ontosage:Booking` | V7-T30 | 543 |
| `contract_warranty` | `ontosage:Contract` | V7-T31 | 413 |
| `handover` | `ontosage:HandoverRecord` | V7-T32 | 257 |
| `permit_to_work` | `ontosage:Permit` | V7-T33 | 160 |
| `tariff` | `ontosage:Tariff` | V7-T34 | 119 |
| `condition_survey` | `ontosage:ConditionSurvey` | V7-T36 | 99 |
| `competency` | `ontosage:CompetencyRecord` | V7-T37 | 79 |
| `risk_assessment` | `ontosage:RiskAssessment` | V7-T38 | 6 |

Counts are from `docs/V7_question_demand.csv` and **overlap** — a question blocked by both
contracts and handover appears under both. They rank the work; they do not sum.

---

*Written 2026-08-31 as the contract for V7-T18. See
[`docs/V7_IMPLEMENTATION_PLAN.md`](./V7_IMPLEMENTATION_PLAN.md) for why it is the
highest-leverage task in the plan.*
