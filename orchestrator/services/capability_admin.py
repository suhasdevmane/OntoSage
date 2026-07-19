"""Admin CRUD for capability amenity triples (TODO-014 backend).

Guided authoring of ``ontosage:Amenity`` instances. No hand-written Turtle in guided mode —
the form fields are turned into a dual-typed (``ontosage:<Type>, ontosage:Amenity``) instance
on the building namespace. Writes go through ``input_ttl_store``, which persists them to the
building's capability TTL (``input/<bldg>_capabilities.ttl``, the source of truth) and re-syncs
its named graph, so the CapabilityGraphResolver answers them live AND they survive a restart /
GraphDB volume reset. Building-agnostic: the namespace is resolved from the active building.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from shared.config import settings
from shared.utils import get_logger

logger = get_logger(__name__)

_ONTO_NS = "http://ontosage.org/capabilities#"

# Guided mode is constrained to this vocabulary — no arbitrary classes/predicates.
# Physical amenities/facilities (dual-typed ontosage:Amenity).
AMENITY_CLASSES = (
    "Amenity",
    "PrayerRoom",
    "Cafe",
    "BikeStorage",
    "ShowerFacility",
    "ToiletFacility",
    "NursingRoom",
    "StudyArea",
    "Lift",
    "Facility",
    "Service",
)
# Non-physical knowledge topics (dual-typed ontosage:KnowledgeTopic) — how-to procedures,
# informational facts (policies/hours/contacts), and maintenance-issue reporting routes.
KNOWLEDGE_CLASSES = (
    "InformationTopic",
    "Procedure",
    "MaintenanceIssue",
)
ALL_CLASSES = AMENITY_CLASSES + KNOWLEDGE_CLASSES
_LOCALNAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_.\-]{0,63}$")


async def get_capability_classes(client: Optional[Any] = None) -> Dict[str, Any]:
    """Capability types offered by the guided "Add capability" dropdown, DERIVED FROM THE OCBV
    SCHEMA in GraphDB — the subclasses of ``ontosage:Amenity`` and ``ontosage:KnowledgeTopic``.

    This is what makes the dropdown *schema-driven*: add a new capability class to
    ``input/ontosage_schema.ttl`` and it appears in the dropdown after the next reload, no code
    change. Falls back to the built-in ``AMENITY_CLASSES`` / ``KNOWLEDGE_CLASSES`` when GraphDB is
    unreachable or the schema isn't loaded, so the console never shows an empty dropdown.

    Returns ``{"amenity": [...], "knowledge": [...], "all": [...], "source": "schema"|"builtin"}``.
    """
    from orchestrator.services.ontology_manager import run_sparql_select

    amenity: List[str] = []
    knowledge: List[str] = []
    source = "schema"
    try:
        q = (
            "PREFIX ontosage: <http://ontosage.org/capabilities#> "
            "PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#> "
            "SELECT DISTINCT ?c ?base WHERE { "
            "  { ?c rdfs:subClassOf ontosage:Amenity        . BIND('A' AS ?base) } UNION "
            "  { ?c rdfs:subClassOf ontosage:KnowledgeTopic . BIND('K' AS ?base) } "
            "  FILTER(STRSTARTS(STR(?c), STR(ontosage:))) "
            # RDFS reasoning makes subClassOf reflexive → exclude the abstract base classes so only
            # concrete, selectable capability types reach the dropdown (Amenity is re-added below).
            "  FILTER(?c != ontosage:Capability && ?c != ontosage:KnowledgeTopic) }"
        )
        res = await run_sparql_select(q, limit=200, client=client)
        if res.get("ok"):
            for row in res.get("rows", []):
                local = str(row.get("c", "")).rsplit("#", 1)[-1].rsplit("/", 1)[-1]
                if not local:
                    continue
                (amenity if row.get("base") == "A" else knowledge).append(local)
    except Exception as e:  # pragma: no cover - defensive
        logger.warning(f"[capability_admin] schema-derived class query failed: {e}")

    if not amenity and not knowledge:
        # GraphDB down / schema not loaded → keep the console working with the built-in vocabulary.
        amenity, knowledge, source = list(AMENITY_CLASSES), list(KNOWLEDGE_CLASSES), "builtin"
    else:
        # subClassOf returns the SUBclasses only — offer the base ontosage:Amenity type too (the
        # built-in list always has). KnowledgeTopic base is intentionally not offered (abstract).
        if "Amenity" not in amenity:
            amenity.insert(0, "Amenity")

    amenity = sorted(dict.fromkeys(amenity))
    knowledge = sorted(dict.fromkeys(knowledge))
    return {
        "amenity": amenity,
        "knowledge": knowledge,
        "all": amenity + knowledge,
        "source": source,
    }


# ontosage: datatype property (local name) -> guided-form API field name (matches CapabilityCreate).
# Only properties in this map are offered as form fields; their LABEL / HELP / DOMAIN come from the
# schema (get_capability_form_schema), so the form is schema-driven for everything we support.
_PROP_FIELD = {
    "layTerms": "lay_terms",
    "locationText": "location",
    "onFloor": "floor",
    "capabilityCategory": "category",
    "openingHours": "opening_hours",
    "note": "note",
    "answerText": "answer_text",
    "infoUrl": "info_url",
    "contactEmail": "contact_email",
    "contactPhone": "contact_phone",
    "reportTo": "report_to",
    "steps": "steps",
    "priority": "priority",
}
# Built-in field descriptors (domain + label + help), used when GraphDB is unreachable so the guided
# form still renders. Domains mirror input/ontosage_schema.ttl Module A.4 (+ openingHours/priority).
_FIELD_FALLBACK = [
    {
        "prop": "layTerms",
        "field": "lay_terms",
        "domain": "Capability",
        "label": "lay-term keywords",
        "help": "prayer room, quiet room, where can i pray",
    },
    {
        "prop": "locationText",
        "field": "location",
        "domain": "Amenity",
        "label": "human-readable location",
        "help": "Floor 1, room 1.04",
    },
    {
        "prop": "onFloor",
        "field": "floor",
        "domain": "Amenity",
        "label": "floor identifier",
        "help": "1 or Ground",
    },
    {
        "prop": "capabilityCategory",
        "field": "category",
        "domain": "Capability",
        "label": "capability category",
        "help": "AMENITIES / MAINTENANCE / ...",
    },
    {
        "prop": "openingHours",
        "field": "opening_hours",
        "domain": "Capability",
        "label": "opening hours",
        "help": "Mon-Fri 09:00-16:30",
    },
    {
        "prop": "note",
        "field": "note",
        "domain": "Capability",
        "label": "additional detail",
        "help": "Multi-faith, open to all.",
    },
    {
        "prop": "answerText",
        "field": "answer_text",
        "domain": "KnowledgeTopic",
        "label": "canonical answer",
        "help": "Complaints go to the Building Manager.",
    },
    {
        "prop": "infoUrl",
        "field": "info_url",
        "domain": "KnowledgeTopic",
        "label": "information URL",
        "help": "https://...",
    },
    {
        "prop": "contactEmail",
        "field": "contact_email",
        "domain": "KnowledgeTopic",
        "label": "contact email",
        "help": "estates@example.ac.uk",
    },
    {
        "prop": "contactPhone",
        "field": "contact_phone",
        "domain": "KnowledgeTopic",
        "label": "contact phone",
        "help": "029 2087 6026",
    },
    {
        "prop": "reportTo",
        "field": "report_to",
        "domain": "KnowledgeTopic",
        "label": "report to",
        "help": "Estates FM helpdesk",
    },
    {
        "prop": "steps",
        "field": "steps",
        "domain": "Procedure",
        "label": "how-to steps (semicolon-separated)",
        "help": "Note the room; Email the helpdesk",
    },
    {
        "prop": "priority",
        "field": "priority",
        "domain": "MaintenanceIssue",
        "label": "default priority",
        "help": "LOW / MEDIUM / HIGH / URGENT",
    },
]


async def get_capability_form_schema(client: Optional[Any] = None) -> List[Dict[str, str]]:
    """Guided-form FIELD descriptors DERIVED FROM THE OCBV SCHEMA — for each supported ontosage:
    datatype property, its label, help text, and DOMAIN (Capability / Amenity / KnowledgeTopic /
    Procedure / MaintenanceIssue). The console renders only the fields whose domain applies to the
    selected capability type, so the whole form (not just the type dropdown) is schema-driven.
    Falls back to the built-in descriptors when GraphDB is unreachable.
    """
    from orchestrator.services.ontology_manager import run_sparql_select

    by_prop: Dict[str, Dict[str, str]] = {}
    try:
        q = (
            "PREFIX ontosage: <http://ontosage.org/capabilities#> "
            "PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#> "
            "PREFIX owl: <http://www.w3.org/2002/07/owl#> "
            "PREFIX skos: <http://www.w3.org/2004/02/skos/core#> "
            "SELECT ?p ?domain ?label ?comment ?example WHERE { "
            "  ?p a owl:DatatypeProperty ; rdfs:domain ?domain . "
            "  OPTIONAL { ?p rdfs:label ?label } "
            "  OPTIONAL { ?p rdfs:comment ?comment } "
            "  OPTIONAL { ?p skos:example ?example } "
            "  FILTER(STRSTARTS(STR(?p), STR(ontosage:))) "
            "  FILTER(STRSTARTS(STR(?domain), STR(ontosage:))) }"
        )
        res = await run_sparql_select(q, limit=300, client=client)
        if res.get("ok"):
            for r in res.get("rows", []):
                prop = str(r.get("p", "")).rsplit("#", 1)[-1]
                field = _PROP_FIELD.get(prop)
                if not field or prop in by_prop:
                    continue  # only supported fields; first (most-specific) domain wins
                by_prop[prop] = {
                    "prop": prop,
                    "field": field,
                    "domain": str(r.get("domain", "")).rsplit("#", 1)[-1],
                    "label": r.get("label") or prop,
                    "help": r.get("example") or r.get("comment") or "",
                }
    except Exception as e:  # pragma: no cover - defensive
        logger.warning(f"[capability_admin] form-schema query failed: {e}")

    fields = list(by_prop.values()) if by_prop else [dict(f) for f in _FIELD_FALLBACK]
    order = list(_PROP_FIELD.keys())
    fields.sort(key=lambda f: order.index(f["prop"]) if f["prop"] in order else 99)
    return fields


def building_namespace(building_id: str) -> str:
    """Active building's ontology namespace; falls back to the process-global default."""
    try:
        from orchestrator.services.building_context import resolve_building_context

        return resolve_building_context(building_id).namespace
    except Exception:
        return settings.BUILDING_NAMESPACE


def _esc(s: str) -> str:
    """Escape a value for a Turtle string literal."""
    return (s or "").replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ").replace("\r", " ")


def build_amenity_ttl(
    building_id: str,
    local: str,
    cls: str,
    label: str,
    location: str = "",
    floor: str = "",
    category: str = "",
    lay_terms: str = "",
    note: str = "",
    answer_text: str = "",
    info_url: str = "",
    contact_email: str = "",
    contact_phone: str = "",
    report_to: str = "",
    steps: str = "",
    opening_hours: str = "",
    priority: str = "",
    second_type: Optional[str] = None,
) -> Dict[str, Any]:
    """Turn guided form fields into a dual-typed ontosage capability/knowledge instance.

    An amenity type dual-types ``ontosage:Amenity`` (physical facility); a knowledge type dual-types
    ``ontosage:KnowledgeTopic`` (procedure / info / maintenance issue). Only non-empty fields are
    emitted. When ``second_type`` is given (the schema-driven create path already resolved + validated
    the class against the OCBV schema), it is used as-is; otherwise the class is validated against the
    built-in vocabulary and the second type derived from it (backward-compatible for direct callers).
    Returns ``{"ok": bool, "ttl": str, "subject": str, "error": Optional[str]}``.
    """
    if second_type is None:
        if cls not in ALL_CLASSES:
            return {
                "ok": False,
                "error": f"unknown capability type '{cls}'",
                "ttl": "",
                "subject": "",
            }
        second_type = "ontosage:Amenity" if cls in AMENITY_CLASSES else "ontosage:KnowledgeTopic"
    if not _LOCALNAME_RE.match(local or ""):
        return {
            "ok": False,
            "error": "id must be a simple local name (letters, digits, _ . -)",
            "ttl": "",
            "subject": "",
        }
    if not (label or "").strip():
        return {"ok": False, "error": "label is required", "ttl": "", "subject": ""}

    ns = building_namespace(building_id)
    subject = f"{ns}{local}"
    lines = [
        f"@prefix bldg: <{ns}> .",
        f"@prefix ontosage: <{_ONTO_NS}> .",
        "@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .",
        "",
        f"bldg:{local} a ontosage:{cls}, {second_type} ;",
        f'    rdfs:label "{_esc(label)}"@en ;',
    ]
    # (property, value) pairs — only non-empty ones are emitted.
    for prop, val in (
        ("locationText", location),
        ("onFloor", floor),
        ("capabilityCategory", category),
        ("layTerms", lay_terms),
        ("answerText", answer_text),
        ("infoUrl", info_url),
        ("contactEmail", contact_email),
        ("contactPhone", contact_phone),
        ("reportTo", report_to),
        ("steps", steps),
        ("openingHours", opening_hours),
        ("priority", priority),
        ("note", note),
    ):
        if (val or "").strip():
            lines.append(f'    ontosage:{prop} "{_esc(val)}" ;')
    # Turn the trailing ' ;' of the last property into ' .'
    lines[-1] = lines[-1].rstrip().rstrip(";").rstrip() + " ."
    return {"ok": True, "ttl": "\n".join(lines) + "\n", "subject": subject, "error": None}


async def list_amenities(client: Optional[Any] = None) -> List[Dict[str, str]]:
    """Return all ontosage:Amenity instances (file-loaded + GUI-authored)."""
    from orchestrator.services.ontology_manager import run_sparql_select

    q = (
        "PREFIX ontosage: <http://ontosage.org/capabilities#> "
        "PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#> "
        "SELECT ?a ?label ?loc ?cat ?lay ?note WHERE { "
        "{ ?a a ontosage:Amenity } UNION { ?a a ontosage:KnowledgeTopic } "
        "OPTIONAL { ?a rdfs:label ?label } "
        "OPTIONAL { ?a ontosage:locationText ?loc } "
        "OPTIONAL { ?a ontosage:capabilityCategory ?cat } "
        "OPTIONAL { ?a ontosage:layTerms ?lay } "
        "OPTIONAL { ?a ontosage:note ?note } } ORDER BY ?label"
    )
    res = await run_sparql_select(q, limit=500, client=client)
    return res.get("rows", []) if res.get("ok") else []


async def create_amenity(
    building_id: str, fields: Dict[str, str], client: Optional[Any] = None
) -> Dict[str, Any]:
    """Validate + write a guided amenity into the building's capability TTL file
    (input/<bldg>_capabilities.ttl) and re-sync its named graph, so the edit persists to
    the project folder and is picked up identically on the next restart."""
    # Resolve the submitted type against the OCBV SCHEMA (subclasses in GraphDB) so any class added
    # to input/ontosage_schema.ttl is accepted + dual-typed correctly — no hardcoded class list.
    cls = fields.get("type", "")
    classes = await get_capability_classes(client=client)
    if cls not in classes["all"]:
        return {"ok": False, "error": f"unknown capability type '{cls}'", "ttl": "", "subject": ""}
    second_type = "ontosage:Amenity" if cls in classes["amenity"] else "ontosage:KnowledgeTopic"

    built = build_amenity_ttl(
        building_id,
        local=fields.get("id", ""),
        cls=cls,
        second_type=second_type,
        label=fields.get("label", ""),
        location=fields.get("location", ""),
        floor=fields.get("floor", ""),
        category=fields.get("category", ""),
        lay_terms=fields.get("lay_terms", ""),
        note=fields.get("note", ""),
        answer_text=fields.get("answer_text", ""),
        info_url=fields.get("info_url", ""),
        contact_email=fields.get("contact_email", ""),
        contact_phone=fields.get("contact_phone", ""),
        report_to=fields.get("report_to", ""),
        steps=fields.get("steps", ""),
        opening_hours=fields.get("opening_hours", ""),
        priority=fields.get("priority", ""),
    )
    if not built["ok"]:
        return built

    from orchestrator.services.input_ttl_store import upsert_amenity

    res = await upsert_amenity(building_id, built["subject"], built["ttl"], client=client)
    _reset_resolver_cache()
    return {
        "ok": bool(res.get("ok")),
        "subject": built["subject"],
        "ttl": built["ttl"],
        "file": res.get("file"),
        "error": res.get("error"),
    }


async def delete_amenity(
    building_id: str, local: str, client: Optional[Any] = None
) -> Dict[str, Any]:
    """Delete an amenity by local name from the capability TTL file (backed up to
    input/.trash/ first) and re-sync its graph, so the deletion survives a restart."""
    if not _LOCALNAME_RE.match(local or ""):
        return {"ok": False, "error": "invalid id"}
    from orchestrator.services.input_ttl_store import remove_amenity

    res = await remove_amenity(
        building_id, f"{building_namespace(building_id)}{local}", client=client
    )
    _reset_resolver_cache()
    return res


def _reset_resolver_cache() -> None:
    """Invalidate the CapabilityGraphResolver's amenity cache so edits show up live."""
    try:
        from orchestrator.services.capability_graph_resolver import (
            get_capability_graph_resolver,
        )

        r = get_capability_graph_resolver()
        r._cache = None
        r._cache_ts = 0.0
    except Exception as e:
        logger.debug(f"[capability_admin] resolver cache reset skipped: {e}")
