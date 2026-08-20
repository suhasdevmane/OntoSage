"""
dwg_pipeline.py — AutoCAD DWG ingestion pipeline (Phase DW1 + DW2).

Converts DWG floor plan files to spatial data:
  1. discover   — find DWG files in /app/input/ matching building pattern
  2. fingerprint — SHA-256; skip if intermediate manifest up to date
  3. convert    — dwg2dxf (libredwg-utils) → DXF in /tmp/
  4. parse      — ezdxf: layers, polylines, text, INSERT blocks
  5. geometry   — shapely: area, perimeter, adjacency (distance < 0.6 m)
  6. normalise  — world coords → [0,1] with Y-flip
  7. write      — intermediate floor_N.dwg_manifest.json

Public API:
    pipeline = DWGPipeline()
    manifests = await pipeline.ingest_all()            # startup: all DWG files
    manifest  = await pipeline.ingest_file(Path(...))  # single file
    manifest  = pipeline.load_manifest("abacws", 3)    # read cached result
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Tuple

from shared.building_paths import resolve_building_file
from shared.floor_plan_config import BuildingConfig, default_config
from shared.models import (
    Block,
    FloorPlanManifest,
    NormalisedPoint,
    RenderedImage,
    Space,
)
from shared.utils import get_logger

logger = get_logger(__name__)

_DEFAULT_INPUT_DIR = Path("/app/input")
_DEFAULT_MANIFEST_DIR = Path("/app/floor_plans")

_DWG_PATTERN = re.compile(
    r"^(?P<building>.+?)\s+floor\s+(?P<floor>\d+)\.(?:dwg|dxf)$",
    re.IGNORECASE,
)

# Unit scale factors: DXF INSUNITS → metres
_UNIT_TO_M: Dict[int, float] = {
    1: 0.0254,  # inches
    2: 0.3048,  # feet
    4: 0.001,  # mm
    5: 0.01,  # cm
    6: 1.0,  # metres (default)
    7: 1000.0,  # km
}

# Block name → BlockType mapping (regex patterns)
_BLOCK_TYPE_RULES: List[Tuple[str, str]] = [
    (r"(?i)^DR|DOOR", "door"),
    (r"(?i)WIN|GLAZING", "window"),
    (r"(?i)FIRE[_-]?EXIT|EMERG", "fire_exit"),
    (r"(?i)SENSOR|TEMP|CO2|HUM|MOTION", "sensor"),
    (r"(?i)DIFF|DIFFUSER|SUPPLY|EXTRACT", "hvac_diffuser"),
    (r"(?i)FIRE[_-]?ALARM|FA[_-]?", "fire_alarm"),
    (r"(?i)LIGHT|LGHT|LUX|LAMP", "light_fixture"),
    (r"(?i)POWER|SOCKET|OUTLET", "power_outlet"),
    (r"(?i)EQUIP|MECH|PLANT|PUMP", "equipment"),
]


def _slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


# Label keyword → space type (longest-match wins)
_SPACE_TYPE_KEYWORDS: List[Tuple[str, str]] = [
    ("server", "server_room"),
    ("plant room", "utility"),
    ("plant", "utility"),
    ("electrical", "utility"),
    ("cleaner", "utility"),
    ("janitor", "utility"),
    ("storage", "storage"),
    ("store", "storage"),
    ("stair", "staircase"),
    ("lift", "lift"),
    ("elevator", "lift"),
    ("toilet", "toilet"),
    ("wc", "toilet"),
    ("bathroom", "toilet"),
    ("shower", "toilet"),
    ("kitchen", "kitchen"),
    ("breakout", "kitchen"),
    ("canteen", "kitchen"),
    ("cafe", "kitchen"),
    ("reception", "reception"),
    ("lobby", "reception"),
    ("corridor", "corridor"),
    ("hallway", "corridor"),
    ("landing", "corridor"),
    ("lecture", "lecture"),
    ("seminar", "classroom"),
    ("classroom", "classroom"),
    ("teaching", "classroom"),
    ("laboratory", "lab"),
    ("lab", "lab"),
    ("meeting", "meeting_room"),
    ("conference", "meeting_room"),
    ("board room", "meeting_room"),
    ("office", "office"),
    ("study", "office"),
    ("workspace", "office"),
    ("open plan", "office"),
]


def _classify_space_type_from_label(label: str) -> str:
    """Return a space type string based on keyword presence in label (case-insensitive)."""
    lower = label.lower()
    # Try longest keyword first to prefer specific matches
    for keyword, stype in sorted(_SPACE_TYPE_KEYWORDS, key=lambda x: -len(x[0])):
        if keyword in lower:
            return stype
    return "zone"


def _classify_block_type(block_name: str) -> str:
    for pattern, btype in _BLOCK_TYPE_RULES:
        if re.search(pattern, block_name):
            return btype
    return "unknown"


def _strip_mtext_codes(text: str) -> str:
    """Remove AutoCAD MTEXT formatting codes, preserving visible content."""
    # Strip inline code directives like \H2.5; \W1.2; \f...; etc.
    text = re.sub(r"\\[A-Za-z][^;]*;", "", text)
    # Strip braces but keep their contents
    text = text.replace("{", "").replace("}", "")
    # Strip paragraph/line codes \P \p \N \n \L \l
    text = re.sub(r"\\[PpNnLl]", " ", text)
    return text.strip()


async def _run_in_executor(fn, *args):
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, fn, *args)


#: Layer roles that are definitively NOT room boundaries. Used only by the
#: fallback path, where no layer was recognised as holding rooms.
_NON_ROOM_ROLES = frozenset(
    {
        "furniture",
        "annotation",
        "room_label",
        "dimension",
        "gross_area",
        "circulation",
        "wall",
        "door",
        "window",
        "equipment",
        "hvac",
        "lighting",
        "power",
        "fire_protection",
        "plumbing",
        "staircase",
        "lift",
        "mechanical",
    }
)


class DWGPipeline:
    """
    Idempotent pipeline that converts DWG floor plan files to spatial manifests.
    One instance is shared across the application lifecycle.
    """

    def __init__(
        self,
        input_dir: Optional[Path] = None,
        manifest_dir: Optional[Path] = None,
        graphdb_url: Optional[str] = None,
    ) -> None:
        self._input_dir = input_dir or _DEFAULT_INPUT_DIR
        self._manifest_dir = manifest_dir or _DEFAULT_MANIFEST_DIR
        from shared.config import settings

        self._graphdb_url = graphdb_url or getattr(settings, "GRAPHDB_URL", "http://graphdb:7200")

    # ── Lifecycle ──────────────────────────────────────────────────────────────

    async def ingest_all(self) -> List[FloorPlanManifest]:
        """Ingest all DWG files found in input_dir. Idempotent."""
        if not self._input_dir.exists():
            logger.warning(f"[dwg_pipeline] Input dir not found: {self._input_dir}")
            return []
        results: List[FloorPlanManifest] = []
        # Accept .dwg (converted via dwg2dxf) and .dxf (the CAD interchange format, read
        # directly — also lets tool-exported/synthetic plans skip a lossy DWG round-trip).
        _cad_files = sorted([*self._input_dir.glob("*.dwg"), *self._input_dir.glob("*.dxf")])
        for dwg_path in _cad_files:
            try:
                manifest = await self.ingest_file(dwg_path)
                if manifest:
                    results.append(manifest)
            except Exception as e:
                logger.error(f"[dwg_pipeline] Failed to ingest {dwg_path.name}: {e}", exc_info=True)
        return results

    async def ingest_file(self, dwg_path: Path) -> Optional[FloorPlanManifest]:
        """Ingest one DWG file through all 7 steps."""
        m = _DWG_PATTERN.match(dwg_path.name)
        if not m:
            logger.debug(f"[dwg_pipeline] Skipping non-floor-plan DWG: {dwg_path.name}")
            return None

        building_name = m.group("building")
        building_id = _slugify(building_name)
        floor = int(m.group("floor"))
        cfg = self._load_config(building_id)

        manifest_path = self._manifest_path(building_id, floor)

        logger.info(
            f"[dwg_pipeline] Ingesting {dwg_path.name} → building={building_id}, floor={floor}"
        )

        # Step 2: fingerprint — skip if unchanged
        sha = _sha256_file(dwg_path)
        if manifest_path.exists():
            try:
                existing = FloorPlanManifest.model_validate_json(manifest_path.read_text("utf-8"))
                if existing.source_dwg_sha256 == sha:
                    logger.info(f"[dwg_pipeline] {dwg_path.name} unchanged — skipping.")
                    return existing
            except Exception:
                pass

        # Step 3: obtain a DXF. A .dxf is read directly; a .dwg is converted via dwg2dxf.
        if dwg_path.suffix.lower() == ".dxf":
            dxf_path, convert_warnings = dwg_path, []
        else:
            dxf_path, convert_warnings = await _run_in_executor(self._convert_to_dxf, dwg_path)
        if dxf_path is None:
            logger.error(
                f"[dwg_pipeline] DWG→DXF conversion failed for {dwg_path.name} — aborting."
            )
            return None

        # Step 4–6: parse + geometry + normalise (blocking, run in executor)
        parse_result = await _run_in_executor(
            self._parse_dxf, dxf_path, building_id, floor, cfg, sha
        )

        spaces, blocks, layers, units, bounding_box, parse_warnings = parse_result
        all_warnings = convert_warnings + parse_warnings

        # DW3: Link sensor TAG attributes in blocks → ontology IRIs
        link_warnings = await self._link_sensor_blocks(blocks, spaces, building_id)
        all_warnings.extend(link_warnings)

        # Compute total area
        total_area = sum(s.area_m2 for s in spaces if s.area_m2 is not None)

        # Build facilities map
        facilities: Dict[str, List[str]] = {}
        for space in spaces:
            if space.type not in ("unknown", "zone", "corridor"):
                facilities.setdefault(space.type, []).append(space.zone_id)

        # Build adjacency dict
        adjacency: Dict[str, List[str]] = {
            s.zone_id: s.adjacent_spaces for s in spaces if s.adjacent_spaces
        }

        # Build layer summary list
        layer_summary = [{"name": name, "role": role} for name, role in layers.items()]

        # Placeholder rendered_image (PDF pipeline will provide the real PNG)
        rendered_image = RenderedImage(
            png_url="",
            thumbnail_url="",
            width_px=0,
            height_px=0,
            dpi=0,
        )

        from datetime import datetime

        manifest = FloorPlanManifest(
            schema_version="2.0",
            building_id=building_id,
            building_name=building_name,
            floor=floor,
            floor_label=cfg.floor_label(floor),
            source_pdf="",
            source_sha256="",
            source_dwg=dwg_path.name,
            source_dwg_sha256=sha,
            dwg_units=units,
            data_sources=["dwg"],
            generated_at=datetime.utcnow(),
            generator_version="2.0.0",
            rendered_image=rendered_image,
            pdf_url="",
            bounding_box=bounding_box,
            spaces=spaces,
            blocks=blocks,
            layers=layer_summary,
            facilities=facilities,
            total_area_m2=total_area if total_area > 0 else None,
            adjacency=adjacency,
            warnings=all_warnings,
        )

        # Step 7: write intermediate manifest
        manifest_path.write_text(manifest.model_dump_json(indent=2), encoding="utf-8")
        logger.info(
            f"[dwg_pipeline] {dwg_path.name} → {len(spaces)} spaces, "
            f"{len(blocks)} blocks, total_area={total_area:.1f}m²"
        )
        return manifest

    # ── Manifest I/O ──────────────────────────────────────────────────────────

    def _manifest_path(self, building_id: str, floor: int) -> Path:
        d = self._manifest_dir / building_id
        d.mkdir(parents=True, exist_ok=True)
        return d / f"floor_{floor}.dwg_manifest.json"

    def load_manifest(self, building_id: str, floor: int) -> Optional[FloorPlanManifest]:
        """Load a DWG intermediate manifest from disk (synchronous)."""
        p = self._manifest_path(building_id, floor)
        if not p.exists():
            return None
        try:
            return FloorPlanManifest.model_validate_json(p.read_text("utf-8"))
        except Exception as e:
            logger.warning(f"[dwg_pipeline] Could not load manifest {p}: {e}")
            return None

    # ── Config ────────────────────────────────────────────────────────────────

    def _load_config(self, building_id: str) -> BuildingConfig:
        yaml_path = resolve_building_file(building_id, "building.yaml", self._input_dir)
        if yaml_path is not None:
            try:
                return BuildingConfig.from_yaml(yaml_path)
            except Exception as e:
                logger.warning(f"[dwg_pipeline] Could not load {yaml_path}: {e}")
        # Phase 4 — consult the BuildingRegistry so PDF slugs (e.g. "abacws")
        # that are declared as aliases by a logical building (e.g. "bldg1")
        # return the logical config rather than a stub.  Lazy import to keep
        # this module loadable in isolation.
        try:
            from orchestrator.services.building_registry import get_building_registry

            cfg = get_building_registry().get(building_id)
            if cfg is not None:
                return cfg
        except Exception:
            pass
        # No building.yaml and no registry entry: describe THIS building
        # generically rather than handing back another building's identity.
        return default_config(building_id)

    # ── Step 3: DWG → DXF conversion ─────────────────────────────────────────

    def _convert_to_dxf(self, dwg_path: Path) -> Tuple[Optional[Path], List[str]]:
        """Run dwg2dxf (libredwg-utils) to produce a DXF file in /tmp/."""
        warnings: List[str] = []
        dxf_path = Path(tempfile.gettempdir()) / f"{dwg_path.stem}_{_sha256_file(dwg_path)[:8]}.dxf"

        if dxf_path.exists():
            logger.debug(f"[dwg_pipeline] Using cached DXF: {dxf_path}")
            return dxf_path, warnings

        try:
            result = subprocess.run(
                ["dwg2dxf", str(dwg_path), "-o", str(dxf_path)],
                capture_output=True,
                text=True,
                timeout=120,
            )
            if result.returncode != 0:
                err = result.stderr.strip() or result.stdout.strip()
                warnings.append(f"dwg2dxf conversion failed for {dwg_path.name}: {err}")
                logger.error(f"[dwg_pipeline] dwg2dxf failed: {err}")
                return None, warnings
            if not dxf_path.exists():
                warnings.append(f"dwg2dxf produced no output for {dwg_path.name}")
                return None, warnings
            logger.info(
                f"[dwg_pipeline] Converted {dwg_path.name} → {dxf_path.name} "
                f"({dxf_path.stat().st_size // 1024} KB)"
            )
            return dxf_path, warnings
        except FileNotFoundError:
            warnings.append("dwg2dxf not found — install libredwg-utils in the Docker image")
            return None, warnings
        except subprocess.TimeoutExpired:
            warnings.append(f"dwg2dxf timed out converting {dwg_path.name}")
            return None, warnings
        except Exception as e:
            warnings.append(f"DWG conversion error: {e}")
            return None, warnings

    # ── Steps 4–6: parse DXF, extract geometry, normalise ────────────────────

    def _parse_dxf(
        self,
        dxf_path: Path,
        building_id: str,
        floor: int,
        cfg: BuildingConfig,
        dwg_sha: str,
    ) -> Tuple[List[Space], List[Block], Dict[str, str], str, Dict[str, float], List[str]]:
        """
        Parse DXF file using ezdxf + shapely.

        Returns: (spaces, blocks, layer_role_map, units_str, bounding_box, warnings)
        """
        warnings: List[str] = []
        spaces: List[Space] = []
        blocks: List[Block] = []

        try:
            import ezdxf
            from shapely.geometry import Point, Polygon
        except ImportError as e:
            warnings.append(f"Missing dependency: {e} — install ezdxf and shapely")
            return spaces, blocks, {}, "m", {}, warnings

        try:
            doc = ezdxf.readfile(str(dxf_path))
        except Exception as e:
            warnings.append(f"ezdxf could not read {dxf_path.name}: {e}")
            return spaces, blocks, {}, "m", {}, warnings

        msp = doc.modelspace()

        # Determine unit scale
        insunits = doc.header.get("$INSUNITS", 6)
        scale_to_m = _UNIT_TO_M.get(insunits, 1.0)
        units_str = {1: "in", 2: "ft", 4: "mm", 5: "cm", 6: "m", 7: "km"}.get(insunits, "m")

        # Classify layers
        layer_role_map = self._classify_layers(doc, cfg)

        # Extract room polygons
        polygons_raw, poly_warnings = self._extract_polygons(msp, layer_role_map, cfg, scale_to_m)
        warnings.extend(poly_warnings)

        # Extract text/label entities
        labels = self._extract_labels(msp)

        # Extract INSERT blocks (doors, sensors, etc.)
        raw_blocks, block_world_coords = self._extract_insert_blocks(msp, layer_role_map)

        if not polygons_raw:
            warnings.append(
                f"No room polygons found in {dxf_path.name} — "
                "check layer names against AIA/NCS conventions or add layer_map in building.yaml"
            )
            # A drawing with no room outlines can still NAME its rooms, and on a
            # real export that is the normal case rather than a broken one: the
            # room numbers sit on the area-identification layer while the only
            # closed polylines are furniture and the floor outline. Returning
            # here threw those names away and left the floor with nothing at all
            # (CAVEAT-206). Normalise against the labels' own extent, which is
            # the only extent the drawing offers once the polygons are gone.
            zone_re = cfg.zone_id_regex()
            named = [(txt, lx, ly) for txt, lx, ly in labels if zone_re.search(txt)]
            if named:
                lxs = [p[1] for p in named]
                lys = [p[2] for p in named]
                lmin_x, lmin_y = min(lxs), min(lys)
                lw = (max(lxs) - lmin_x) or 1.0
                lh = (max(lys) - lmin_y) or 1.0
                spaces = self._spaces_from_unclaimed_labels(
                    labels, set(), building_id, floor, zone_re, lmin_x, lmin_y, lw, lh
                )
                bounding_box = {
                    "min_x": lmin_x,
                    "min_y": lmin_y,
                    "max_x": max(lxs),
                    "max_y": max(lys),
                    "width_m": lw * scale_to_m,
                    "height_m": lh * scale_to_m,
                }
                logger.info(
                    f"[dwg_pipeline] floor {floor}: no room polygons, but {len(spaces)} named "
                    f"room(s) recovered from labels"
                )
                return spaces, blocks, layer_role_map, units_str, bounding_box, warnings
            return spaces, blocks, layer_role_map, units_str, {}, warnings

        # Compute global bounding box for normalisation
        all_x = [pt[0] for poly, _ in polygons_raw for pt in poly]
        all_y = [pt[1] for poly, _ in polygons_raw for pt in poly]
        min_x, max_x = min(all_x), max(all_x)
        min_y, max_y = min(all_y), max(all_y)
        width = max_x - min_x or 1.0
        height = max_y - min_y or 1.0

        bounding_box = {
            "min_x": min_x,
            "min_y": min_y,
            "max_x": max_x,
            "max_y": max_y,
            "width_m": width * scale_to_m,
            "height_m": height * scale_to_m,
        }

        # Associate labels → polygons (point-in-polygon)
        zone_re = cfg.zone_id_regex()
        spaces = self._associate_labels(
            polygons_raw,
            labels,
            building_id,
            floor,
            zone_re,
            scale_to_m,
            min_x,
            min_y,
            width,
            height,
            cfg,
        )

        # Compute adjacency
        self._compute_adjacency(spaces, polygons_raw, scale_to_m)

        # Normalise block positions and assign to spaces
        for bk_name, bk_type, wx, wy, layer, attribs in raw_blocks:
            nx = (wx - min_x) / width
            ny = 1.0 - (wy - min_y) / height
            pos = NormalisedPoint(x=max(0.0, min(nx, 1.0)), y=max(0.0, min(ny, 1.0)))

            # Find which space this block falls in
            space_id = None
            pt = Point(wx, wy)
            for space, (poly_pts, _) in zip(spaces, polygons_raw):
                if len(poly_pts) >= 3:
                    try:
                        if pt.within(Polygon(poly_pts)):
                            space_id = space.id
                            break
                    except Exception:
                        pass

            blocks.append(
                Block(
                    type=bk_type,  # type: ignore[arg-type]
                    block_name=bk_name,
                    position=pos,
                    layer=layer,
                    attributes=attribs,
                    space_id=space_id,
                )
            )

        logger.info(
            f"[dwg_pipeline] Parsed {dxf_path.name}: "
            f"{len(spaces)} spaces, {len(blocks)} blocks, units={units_str}"
        )
        return spaces, blocks, layer_role_map, units_str, bounding_box, warnings

    # ── DW3: Sensor TAG → ontology linking ───────────────────────────────────

    async def _link_sensor_blocks(
        self,
        blocks: List[Block],
        spaces: List[Space],
        building_id: str,
    ) -> List[str]:
        """
        Match DWG block attribute values (TAG, SENSOR_ID, UUID, BACNET_ID) against
        GraphDB to find ontology IRIs and time-series UUIDs.

        Updates in place:
          block.attributes['ontology_iri'] — IRI of matched sensor entity
          space.sensor_uuids              — UUID appended for every matched sensor inside
        """
        warnings: List[str] = []

        # Collect candidate sensor identifier values from all blocks
        _ATTR_KEYS = {"TAG", "SENSOR_ID", "UUID", "DEVICE_ID", "BACNET_ID", "ID", "NAME"}
        candidates: Dict[str, Block] = {}  # value → first block with that value
        for block in blocks:
            if block.type not in ("sensor", "hvac_diffuser", "fire_alarm", "unknown"):
                continue
            for key, val in block.attributes.items():
                if key.upper() in _ATTR_KEYS and val:
                    candidates[val] = block

        if not candidates:
            return warnings

        values = list(candidates.keys())[:40]  # cap to avoid huge query
        vals_sparql = " ".join(f'"{v}"' for v in values)

        sparql = f"""
PREFIX rdf:    <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
PREFIX rdfs:   <http://www.w3.org/2000/01/rdf-schema#>
PREFIX brick:  <https://brickschema.org/schema/Brick#>
PREFIX bacnet: <http://data.ashrae.org/bacnet/#>

SELECT ?entity ?label ?uuid WHERE {{
    ?entity a ?type .
    OPTIONAL {{ ?entity rdfs:label ?label }}
    OPTIONAL {{
        ?entity brick:hasExternalReference ?ref .
        ?ref brick:hasTimeseriesId ?uuid .
    }}
    FILTER(
        (bound(?label) && ?label IN ({vals_sparql}))
        || (bound(?uuid)  && ?uuid  IN ({vals_sparql}))
    )
}} LIMIT 100
"""
        try:
            import httpx

            from shared.config import settings as _settings

            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(
                    f"{self._graphdb_url}/repositories/{_settings.GRAPHDB_REPOSITORY}",
                    headers={
                        "Content-Type": "application/sparql-query",
                        "Accept": "application/sparql-results+json",
                    },
                    content=sparql,
                )
            if resp.status_code != 200:
                warnings.append(f"DW3 sensor linking: GraphDB returned {resp.status_code}")
                return warnings

            bindings = resp.json().get("results", {}).get("bindings", [])
            iri_map: Dict[str, str] = {}  # value → IRI
            uuid_map: Dict[str, str] = {}  # value → timeseries UUID

            for b in bindings:
                iri = b.get("entity", {}).get("value", "")
                label = b.get("label", {}).get("value", "")
                uuid = b.get("uuid", {}).get("value", "")
                if label and iri:
                    iri_map[label] = iri
                if uuid and iri:
                    iri_map[uuid] = iri
                    uuid_map[uuid] = uuid

            # Build space lookup: block.space_id → Space
            space_by_id: Dict[str, Space] = {s.id: s for s in spaces}

            linked = 0
            for val, block in candidates.items():
                iri = iri_map.get(val)
                if iri:
                    block.attributes["ontology_iri"] = iri
                    uuid = uuid_map.get(val, "")
                    if uuid and block.space_id and block.space_id in space_by_id:
                        sp = space_by_id[block.space_id]
                        if uuid not in sp.sensor_uuids:
                            sp.sensor_uuids.append(uuid)
                    linked += 1

            if linked:
                logger.info(
                    f"[dwg_pipeline] DW3: linked {linked}/{len(candidates)} sensor blocks "
                    f"for building={building_id}"
                )
            else:
                logger.debug(
                    f"[dwg_pipeline] DW3: no ontology matches for {len(candidates)} sensor "
                    f"attribute values — check GraphDB data"
                )
        except Exception as e:
            warnings.append(f"DW3 sensor linking failed: {e}")
        return warnings

    # ── Layer classification ──────────────────────────────────────────────────

    def _classify_layers(self, doc: Any, cfg: BuildingConfig) -> Dict[str, str]:
        """Map layer names → semantic roles using AIA/NCS defaults + building overrides."""
        layer_map = cfg.merged_layer_map()
        result: Dict[str, str] = {}
        for layer in doc.layers:
            name = layer.dxf.name
            matched_role = "other"
            for pattern, role in layer_map.items():
                if re.search(pattern, name):
                    matched_role = role
                    break
            result[name] = matched_role
        return result

    # ── Polygon extraction ────────────────────────────────────────────────────

    def _extract_polygons(
        self,
        msp: Any,
        layer_role_map: Dict[str, str],
        cfg: BuildingConfig,
        scale_to_m: float,
    ) -> Tuple[List[Tuple[List[Tuple[float, float]], str]], List[str]]:
        """
        Extract closed polylines that represent room boundaries.

        Returns list of (world_coords, layer_name) pairs.
        """
        warnings: List[str] = []
        room_boundary_layers = {
            name for name, role in layer_role_map.items() if role == "room_boundary"
        }

        candidates = []
        all_closed = []

        for pts, layer in _iter_closed_rings(msp):

            try:
                from shapely.geometry import Polygon as ShapelyPoly

                poly = ShapelyPoly(pts)
                if not poly.is_valid:
                    poly = poly.buffer(0)
                area_world = poly.area
                area_m2 = area_world * (scale_to_m**2)
            except Exception:
                continue

            all_closed.append((pts, layer, area_m2))
            if layer in room_boundary_layers:
                candidates.append((pts, layer, area_m2))

        # Fallback: no layer was recognised as a room boundary. Use every closed
        # polyline EXCEPT those positively identified as something else. Sweeping
        # in everything made furniture and gross-area outlines into "rooms" — on
        # a real drawing that is dozens of spaces per floor which can never match
        # anything in the ontology, and which crowd out the rooms that can.
        # Unclassified layers are still admitted: not knowing a layer is a reason
        # to consider it, whereas knowing it is furniture is a reason not to.
        if not candidates and all_closed:
            kept = [
                (pts, layer, area)
                for pts, layer, area in all_closed
                if layer_role_map.get(layer) not in _NON_ROOM_ROLES
            ]
            dropped = len(all_closed) - len(kept)
            warnings.append(
                "No room_boundary layers matched — using closed polylines as fallback"
                + (
                    f" ({dropped} excluded as furniture/annotation/area outlines)"
                    if dropped
                    else ""
                )
            )
            candidates = kept

        # Filter by area bounds
        result = []
        for pts, layer, area_m2 in candidates:
            if cfg.min_room_area_m2 <= area_m2 <= cfg.max_room_area_m2:
                result.append((pts, layer))
            else:
                logger.debug(
                    f"[dwg_pipeline] Skipping polyline on {layer}: "
                    f"area={area_m2:.1f}m² outside [{cfg.min_room_area_m2}, {cfg.max_room_area_m2}]"
                )

        logger.debug(
            f"[dwg_pipeline] {len(result)} room polygons after area filter "
            f"(from {len(candidates)} candidates)"
        )
        return result, warnings

    # ── Label extraction ──────────────────────────────────────────────────────

    def _extract_labels(self, msp: Any) -> List[Tuple[str, float, float]]:
        """Return list of (text, world_x, world_y) from TEXT and MTEXT entities."""
        labels = []
        for entity in msp.query("TEXT MTEXT"):
            try:
                if entity.dxftype() == "TEXT":
                    txt = entity.dxf.text.strip()
                    ins = entity.dxf.insert
                    wx, wy = ins.x, ins.y
                else:
                    txt = _strip_mtext_codes(entity.plain_mtext().strip())
                    ins = entity.dxf.insert
                    wx, wy = ins.x, ins.y
                if txt:
                    labels.append((txt, wx, wy))
            except Exception:
                pass
        return labels

    # ── INSERT block extraction ───────────────────────────────────────────────

    def _extract_insert_blocks(
        self,
        msp: Any,
        layer_role_map: Dict[str, str],
    ) -> Tuple[List[Tuple[str, str, float, float, str, Dict[str, str]]], List[Any]]:
        """Extract INSERT entities (doors, sensors, equipment) with attributes."""
        results = []
        world_coords = []
        for entity in msp.query("INSERT"):
            try:
                block_name = entity.dxf.name
                ins = entity.dxf.insert
                wx, wy = ins.x, ins.y
                layer = entity.dxf.layer

                attribs: Dict[str, str] = {}
                if entity.has_attribs:
                    for attrib in entity.attribs:
                        tag = attrib.dxf.tag.strip().upper()
                        val = attrib.dxf.text.strip()
                        if tag and val:
                            attribs[tag] = val

                btype = _classify_block_type(block_name)
                results.append((block_name, btype, wx, wy, layer, attribs))
                world_coords.append((wx, wy))
            except Exception:
                pass
        return results, world_coords

    # ── Label → polygon association ───────────────────────────────────────────

    def _associate_labels(
        self,
        polygons_raw: List[Tuple[List[Tuple[float, float]], str]],
        labels: List[Tuple[str, float, float]],
        building_id: str,
        floor: int,
        zone_re: Any,
        scale_to_m: float,
        min_x: float,
        min_y: float,
        width: float,
        height: float,
        cfg: BuildingConfig,
    ) -> List[Space]:
        """
        For each polygon, find labels inside it via point-in-polygon.
        Extract zone_id from the label text if it matches the building's zone pattern.
        Falls back to positional ID if no matching label is found.

        Labels that no polygon contains become POINT SPACES (CAVEAT-206). Not
        every drawing outlines its rooms: a real architectural export may name
        all 51 rooms as text on the area-identification layer while its only
        closed polylines are the gross-internal-area outline, furniture and
        access routes. Dropping those labels lost the rooms entirely — the very
        rooms the ontology knows by name — and left the manifest holding
        furniture polygons under positional ids instead. A space with an
        identity and a position, honestly carrying no area, is worth far more
        than that: it answers "where is 5.26", links to the ontology, and joins
        to its sensors. Area stays None rather than guessed, so nothing
        downstream can mistake it for measured geometry.
        """
        try:
            from shapely.geometry import Point
            from shapely.geometry import Polygon as ShapelyPoly
        except ImportError:
            return []

        spaces: List[Space] = []
        #: labels a polygon claimed, so the fallback below adds only the rest
        consumed: set = set()

        for i, (pts, layer) in enumerate(polygons_raw):
            try:
                poly = ShapelyPoly(pts)
                if not poly.is_valid:
                    poly = poly.buffer(0)

                area_world = poly.area
                area_m2 = area_world * (scale_to_m**2)

                # Perimeter in metres
                perimeter_m = poly.length * scale_to_m

                # Centroid in normalised coords
                cx_world = poly.centroid.x
                cy_world = poly.centroid.y
                nx = (cx_world - min_x) / width
                ny = 1.0 - (cy_world - min_y) / height

                # Polygon vertices normalised
                norm_poly = [
                    NormalisedPoint(
                        x=max(0.0, min((p[0] - min_x) / width, 1.0)),
                        y=max(0.0, min(1.0 - (p[1] - min_y) / height, 1.0)),
                    )
                    for p in pts
                ]

                # Find labels inside polygon
                zone_id: Optional[str] = None
                label_text: Optional[str] = None
                inside = [(txt, lx, ly) for txt, lx, ly in labels if Point(lx, ly).within(poly)]
                numbered = [p for p in inside if zone_re.search(p[0])]

                if len(numbered) > 1:
                    # One outline, several room numbers: the drawing says these
                    # rooms are in here, and says nothing about where the line
                    # between them falls. Naming it after the first number found
                    # would hand that room the OTHERS' floor space -- on a real
                    # floor, a boundary drawn across two 11 m2 rooms reported one
                    # of them as 22.8 m2, a plausible number that is simply wrong,
                    # and the kind of answer this system exists not to give.
                    # The outline is kept as an unnamed space so the floor total
                    # stays right, and its room numbers are left unconsumed so
                    # each becomes a point space below: known to exist, known
                    # where, honestly carrying no area.
                    logger.info(
                        f"[dwg_pipeline] floor {floor}: one boundary encloses "
                        f"{len(numbered)} room numbers "
                        f"({', '.join(sorted(zone_re.search(p[0]).group(0).strip() for p in numbered))})"
                        " - area left unattributed; split the outline per room to recover it"
                    )
                    for p in inside:
                        if p not in numbered:
                            consumed.add(p)
                else:
                    for txt, lx, ly in inside:
                        consumed.add((txt, lx, ly))
                        # Try to extract zone_id from text
                        m = zone_re.search(txt)
                        if m:
                            zone_id = m.group(0).strip()
                            label_text = txt
                            break
                        elif label_text is None:
                            label_text = txt  # keep first label inside

                if zone_id is None:
                    # Use first-found label text as label, generate positional ID
                    zone_id = f"{floor}Z{i+1:03d}"

                final_label = label_text or f"Zone {zone_id}"
                space_id = f"{building_id}.{zone_id}"
                space_type = _classify_space_type_from_label(final_label)

                spaces.append(
                    Space(
                        id=space_id,
                        zone_id=zone_id,
                        label=final_label,
                        type=space_type,
                        centroid=NormalisedPoint(
                            x=max(0.0, min(nx, 1.0)),
                            y=max(0.0, min(ny, 1.0)),
                        ),
                        polygon=norm_poly,
                        source="dwg",
                        confidence=0.98,
                        area_m2=round(area_m2, 2),
                        perimeter_m=round(perimeter_m, 2),
                        layer=layer,
                    )
                )
            except Exception as e:
                logger.debug(f"[dwg_pipeline] Skipping polygon {i}: {e}")

        spaces.extend(
            self._spaces_from_unclaimed_labels(
                labels, consumed, building_id, floor, zone_re, min_x, min_y, width, height
            )
        )
        return spaces

    def _spaces_from_unclaimed_labels(
        self,
        labels: List[Tuple[str, float, float]],
        consumed: set,
        building_id: str,
        floor: int,
        zone_re: Any,
        min_x: float,
        min_y: float,
        width: float,
        height: float,
    ) -> List[Space]:
        """Rooms the drawing NAMES but does not outline (CAVEAT-206).

        Only labels that match the building's own ``zone_id_pattern`` qualify, so
        legend entries, dimension callouts and title-block text cannot become
        rooms. Each yields one space at the label's own position, with no
        polygon and ``area_m2`` left None: the drawing states where the room is
        and what it is called, and states nothing about its extent.
        """
        out: List[Space] = []
        seen: set = set()
        for txt, lx, ly in labels:
            if (txt, lx, ly) in consumed:
                continue
            m = zone_re.search(txt)
            if not m:
                continue
            zone_id = m.group(0).strip()
            if zone_id in seen:
                continue  # one space per room, however often the CAD repeats it
            seen.add(zone_id)
            out.append(
                Space(
                    id=f"{building_id}.{zone_id}",
                    zone_id=zone_id,
                    label=txt.strip() or f"Zone {zone_id}",
                    type=_classify_space_type_from_label(txt),
                    centroid=NormalisedPoint(
                        x=max(0.0, min((lx - min_x) / width, 1.0)),
                        y=max(0.0, min(1.0 - (ly - min_y) / height, 1.0)),
                    ),
                    polygon=None,
                    source="dwg",
                    # Lower than a polygon-backed space: the identity and place
                    # are read straight from the drawing, the extent is unknown.
                    confidence=0.9,
                    area_m2=None,
                    layer="",
                )
            )
        if out:
            logger.info(
                f"[dwg_pipeline] {len(out)} room label(s) had no enclosing polygon — "
                f"kept as point spaces with identity but no area (CAVEAT-206)"
            )
        return out

    # ── Adjacency computation ─────────────────────────────────────────────────

    def _compute_adjacency(
        self,
        spaces: List[Space],
        polygons_raw: List[Tuple[List[Tuple[float, float]], str]],
        scale_to_m: float,
        threshold_m: float = 0.6,
    ) -> None:
        """Populate space.adjacent_spaces for spaces whose polygons are within threshold_m.

        ``spaces`` and ``polygons_raw`` were once index-parallel, one space per
        polygon. They no longer are: a room the drawing names but does not
        outline becomes a point space with no polygon (CAVEAT-206), so indexing
        polygons_raw by space position walked off the end. Pad to the length of
        ``spaces`` with None, which the loops below already treat as "no
        geometry, no adjacency" — a point space genuinely has no measurable
        distance to anything.
        """
        try:
            from shapely.geometry import Polygon as ShapelyPoly
        except ImportError:
            return

        # Build shapely polygons, keyed by space index
        polys = []
        for pts, _ in polygons_raw:
            try:
                p = ShapelyPoly(pts)
                if not p.is_valid:
                    p = p.buffer(0)
                polys.append(p)
            except Exception:
                polys.append(None)
        # Spaces beyond the polygon list carry no geometry.
        polys.extend([None] * max(0, len(spaces) - len(polys)))

        threshold_world = threshold_m / scale_to_m

        for i, space_a in enumerate(spaces):
            if polys[i] is None:
                continue
            for j, space_b in enumerate(spaces):
                if i >= j or polys[j] is None:
                    continue
                try:
                    dist = polys[i].distance(polys[j])
                    if dist < threshold_world:
                        space_a.adjacent_spaces.append(space_b.zone_id)
                        space_b.adjacent_spaces.append(space_a.zone_id)
                except Exception:
                    pass


# ── Module-level singleton ─────────────────────────────────────────────────────
_pipeline: Optional[DWGPipeline] = None


def get_dwg_pipeline() -> DWGPipeline:
    global _pipeline
    if _pipeline is None:
        _pipeline = DWGPipeline()
    return _pipeline


#: How large an endpoint gap may be, as a share of the ring's own perimeter,
#: before the polyline is read as a genuinely OPEN path rather than a boundary
#: someone meant to close. Relative rather than absolute because a drawing may be
#: in millimetres or metres, and a 15 mm slip means something different on a 14 m
#: room than on a 140 mm one. The two failure modes sit orders of magnitude apart:
#: real drafting closures measured here come in at 0.0025%-0.10%, while an open
#: wall run has a gap comparable to its own length -- tens of percent at least.
_RING_CLOSURE_TOLERANCE = 0.01


def _iter_closed_rings(msp: Any) -> Iterator[Tuple[List[Tuple[float, float]], str]]:
    """Yield (points, layer) for every polyline that bounds an area.

    Two things this deliberately does NOT do. It does not trust the ``closed``
    flag alone: AutoCAD sets that flag only when the ring is finished with the
    Close option, so a boundary drawn by snapping the last vertex back onto the
    first -- which is what a person naturally does, and which is geometrically a
    closed ring -- arrives flagged open. Requiring the flag silently discarded
    such rooms, and because the fallback then kept them as point spaces with no
    area, the loss looked like missing source data rather than a bug here.

    Nor does it accept any old open path: a polyline qualifies only if its ends
    already meet within _RING_CLOSURE_TOLERANCE of its perimeter, so wall runs,
    leader lines and section marks cannot become rooms.

    Heavy POLYLINE entities are read alongside LWPOLYLINE because which of the
    two a DXF carries is a function of the exporting tool, not of what was drawn;
    querying only the modern form made the result depend on the user's CAD build.
    Meshes and polyface entities are excluded -- they are 3D geometry, not plan
    boundaries.
    """
    for entity in msp.query("LWPOLYLINE"):
        try:
            pts = [(p[0], p[1]) for p in entity.get_points("xy")]
            if _is_ring(pts, bool(entity.closed)):
                yield pts, entity.dxf.layer
        except Exception:  # a malformed entity must not abort the whole floor
            continue

    for entity in msp.query("POLYLINE"):
        try:
            if not getattr(entity, "is_2d_polyline", False):
                continue
            pts = [(v.dxf.location[0], v.dxf.location[1]) for v in entity.vertices]
            if _is_ring(pts, bool(entity.is_closed)):
                yield pts, entity.dxf.layer
        except Exception:
            continue


def _is_ring(pts: List[Tuple[float, float]], closed_flag: bool) -> bool:
    """True when these points bound an area, by flag or by meeting ends."""
    if len(pts) < 3:
        return False
    if closed_flag:
        return True
    perimeter = sum(
        math.dist(pts[i], pts[i + 1]) for i in range(len(pts) - 1)  # type: ignore[arg-type]
    )
    if perimeter <= 0:
        return False
    gap = math.dist(pts[0], pts[-1])  # type: ignore[arg-type]
    return gap <= _RING_CLOSURE_TOLERANCE * perimeter
