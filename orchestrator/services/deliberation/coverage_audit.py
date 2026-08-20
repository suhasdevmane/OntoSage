"""
coverage_audit.py — space × modality coverage matrix for the SATURATE pipeline (V4-T06).

Answers, for the ACTIVE building only: "which spaces lack which sensor modalities?"
The output gap matrix drives the saturation provisioner (V4-T08) and is itself a
reported artifact (N of M spaces instrumented per modality).

Building-agnostic by construction:
  * the namespace is an argument (callers pass the active building's);
  * spaces are discovered subclass-closure-aware — some buildings type rooms only as
    Brick room SUBCLASSES (Office/Laboratory/...), never ``a brick:Room``, others use
    ``a brick:Room`` directly — one property-path query covers both, with a
    direct-typing fallback when the Brick class hierarchy isn't loaded;
  * points are discovered through BOTH location idioms in the wild: sensors carrying
    ``brick:hasLocation`` directly, and sensors ``brick:isPointOf`` an equipment that
    is located in / feeds a space;
  * the required modality set comes from config/saturation_modalities.yaml with a
    per-building overlay — never from code.

SPARQL execution is injected (async callable returning SPARQL-JSON), matching the
referent_resolver pattern, so unit tests run fully offline.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List, Optional

import yaml

from shared.building_paths import resolve_building_file
from shared.utils import get_logger

logger = get_logger(__name__)

SparqlExec = Callable[[str], Awaitable[Dict[str, Any]]]

_PREFIXES = (
    "PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>\n"
    "PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>\n"
    "PREFIX brick: <https://brickschema.org/schema/Brick#>\n"
    "PREFIX ref: <https://brickschema.org/schema/Brick/ref#>\n"
)

# Coverage statuses
STATUS_PRESENT = "present"  # sensor of the modality exists AND has a timeseries ref
STATUS_UNBACKED = "unbacked"  # sensor modeled in TTL but no hasTimeseriesId/storedAt
STATUS_MISSING = "missing"  # no sensor of the modality located in the space

_DEFAULT_CONFIG = Path(__file__).resolve().parents[3] / "config" / "saturation_modalities.yaml"


@dataclass
class ModalitySpec:
    """One required modality: Brick class local names + optional label filter.

    ``sat`` carries the SATURATE provisioning config (brick_class, table, unit)
    when present — the auditor itself never reads it.
    """

    name: str
    brick_classes: List[str]
    label_contains: List[str] = field(default_factory=list)
    #: Substrings that DISQUALIFY a sensor from this modality even though its
    #: Brick class matches. The mirror of ``label_contains``, and the piece that
    #: was missing to split one Brick class into two populations rather than
    #: merely to name one of them (CAVEAT-207): a building may instrument the
    #: same quantity with hardware reporting different SCALES — a physical "CO2
    #: Level Sensor installed-node 5.01" reads an index around 50-80 while a
    #: provisioned sensor in the same room reads ppm. Both are CO2_Level_Sensor,
    #: so class alone cannot separate them, and scoring them against one band
    #: makes every room saturate at a perfect utility.
    label_excludes: List[str] = field(default_factory=list)
    sat: Dict[str, str] = field(default_factory=dict)

    def matches(self, class_local: str, sensor_text: str) -> bool:
        """True when a sensor typed `class_local` (labeled `sensor_text`) is this modality."""
        if class_local.lower() not in {c.lower() for c in self.brick_classes}:
            return False
        text = sensor_text.lower()
        # Exclusion is checked FIRST and wins: a sensor named by both lists is
        # ambiguous, and silently including it is the outcome that corrupts a
        # ranking, while excluding it merely narrows one.
        if self.label_excludes and any(sub.lower() in text for sub in self.label_excludes):
            return False
        if self.label_contains:
            return any(sub.lower() in text for sub in self.label_contains)
        return True


@dataclass
class SpaceCoverage:
    """Per-space audit result: modality name -> (status, sensor, uuid, stored_at)."""

    space_iri: str
    label: str = ""
    floor: str = ""
    modalities: Dict[str, Dict[str, str]] = field(default_factory=dict)


def _local(iri: str) -> str:
    """Local name of an IRI ('...#Zone_5.01' | '.../Room1' -> last segment)."""
    s = str(iri)
    for sep in ("#", "/"):
        if sep in s:
            s = s.rsplit(sep, 1)[-1]
    return s


def load_modalities(
    building_id: Optional[str] = None, config_path: Optional[Path] = None
) -> List[ModalitySpec]:
    """Load the required-modality set: shared config + per-building overlay.

    Overlay entries replace same-named base entries; new names are appended.
    """
    base_path = config_path or _DEFAULT_CONFIG
    merged: Dict[str, Dict[str, Any]] = {}
    for path in _config_candidates(base_path, building_id):
        try:
            raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except Exception as exc:  # unreadable overlay must not kill the audit
            logger.warning(f"[coverage_audit] Skipping unreadable modality config {path}: {exc}")
            continue
        for name, spec in (raw.get("modalities") or {}).items():
            merged[str(name)] = spec or {}
    specs = [
        ModalitySpec(
            name=name,
            brick_classes=[str(c) for c in (spec.get("brick_classes") or [])],
            label_contains=[str(s) for s in (spec.get("label_contains") or [])],
            label_excludes=[str(s) for s in (spec.get("label_excludes") or [])],
            sat={str(k): str(v) for k, v in (spec.get("sat") or {}).items()},
        )
        for name, spec in merged.items()
    ]
    specs = [s for s in specs if s.brick_classes]
    logger.info(f"[coverage_audit] Loaded {len(specs)} required modalities")
    return specs


def load_modality_raw(
    building_id: Optional[str] = None, config_path: Optional[Path] = None
) -> Dict[str, Dict[str, Any]]:
    """The merged modality config as raw dicts (shared config + building overlay).

    load_modalities() drops everything it does not need for the coverage audit,
    including per-building ``anchors``. Callers that need those blocks read them
    from here so there is ONE merge order — overlay replaces same-named base
    entries — rather than a second one that could disagree.
    """
    base_path = config_path or _DEFAULT_CONFIG
    merged: Dict[str, Dict[str, Any]] = {}
    for path in _config_candidates(base_path, building_id):
        try:
            raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except Exception as exc:
            logger.warning(f"[coverage_audit] Skipping unreadable modality config {path}: {exc}")
            continue
        for name, spec in (raw.get("modalities") or {}).items():
            merged[str(name)] = spec or {}
    return merged


def _config_candidates(base_path: Path, building_id: Optional[str]) -> List[Path]:
    paths: List[Path] = []
    if base_path.exists():
        paths.append(base_path)
    if building_id:
        overlay = resolve_building_file(building_id, "saturation_modalities.yaml")
        if overlay is not None:
            paths.append(overlay)
    return paths


class CoverageAuditor:
    """Builds the space × modality coverage matrix from the live graph."""

    def __init__(self, sparql_exec: SparqlExec, modalities: List[ModalitySpec]):
        self._exec = sparql_exec
        self._modalities = modalities

    # ── discovery ────────────────────────────────────────────────────────────

    async def discover_spaces(self, namespace: str) -> List[SpaceCoverage]:
        """All room-like spaces in the namespace, subclass-closure-aware."""

        def _space_query(typing_clause: str) -> str:
            return _PREFIXES + (
                "SELECT DISTINCT ?space ?label ?floor WHERE {\n"
                f"  {typing_clause}\n"
                "  OPTIONAL { ?space rdfs:label ?label }\n"
                "  OPTIONAL { ?space brick:isPartOf ?floor . ?floor a brick:Floor }\n"
                f'  FILTER(STRSTARTS(STR(?space), "{namespace}"))\n'
                "} LIMIT 5000"
            )

        rows = _bindings(
            await self._exec(_space_query("?space a ?cls . ?cls rdfs:subClassOf* brick:Room ."))
        )
        if not rows:
            # Brick class hierarchy not loaded in this repo — direct typing only.
            logger.warning(
                "[coverage_audit] subclass-closure space query returned 0 — "
                "falling back to direct `a brick:Room` typing"
            )
            rows = _bindings(await self._exec(_space_query("?space a brick:Room .")))
        spaces: Dict[str, SpaceCoverage] = {}
        for b in rows:
            iri = _val(b, "space")
            if not iri:
                continue
            sc = spaces.setdefault(iri, SpaceCoverage(space_iri=iri))
            sc.label = sc.label or _val(b, "label") or _local(iri)
            sc.floor = sc.floor or _local(_val(b, "floor"))
        logger.info(f"[coverage_audit] Discovered {len(spaces)} spaces in {namespace}")
        return list(spaces.values())

    _POINTS_PAGE = 20000

    async def discover_points(self, namespace: str) -> List[Dict[str, str]]:
        """All sensors joined to a space via either location idiom, with ts refs.

        Paginated (BUG-161): a densely-instrumented building can exceed one
        page of located points, and a single LIMIT silently dropped every
        sensor beyond it, reporting saturated modalities as 0% coverage.
        ORDER BY makes OFFSET paging deterministic.
        """
        body = (
            "SELECT DISTINCT ?sensor ?cls ?space ?label ?uuid ?stored WHERE {\n"
            "  ?sensor a ?cls .\n"
            "  { ?sensor brick:hasLocation ?space }\n"
            "  UNION { ?sensor brick:isPointOf ?eq . ?eq brick:hasLocation ?space }\n"
            "  UNION { ?sensor brick:isPointOf ?eq . ?eq brick:feeds ?space }\n"
            # a sensor located in (or feeding) a ZONE covers the room(s) the zone
            # hasPart — but a floor's hasPart must never grant floor-wide coverage
            "  UNION { ?sensor brick:hasLocation ?zone . ?zone brick:hasPart ?space .\n"
            "          FILTER NOT EXISTS { ?zone a brick:Floor } }\n"
            "  UNION { ?sensor brick:isPointOf ?eq2 . ?eq2 brick:feeds ?zone2 .\n"
            "          ?zone2 brick:hasPart ?space .\n"
            "          FILTER NOT EXISTS { ?zone2 a brick:Floor } }\n"
            "  OPTIONAL { ?sensor rdfs:label ?label }\n"
            "  OPTIONAL {\n"
            "    ?sensor ref:hasExternalReference ?r .\n"
            "    ?r ref:hasTimeseriesId ?uuid .\n"
            "    OPTIONAL { ?r ref:storedAt ?stored }\n"
            "  }\n"
            f'  FILTER(STRSTARTS(STR(?sensor), "{namespace}"))\n'
            "} ORDER BY ?sensor ?cls ?space"
        )
        rows: List[Dict] = []
        offset = 0
        while True:
            page = _bindings(
                await self._exec(_PREFIXES + body + f" LIMIT {self._POINTS_PAGE} OFFSET {offset}")
            )
            rows.extend(page)
            if len(page) < self._POINTS_PAGE:
                break
            offset += self._POINTS_PAGE
        points = [
            {
                "sensor": _val(b, "sensor"),
                "class_local": _local(_val(b, "cls")),
                "space": _val(b, "space"),
                "text": (_val(b, "label") or _local(_val(b, "sensor"))),
                "uuid": _val(b, "uuid"),
                "stored_at": _local(_val(b, "stored")),
            }
            for b in rows
            if _val(b, "sensor") and _val(b, "space")
        ]
        logger.info(f"[coverage_audit] Discovered {len(points)} located points")
        return points

    # ── audit ────────────────────────────────────────────────────────────────

    async def audit(self, namespace: str) -> List[SpaceCoverage]:
        """Full matrix: every discovered space × every required modality."""
        spaces = await self.discover_spaces(namespace)
        points = await self.discover_points(namespace)
        by_space: Dict[str, List[Dict[str, str]]] = {}
        for p in points:
            by_space.setdefault(p["space"], []).append(p)

        for sc in spaces:
            for spec in self._modalities:
                # V5-T09: floor/building-scoped modalities are not per-room
                # requirements — they never enter the room coverage matrix.
                if str((spec.sat or {}).get("scope", "room")).lower() != "room":
                    continue
                best: Dict[str, str] = {
                    "status": STATUS_MISSING,
                    "sensor": "",
                    "uuid": "",
                    "stored_at": "",
                }
                for p in by_space.get(sc.space_iri, []):
                    if not spec.matches(p["class_local"], p["text"]):
                        continue
                    if p["uuid"] and p["stored_at"]:
                        best = {
                            "status": STATUS_PRESENT,
                            "sensor": p["sensor"],
                            "uuid": p["uuid"],
                            "stored_at": p["stored_at"],
                        }
                        break  # contract #8 satisfied — done for this modality
                    if best["status"] == STATUS_MISSING:
                        best = {
                            "status": STATUS_UNBACKED,
                            "sensor": p["sensor"],
                            "uuid": p["uuid"],
                            "stored_at": p["stored_at"],
                        }
                sc.modalities[spec.name] = best
        return spaces

    # ── reporting ────────────────────────────────────────────────────────────

    @staticmethod
    def to_rows(building_id: str, spaces: List[SpaceCoverage]) -> List[Dict[str, str]]:
        """Flatten the matrix into gap-CSV rows (one row per space × modality)."""
        rows: List[Dict[str, str]] = []
        for sc in sorted(spaces, key=lambda s: (s.floor, s.label)):
            for modality, entry in sc.modalities.items():
                rows.append(
                    {
                        "building_id": building_id,
                        "space_iri": sc.space_iri,
                        "space_label": sc.label,
                        "floor": sc.floor,
                        "modality": modality,
                        "status": entry["status"],
                        "sensor_iri": entry["sensor"],
                        "uuid": entry["uuid"],
                        "stored_at": entry["stored_at"],
                    }
                )
        return rows

    @staticmethod
    def summary(spaces: List[SpaceCoverage]) -> Dict[str, Dict[str, int]]:
        """Per-modality counts: {modality: {present, unbacked, missing, total}}."""
        out: Dict[str, Dict[str, int]] = {}
        for sc in spaces:
            for modality, entry in sc.modalities.items():
                agg = out.setdefault(
                    modality, {STATUS_PRESENT: 0, STATUS_UNBACKED: 0, STATUS_MISSING: 0, "total": 0}
                )
                agg[entry["status"]] += 1
                agg["total"] += 1
        return out


# ── SPARQL-JSON helpers ──────────────────────────────────────────────────────


def _bindings(result: Dict[str, Any]) -> List[Dict[str, Any]]:
    try:
        return list((result.get("results") or {}).get("bindings") or [])
    except AttributeError:
        return []


def _val(binding: Dict[str, Any], var: str) -> str:
    entry = binding.get(var)
    if isinstance(entry, dict):
        return str(entry.get("value") or "")
    return ""
