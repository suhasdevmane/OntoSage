# -*- coding: utf-8 -*-
"""Lift a record document's front-matter and tables into RDF (V7-T18).

A building's permit register, booking log and contract schedule arrive as documents. The
retrieval lane can quote them; it cannot count them. "What does the permit policy say?"
works because the passage contains the answer; "how many permits are open?" does not,
because you cannot aggregate over prose. Measured across the 37 stakeholder catalogues,
703 of 2,960 questions are capped by exactly that.

Design contract 2 settles the direction — a fact that can be a triple belongs in the
ontology — so the document must BECOME triples. Contract 8 settles the constraint —
onboarding a source is dropping a file, never a code change — so the lifting is declared
in a mapping rather than written in Python.

    document (input/documents/*.md)      one per building, authored by whoever owns it
      + mapping (ontology/record_documents/<record_type>.yaml)   ships with the ONTOLOGY
      = RDF in a named graph, one graph per document

Because the mapping ships with the ontology and not with the building, a second building
drops a document of the same shape and gets the same triples with no code change. That is
what makes this building-agnostic rather than merely parameterised.

**What is deliberately NOT here.** Nothing asks a model to read prose and emit triples.
The structure is declared by the author and mapped by a file; the only interpretation
allowed is matching a cell against a value list the mapping itself declares. Free-prose
extraction is the fabrication path this project guards against hardest, and it would
re-extract on every question.

See ``docs/RECORD_DOCUMENT_STANDARD.md`` for the authoring contract.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml

from shared.utils import get_logger

logger = get_logger(__name__)

ONTOSAGE = "http://ontosage.org/capabilities#"
XSD = "http://www.w3.org/2001/XMLSchema#"
RDF_TYPE = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"
RDFS_LABEL = "http://www.w3.org/2000/01/rdf-schema#label"

#: Front-matter keys every record document must declare. None is decoration: owner and
#: authority are the two most-demanded fields in the whole catalogue corpus, effective_from
#: is the third of the three times the catalogues insist on separating, and simulated is
#: what stops a synthetic record being rendered as a real one.
REQUIRED_FRONT_MATTER = (
    "record_type",
    "owner",
    "authority",
    "source_system",
    "effective_from",
    "version",
    "simulated",
)

_FRONT_MATTER = re.compile(r"\A\s*---\s*\n(.*?)\n---\s*\n", re.DOTALL)
_HEADING = re.compile(r"^#{1,6}\s+(.*?)\s*$")
_TABLE_ROW = re.compile(r"^\s*\|(.+)\|\s*$")
_TABLE_RULE = re.compile(r"^\s*\|[\s:|-]+\|\s*$")
_IRI_SLOT = re.compile(r"\{([a-z0-9_]+)\}", re.IGNORECASE)
_UNSAFE_IRI = re.compile(r"[^A-Za-z0-9_.\-]")


@dataclass
class ColumnSpec:
    """How one table column becomes one predicate."""

    predicate: str
    datatype: str = "xsd:string"
    required: bool = False
    #: Declared value list: {canonical: [accepted, phrasings]}. The ONLY interpretation
    #: this module performs, and it is a lookup, not a judgement.
    values: Dict[str, List[str]] = field(default_factory=dict)


@dataclass
class RecordMapping:
    """One record_type's lifting rules, loaded from the ontology."""

    record_type: str
    class_iri: str
    iri_template: str
    columns: Dict[str, ColumnSpec]
    label_column: str = ""


@dataclass
class LiftResult:
    """What a lift produced, and why it produced nothing when it did.

    ``errors`` being non-empty means NOTHING was lifted. A half-lifted register answers
    "which permits are open" with a number that is confidently short, which is worse than
    declining — so the failure is total and reported, never partial.
    """

    document: str
    record_type: str = ""
    triples: List[Tuple[str, str, Any]] = field(default_factory=list)
    instances: int = 0
    errors: List[str] = field(default_factory=list)
    graph_iri: str = ""

    @property
    def ok(self) -> bool:
        return not self.errors and self.instances > 0


# ── parsing ────────────────────────────────────────────────────────────────────────


def parse_front_matter(text: str) -> Tuple[Dict[str, Any], str]:
    """Split a document into its YAML front-matter and its body.

    A document with no front-matter is not a record document — it returns an empty dict
    and its whole text, so the caller indexes it as prose exactly as before. Adding the
    lifter must not change how any existing document behaves.
    """
    match = _FRONT_MATTER.match(text)
    if not match:
        return {}, text
    try:
        loaded = yaml.safe_load(match.group(1)) or {}
    except yaml.YAMLError as exc:
        logger.warning(f"[record_documents] front-matter is not valid YAML: {exc}")
        return {}, text
    if not isinstance(loaded, dict):
        return {}, text
    return loaded, text[match.end() :]


def parse_tables(body: str) -> List[Tuple[str, List[Dict[str, str]]]]:
    """Every Markdown table in the body, paired with the heading it sits under.

    The heading is how a mapping names the table it wants, so a document may carry
    several tables and lift only the ones it declares.
    """
    tables: List[Tuple[str, List[Dict[str, str]]]] = []
    heading = ""
    header: List[str] = []
    rows: List[Dict[str, str]] = []

    def _flush() -> None:
        nonlocal header, rows
        if header and rows:
            tables.append((heading, rows))
        header, rows = [], []

    def _cells(line: str) -> List[str]:
        return [c.strip() for c in _TABLE_ROW.match(line).group(1).split("|")]

    for line in body.splitlines():
        head = _HEADING.match(line)
        if head:
            _flush()
            heading = head.group(1).strip()
            continue
        if _TABLE_RULE.match(line):
            continue  # the |---|---| separator
        if _TABLE_ROW.match(line):
            cells = _cells(line)
            if not header:
                header = [c.lower() for c in cells]
            elif len(cells) == len(header):
                rows.append(dict(zip(header, cells)))
            continue
        if line.strip() == "":
            continue
        # Prose after a table ends it; prose before one is ignored.
        if header and rows:
            _flush()
        elif header:
            header = []
    _flush()
    return tables


def load_mapping(record_type: str, mappings_dir: Path) -> Optional[RecordMapping]:
    """Load the lifting rules for a record_type from the ONTOLOGY, not the building."""
    path = mappings_dir / f"{record_type}.yaml"
    if not path.is_file():
        return None
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        logger.warning(f"[record_documents] mapping {path.name} is not valid YAML: {exc}")
        return None
    columns = {
        name: ColumnSpec(
            predicate=spec.get("predicate", ""),
            datatype=spec.get("datatype", "xsd:string"),
            required=bool(spec.get("required", False)),
            values={k: list(v) for k, v in (spec.get("values") or {}).items()},
        )
        for name, spec in (raw.get("columns") or {}).items()
    }
    return RecordMapping(
        record_type=raw.get("record_type", record_type),
        class_iri=_expand(raw.get("class", "")),
        iri_template=raw.get("iri_template", f"{record_type}/{{row}}"),
        columns=columns,
        label_column=raw.get("label_column", ""),
    )


# ── lifting ────────────────────────────────────────────────────────────────────────


def _expand(term: str) -> str:
    """ontosage:Permit -> full IRI. Already-absolute IRIs pass through."""
    if term.startswith("http://") or term.startswith("https://"):
        return term
    if term.startswith("ontosage:"):
        return ONTOSAGE + term.split(":", 1)[1]
    if term.startswith("xsd:"):
        return XSD + term.split(":", 1)[1]
    return term


def _coerce(value: str, datatype: str, spec: ColumnSpec) -> Tuple[Any, Optional[str]]:
    """Turn a cell into a typed literal, or say why it cannot be one.

    A cell that matches no declared value is an ERROR, never a guess. That is the whole
    difference between this and prose extraction: "Closed, fire watch completed" becomes
    `closed` because the mapping lists the phrase, not because anything judged it closed.
    """
    text = (value or "").strip()
    if not text:
        return None, None

    if spec.values:
        low = text.lower()
        for canonical, accepted in spec.values.items():
            if any(low.startswith(a.lower()) for a in accepted):
                return canonical, None
        return None, f"value {text!r} matches none of {sorted(spec.values)}"

    short = datatype.split(":")[-1]
    try:
        if short == "date":
            return date.fromisoformat(text[:10]).isoformat(), None
        if short == "dateTime":
            return datetime.fromisoformat(text.replace("Z", "+00:00")).isoformat(), None
        if short == "integer":
            return int(re.sub(r"[^\d-]", "", text)), None
        if short == "decimal":
            return float(re.sub(r"[^\d.\-]", "", text)), None
        if short == "boolean":
            return text.lower() in ("true", "yes", "y", "1"), None
    except (ValueError, TypeError):
        return None, f"{text!r} is not a valid {short}"
    return text, None


def _slug(value: str) -> str:
    return _UNSAFE_IRI.sub("_", (value or "").strip()) or "unknown"


def lift_document(
    path: Path,
    namespace: str,
    mappings_dir: Path,
    retrieved_at: Optional[datetime] = None,
) -> LiftResult:
    """Lift one record document into triples, or explain why it lifted nothing.

    Returns an empty result with no errors for an ordinary document — one with no
    front-matter is simply not a record document, and that is not a failure.
    """
    result = LiftResult(document=path.name)
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        result.errors.append(f"unreadable: {exc}")
        return result

    front, body = parse_front_matter(text)
    if not front or "record_type" not in front:
        return result  # an ordinary document; prose indexing is unaffected

    result.record_type = str(front.get("record_type", ""))

    missing = [k for k in REQUIRED_FRONT_MATTER if k not in front]
    if missing:
        result.errors.append(f"front-matter missing required keys: {', '.join(missing)}")
        return result

    mapping = load_mapping(result.record_type, mappings_dir)
    if mapping is None:
        result.errors.append(f"no mapping for record_type {result.record_type!r} in {mappings_dir}")
        return result

    declared = {
        str(t.get("name", "")).strip().lower(): str(t.get("maps_to", "")).strip()
        for t in (front.get("tables") or [])
        if isinstance(t, dict)
    }
    tables = parse_tables(body)
    wanted = [(h, rows) for h, rows in tables if h.strip().lower() in declared]
    if not wanted:
        result.errors.append(
            "front-matter declares tables "
            f"{sorted(declared) or '[]'} but the body has {[h for h, _ in tables] or '[]'}"
        )
        return result

    graph_iri = f"{namespace}documents/{_slug(path.stem)}"
    result.graph_iri = graph_iri
    triples: List[Tuple[str, str, Any]] = []
    seen: set = set()

    for heading, rows in wanted:
        for index, row in enumerate(rows, start=1):
            slots = {k: v for k, v in row.items()}
            slots["row"] = str(index)
            try:
                local = _IRI_SLOT.sub(
                    lambda m: _slug(slots.get(m.group(1), "")), mapping.iri_template
                )
            except Exception as exc:  # pragma: no cover - template is author-controlled
                result.errors.append(f"{heading} row {index}: bad iri_template ({exc})")
                continue
            subject = f"{namespace}{local}"
            if subject in seen:
                result.errors.append(
                    f"{heading} row {index}: iri_template produced a duplicate subject "
                    f"{local!r} — two records would be merged into one"
                )
                continue

            row_triples: List[Tuple[str, str, Any]] = [(subject, RDF_TYPE, mapping.class_iri)]
            for column, spec in mapping.columns.items():
                if column not in row:
                    if spec.required:
                        result.errors.append(f"{heading} row {index}: missing column {column!r}")
                    continue
                value, why = _coerce(row[column], spec.datatype, spec)
                if why:
                    result.errors.append(f"{heading} row {index}, column {column!r}: {why}")
                    continue
                if value is None:
                    if spec.required:
                        result.errors.append(f"{heading} row {index}: {column!r} is empty")
                    continue
                row_triples.append((subject, _expand(spec.predicate), value))

            if mapping.label_column and row.get(mapping.label_column):
                row_triples.append((subject, RDFS_LABEL, row[mapping.label_column]))

            # Provenance travels with every lifted fact. Without derivedFromDocument a
            # stale table silently outranks a live register, which is what BUG-194 was.
            stamp = (retrieved_at or datetime.now()).replace(microsecond=0).isoformat()
            row_triples += [
                (subject, ONTOSAGE + "derivedFromDocument", path.name),
                (subject, ONTOSAGE + "liftedByMapping", mapping.record_type),
                (subject, ONTOSAGE + "recordOwner", str(front["owner"])),
                (subject, ONTOSAGE + "owningAuthority", str(front["authority"])),
                (subject, ONTOSAGE + "recordVersion", str(front["version"])),
                (subject, ONTOSAGE + "retrievedAt", stamp),
                (subject, ONTOSAGE + "isSimulated", bool(front["simulated"])),
            ]
            if not any(p.endswith("effectiveFrom") for _, p, _ in row_triples):
                row_triples.append(
                    (subject, ONTOSAGE + "effectiveFrom", str(front["effective_from"]))
                )
            seen.add(subject)
            triples.extend(row_triples)

    if result.errors:
        # Total, not partial: half a register is a confidently short answer.
        return result

    result.triples = triples
    result.instances = len(seen)
    return result


def to_turtle(result: LiftResult) -> str:
    """Serialise a lift to Turtle for upload into its named graph."""
    lines = [
        "@prefix ontosage: <http://ontosage.org/capabilities#> .",
        "@prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .",
        "@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .",
        "@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .",
        "",
    ]
    for subject, predicate, value in result.triples:
        lines.append(f"<{subject}> <{predicate}> {_literal(value)} .")
    return "\n".join(lines) + "\n"


def _literal(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return f'"{value}"^^xsd:integer'
    if isinstance(value, float):
        return f'"{value}"^^xsd:decimal'
    text = str(value)
    if text.startswith("http://") or text.startswith("https://"):
        return f"<{text}>"
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        return f'"{text}"^^xsd:date'
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}T[\d:.+\-]+", text):
        return f'"{text}"^^xsd:dateTime'
    escaped = text.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
    return f'"{escaped}"'
