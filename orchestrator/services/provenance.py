"""
provenance.py — per-answer data-source provenance tags (Phase 3).

Nodes record raw *store keys* into ``state.intermediate_results["_prov_stores"]``
as they contribute to an answer; the response node maps those to
``ProvenanceTag``s (label + color + synthetic flag) and renders a chip footer.

Store-key convention:
  * built-in real stores: ``"ontology"``, ``"live_sensors"``, ``"analytics"``,
    ``"capability_kb"``, ``"documents"`` (see BUILTIN_PROVENANCE)
  * a narrow timeseries table: ``"store:<table>"`` (e.g. ``"store:occupancy_data"``)
    → mapped to the owning synthetic data source via the registry.

Everything here is a no-op unless the datasource-toggles feature is enabled and
a registry is available — so it never changes behaviour when the flag is off.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Optional

from orchestrator.services.datasource_registry import BUILTIN_PROVENANCE
from shared.models import ProvenanceTag

_PROV_KEY = "_prov_stores"

#: Fallback tag for store keys no registry entry can attribute. Deliberately NOT
#: the real "Live Sensor Data" tag: an unregistered table must never be chip-
#: labeled as real data (BUG-145). Declare the source in datasources.yaml to get
#: its true real/synthetic chip.
UNKNOWN_PROVENANCE = ProvenanceTag(
    source_id="unknown_source",
    label="Unknown Source",
    color="#9CA3AF",
    synthetic=False,
    store="",
)


def record(state: Any, store_key: str) -> None:
    """Append a store key to the answer's provenance list (deduped, order-kept)."""
    try:
        stores = state.intermediate_results.setdefault(_PROV_KEY, [])
        if store_key not in stores:
            stores.append(store_key)
    except Exception:
        pass  # provenance is best-effort; never break a node


def _table_from_storage(uri: str) -> str:
    """'bldg:occupancy_data' | 'http://…#occupancy_data' -> 'occupancy_data'."""
    s = str(uri)
    for sep in ("#", "/", ":"):
        if sep in s:
            s = s.rsplit(sep, 1)[-1]
    return s


def uuids_holding_rows(rows: Any) -> Optional[set]:
    """The uuids that appear in a fetched result, or None when the rows carry no uuid column.

    None means "cannot tell which sensors contributed", and the caller keeps the whole bound
    map rather than guessing a subset.
    """
    rows = list(rows or [])
    if not all(isinstance(r, dict) and "uuid" in r for r in rows):
        return None
    return {r["uuid"] for r in rows}


def record_sql_stores(
    state: Any,
    storage_map: Dict[str, str],
    uuids_with_rows: Optional[Iterable[str]] = None,
) -> None:
    """Record provenance for the SQL step from a {uuid: storedAt-uri} map.

    ``uuids_with_rows``, when given, restricts the stores cited to those holding a row for a
    bound uuid. The map is every sensor the SPARQL step BOUND; a store that returned nothing for
    its sensors was not a source of the answer, and citing it (BUG-1442: "Co2 Data" named for a
    turn whose co2_data read was one sensor's rows) told the reader a table contributed that did
    not. ``None`` keeps the old behaviour for result shapes that carry no uuid column.

    Falls back to the generic live-sensors tag when no storedAt is known.
    """
    if storage_map:
        bound = storage_map
        if uuids_with_rows is not None:
            wanted = set(uuids_with_rows)
            bound = {u: uri for u, uri in storage_map.items() if u in wanted}
        for uri in bound.values():
            record(state, f"store:{_table_from_storage(uri)}")
    else:
        record(state, "live_sensors")


def _tag_from_database_key(key: str) -> Optional[ProvenanceTag]:
    """A tag from the DATABASE REGISTRY entry named ``key``, by its declared ``nature`` (WB-07).

    A storage key can name a database rather than a datasource table — the wide store is
    ``database1``, declared ``nature: real`` — and every answer from it carried an
    "Unknown Source" chip. Only an explicit declaration is trusted: no entry, or no
    ``nature``, still falls through to Unknown (BUG-145's rule stands).
    """
    try:
        from orchestrator.services.adapters.registry import adapter_registry

        config = adapter_registry._load_yaml_config() or {}
        entry = (config.get("databases") or config).get(key) or {}
        nature = str(entry.get("nature") or "").strip().lower()
    except Exception:
        return None
    if nature == "real":
        return BUILTIN_PROVENANCE["live_sensors"]
    if nature in ("synthetic", "simulated"):
        return ProvenanceTag(
            source_id=f"db:{key}",
            # NOT "Simulated sensor data". This string is rendered to the reader under
            # every answer as a source chip, and the building's sensor data is a
            # PLACEHOLDER for the real feeds that will replace it -- calling it simulated
            # in the interface describes the development fixture, not the system being
            # demonstrated. The distinction is NOT lost: `synthetic=True` below and the
            # grey colour both stay, so provenance accounting and the scorecard's
            # real/synthetic share are unchanged. Only the words a reader sees change.
            label=str(entry.get("label") or "Sensor data"),
            color="#9CA3AF",
            synthetic=True,
            store=str(entry.get("type") or ""),
        )
    return None


#: Capability-lane `"provenance"` values that ANSWER the question, mapped to the BUILTIN key
#: that describes what was actually read (D3, QA-trial plan 2026-10-02). The lane writes 15
#: distinct strings (`capability_agent.py`) and none was a `BUILTIN_PROVENANCE` key, so every
#: capability-lane answer lost its chip silently — build_tags returned `[]` for all of them,
#: including the provenance lane's own answers. Values NOT listed here are declines or honest
#: absences (`referent_unverified`, `referent_not_found`, `building_profile_absent`,
#: `scenario_out_of_scope`, `absent_system_of_record`, `document_cannot_answer_live_state`,
#: `documents_do_not_answer`, `no_match`) and are deliberately left unmapped: a decline must
#: not cite a source (BUG-1401). `answer_provenance` — the provenance lane's own self-answer,
#: reading the PREVIOUS turn's stored record rather than any store — is also left unmapped on
#: purpose: it names no new data source, so the inline evidence panel (not a chip) is what
#: should ever speak for it.
_CAPABILITY_PROVENANCE_ALIASES = {
    "building_profile": "ontology",
    "live_metrics": "live_sensors",
    "capability_graph": "ontology",
    "ontology_inventory": "ontology",
    "document_answered": "documents",
    "held_register_named": "ontology",
}


def readable_source_label(source_id: str) -> str:
    """A label for a raw record id ("ontosage:WorkOrder", a timeseries UUID) that does not
    put the bare identifier in front of a reader (BUG-780, BUG-1407's shape at the chip layer).
    A UUID yields a generic noun; anything else yields its local name, spaced and titled."""
    local = source_id.rsplit("#", 1)[-1].rsplit(":", 1)[-1].rsplit("/", 1)[-1]
    if re.fullmatch(r"[0-9a-fA-F-]{32,36}", local):
        return "Sensor reading"
    spaced = re.sub(r"(?<!^)(?=[A-Z])", " ", local).replace("_", " ").strip()
    return spaced.title() if spaced else "Building record"


def label_for_string_entry(key: str) -> str:
    """The reader-facing label for a STRING `_prov_stores` entry, without needing a
    registry. Prefers the real label of a known system (`BUILTIN_PROVENANCE`, through the
    capability-lane alias map) over the generic derivation, because "Building model" is a
    better label than "Ontology" even though `readable_source_label` would produce the
    latter safely. Falls through to `readable_source_label` for anything unrecognised,
    including a `store:<table>` key -- resolving THAT to its registered datasource label
    needs the registry, which `evidence.assemble` does not hold; a readable fallback here is
    still strictly better than the bare key.
    """
    resolved = _CAPABILITY_PROVENANCE_ALIASES.get(key, key)
    if resolved in BUILTIN_PROVENANCE:
        return BUILTIN_PROVENANCE[resolved].label
    if key.startswith("store:"):
        return readable_source_label(key[len("store:") :])
    return readable_source_label(key)


def source_id_of(entry: Any) -> str:
    """The id of one `_prov_stores` entry, whichever shape a lane wrote it in (D2, QA-trial
    plan 2026-10-02). `_prov_stores` carries two shapes: a raw STORE KEY string (the original
    contract) and a dict a lane writes when it has owner/authority/version to say
    (`sparql_agent.py:1826`). THREE readers consume this one bus shape -- `build_tags` above,
    `absence_second_chance.stored_sources`, and `evidence.assemble._sources_from` -- and one
    of them already drifted once (`stored_sources`'s own docstring: reading only the dict
    shape raised `'str' object has no attribute 'get'` on every string-shape turn). Extracting
    ONE definition, used by all three, is what stops a second drift."""
    if isinstance(entry, dict):
        return str(entry.get("source_id") or entry.get("store") or "")
    if isinstance(entry, str):
        return entry
    return ""


def build_tags(store_keys: List[Any], registry: Optional[Any]) -> List[ProvenanceTag]:
    """Map recorded store entries to ProvenanceTags (deduped by source_id).

    `_prov_stores` carries two shapes (D2, QA-trial plan 2026-10-02): a raw STORE KEY string
    (the original contract) and a dict a lane writes when it has owner/authority/version to
    say (`sparql_agent.py:1826`). The dict shape used to reach `if key in BUILTIN_PROVENANCE`
    unconditionally — `TypeError: unhashable type: 'dict'`, raised inside the caller's bare
    `except Exception` logged at DEBUG, which silently dropped the ENTIRE footer (and the
    structured `sources` array built from the same list) on every register-lane turn,
    including correctly-recorded string keys sitting in the same list. A dict entry now
    builds its own tag from its own fields — it already knows more than any of the five
    BUILTIN keys could say about it — rather than being forced through a lookup meant for a
    handful of system-level stores.
    """
    tags: List[ProvenanceTag] = []
    seen = set()
    for entry in store_keys or []:
        tag: Optional[ProvenanceTag] = None
        if isinstance(entry, dict):
            sid = str(entry.get("source_id") or entry.get("store") or "unknown_source")
            tag = ProvenanceTag(
                source_id=sid,
                label=str(entry.get("label") or readable_source_label(sid)),
                color="#6B7280",
                synthetic=bool(entry.get("synthetic") or entry.get("simulated") or False),
                store=str(entry.get("store") or ""),
            )
        elif isinstance(entry, str):
            key = _CAPABILITY_PROVENANCE_ALIASES.get(entry, entry)
            if key in BUILTIN_PROVENANCE:
                tag = BUILTIN_PROVENANCE[key]
            elif key.startswith("store:"):
                table = key[len("store:") :]
                if registry is not None:
                    tag = registry.provenance_for_table(table)
                if tag is None:
                    tag = _tag_from_database_key(table)
                if tag is None:
                    tag = UNKNOWN_PROVENANCE
        if tag is not None and tag.source_id not in seen:
            tags.append(tag)
            seen.add(tag.source_id)
    return tags


#: Stores whose tag says "readings were used". A decline that states no figure did not use
#: them, whatever it fetched, so they are not cited on it (BUG-1401, the Sources half).
_READING_STORES = ("mysql", "postgres", "timescale", "cassandra", "influx", "mongo", "compute")


def is_reading_source(tag: ProvenanceTag) -> bool:
    """True for a time-series or analytics source, False for the model and the documents."""
    store = (tag.store or "").lower()
    return tag.source_id in ("live_sensors", "analytics") or store.startswith(_READING_STORES)


def tags_for_answer(tags: List[ProvenanceTag], answer: str) -> List[ProvenanceTag]:
    """The tags an answer may cite: all of them when it states a figure, else only the
    non-reading ones.

    MEASURED 2026-10-02 over 2,554 stored answers: 322 cite a sensing or metering system and
    12 of those state no figure -- every one a decline ("no purity measurement is
    available", "the data only includes energy consumption; power factor is not present").
    Listing `Occupancy Sensing System` under such an answer tells the reader that readings
    informed a conclusion drawn from their absence.
    """
    try:
        from orchestrator.services.disclosure_gate import gives_a_figure

        if gives_a_figure(answer or ""):
            return list(tags)
        return [t for t in tags if not is_reading_source(t)]
    except Exception:  # pragma: no cover - provenance must never cost the answer
        return list(tags)


def render_chips(tags: List[ProvenanceTag]) -> str:
    """Markdown footer listing sources (text fallback; the GUI uses the color hex).

    Terminals/markdown can't render arbitrary color, so this is a labeled chip
    line; the structured `sources` array carries the per-source colors.
    """
    if not tags:
        return ""
    # THE CHIP NAMES THE SOURCE, NOT THE PROVENANCE OF THE DEPLOYMENT (user decision,
    # 2026-09-16). Every reading in this deployment is placeholder data standing in for the
    # building's own feed, and it is replaced wholesale at connection time — so " · simulated"
    # described the DEPLOYMENT STAGE, not the source, and said it on every answer.
    #
    # What this does NOT change: the system still never invents a figure, still says when it
    # holds no data, and still cites which source each number came from. The `synthetic` flag
    # stays on the tag and in the structured `sources` array for anyone auditing the store;
    # it simply is not rendered as a caveat on the answer.
    return "\n\n---\n*Sources: " + " ".join(f"`{t.label}`" for t in tags) + "*"


def tags_to_dicts(tags: List[ProvenanceTag]) -> List[Dict[str, Any]]:
    """Serialize tags for the API envelope (pydantic v1/v2 tolerant)."""
    out = []
    for t in tags:
        out.append(t.model_dump() if hasattr(t, "model_dump") else t.dict())
    return out
