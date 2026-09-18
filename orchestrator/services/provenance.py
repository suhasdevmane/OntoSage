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

from typing import Any, Dict, List, Optional

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


def record_sql_stores(state: Any, storage_map: Dict[str, str]) -> None:
    """Record provenance for the SQL step from a {uuid: storedAt-uri} map.

    Falls back to the generic live-sensors tag when no storedAt is known.
    """
    if storage_map:
        for uri in storage_map.values():
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


def build_tags(store_keys: List[str], registry: Optional[Any]) -> List[ProvenanceTag]:
    """Map recorded store keys to ProvenanceTags (deduped by source_id)."""
    tags: List[ProvenanceTag] = []
    seen = set()
    for key in store_keys or []:
        tag: Optional[ProvenanceTag] = None
        if key in BUILTIN_PROVENANCE:
            tag = BUILTIN_PROVENANCE[key]
        elif key.startswith("store:"):
            table = key[len("store:") :]
            tag = None
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
