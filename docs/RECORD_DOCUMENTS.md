# Record Documents — turning a document into queryable data

A **record document** is an ordinary Markdown file with a typed table in it. OntoSage lifts
it into RDF, so the same content that reads as a document also answers questions by SPARQL —
counted, filtered, joined and grouped, not merely quoted.

A register is **three files and no code**:

| file | what it is |
|---|---|
| `ontology/record_documents/<type>.yaml` | the mapping: which column becomes which predicate |
| `<building>/documents/<name>.md` | the document: front-matter plus a typed table |
| Module R of `ontology/ontosage_schema.ttl` | the class, its properties, and its `ontosage:layTerms` |

Adding a register requires no Python. Restart the orchestrator and the register is live.

---

## 1. The class

Declare it beneath a record root so discovery finds it, and give it lay terms so a question
can reach it:

```turtle
ontosage:Department rdfs:subClassOf ontosage:Record ; a owl:Class ;
    rdfs:label "Department"@en ;
    rdfs:comment "An organisational function that operates the building ..."@en ;
    skos:example "who do I contact about a broken door closer? -> Department whose serviceScope covers doors." .

ontosage:departmentFunction a owl:DatatypeProperty ;
    rdfs:domain ontosage:Department ; rdfs:range xsd:string ;
    rdfs:label "department function"@en .

ontosage:Department ontosage:layTerms "department", "who do i contact", "escalation route" .
```

Use `ontosage:IntervalRecord` instead of `ontosage:Record` when the thing happens over a
period with a lifecycle (bookings, permits, work orders, incidents).

**Lay terms are not optional.** Nothing is derived from part of a phrase — deliberately,
after three defects where a bare head word hijacked a lane ("Room booking" contributing
*room* pulled every wayfinding question into the register lane). A class with no lay terms is
reachable only by its full formal name. `tests/test_every_record_class_is_reachable_by_words.py`
fails if one is missing.

## 2. The mapping

```yaml
record_type: department
class: ontosage:Department
iri_template: "dept/{code}"
label_column: name

columns:
  code:
    predicate: ontosage:recordId
    datatype: xsd:string
    required: true
  function:
    predicate: ontosage:departmentFunction
    datatype: xsd:string
    required: true
  status:
    predicate: ontosage:recordStatus
    datatype: xsd:string
    required: true
    values:                       # surface forms the document may use
      active: ["Active", "In service"]
      reduced: ["Reduced", "Partial"]
```

Reuse an existing predicate wherever one fits — `ontosage:recordId`, `recordOwner`,
`recordStatus`, `locationText`, `nextDue`, `contactEmail` and many more already exist. Invent
a property only when none expresses the thing.

**The lift is all-or-nothing.** A single row failing a `required:` rule drops the whole
register with one warning line in a container log. Mark a column required only when a record
without it is meaningless — the AV register initially required an evidence reference and
refused to load over the one row that mattered most, an untested hearing loop that by
definition has no check date.

## 3. The document

```markdown
---
record_type: department
owner: "Head of Estates Operations"
authority: "Cardiff University Estates"
source_system: "Department Directory"
effective_from: 2026-09-01
version: "2026.9"
review_due: 2027-03-01
simulated: true
tables:
  - name: "Department directory"
    maps_to: departments
---

# Department Directory

| code | name | function | status |
|---|---|---|---|
| DEP-01 | Estates Operations | Runs the building day to day | Active |
```

`simulated: true` marks demonstration data. The prose above and below the table is indexed
for the document lane as usual, so a register is also a readable document.

---

## Design rules that earned their place

**Separate the fields that can disagree.** The waste register keeps the stream a system
records, the stream printed on the bin, and the aperture as three columns, because "where do
the labels conflict?" is only answerable if the conflict can be represented. The asset
register keeps design duty, commissioned duty and observed duty apart for the same reason —
one "duty" field could state neither that a unit was signed off 6% below design nor that it
now delivers 78% of what it was signed off at.

**A blank can be the finding.** An asset with no `observed_duty` has nothing measuring it,
which is exactly what an engineer asking "what is it delivering?" needs to be told. Design
the schema so the absence is expressible rather than excluded.

**Model functions, not people.** Registers are answerable by anyone the PDP admits. Personal
evacuation plans appear as a count and a review date against a floor, never as a subject;
the work-order register carries a trade, not a technician's name. A directory is the easiest
place to breach the identity stance by accident.

**Name only rooms the building has.** A lifted record is graph data, so a register naming
"Room 6.02" asserts an authoritative-looking fact about a room that does not exist, and an
answer built on it passes every honesty check. `tests/test_registers_name_rooms_the_building_has.py`
checks every room-naming column against the building's own labels, offline, before a lift.

**Compute the closing summary.** A register's bold summary sentence is prose the document
lane can quote as a headline. The department directory shipped claiming "twelve have no
out-of-hours route" when its own table said eight. Generate the sentence from the rows;
`tests/test_register_summaries_match_their_tables.py` checks the leading count.

---

## How a question reaches a register

1. `record_registry.held_record_class()` scores the question against every class's lay terms.
   Scored, not first-match, and ties break on class name so routing is deterministic.
2. `dialogue_agent` routes a matched question to `metadata`, skipping the LLM intent call —
   the building holds the answer as data.
3. `sparql_agent._whole_register()` hands the register over with no generated SPARQL. Below
   `MAX_RECORD_ROWS` the whole register goes; above it, the question's own identifiers
   (a room number, a record code, a date) scope it.
4. A question naming nothing specific against an oversized register **declines** rather than
   handing over an arbitrary slice — answering "which room has the most sessions?" from a
   fifth of the data would look authoritative and be wrong.

Two things must not silently override step 2: multi-intent decomposition (a compound
question is where a register is most useful, not least) and the document-KB probe.

## Troubleshooting

| symptom | cause |
|---|---|
| register has 0 instances | mapping missing, or a `required:` column empty in one row — check the container log for `NOT lifted` |
| questions reach the document lane instead | the class declares no `ontosage:layTerms`, or the question's words are not among them |
| a note never appears in answers | the predicate must expand to a real IRI; `rdfs:comment` written as a relative IRI is stored and never queried |
| the class exists but nothing discovers it | it is not `rdfs:subClassOf` `ontosage:Record` or `ontosage:IntervalRecord` |
| a source fix changes nothing | the graph already holds the register, and the loader skips a populated graph — `scripts/relift_registers.py --apply` forces the rewrite |

## Scripts

```bash
python scripts/relift_registers.py            # report every register and its record count
python scripts/relift_registers.py --apply    # rewrite the named graphs
```
