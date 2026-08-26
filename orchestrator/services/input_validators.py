"""
T37 — Per-building config file validators.

Validates all per-building config files at swap/startup time so bad configs
produce actionable error messages rather than silent misbehaviour.

Validation philosophy:
  - REQUIRED files (building.yaml, *.ttl): hard-fail → swap/startup aborts.
  - OPTIONAL files (feeds, recipes, rules, channels, benchmarks, concepts, docs):
    warn + skip → orchestrator still boots, but the feature is disabled.
  - Each validator returns (ok: bool, issues: List[str]) so callers can
    aggregate and report all problems at once.

Usage:
    from orchestrator.services.input_validators import validate_building_input
    ok, report = validate_building_input("bldg2", Path("input"))
"""

from __future__ import annotations

import csv
import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml

logger = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────

#: Fallback only. The authority on which feed types are dispatchable is the
#: registry's own adapter map — this list drifted behind it and rejected a
#: correctly-declared timetable feed that the registry ingests happily.
_FEED_TYPES_FALLBACK = {"csv_drop", "rest_poll", "events"}
#: A telemetry feed becomes a Brick point with rows in a database, so it must say
#: which class and which store. An institutional source produces EVENTS, not a
#: point: it has neither, and demanding them reported a working feed as broken.
_FEED_REQUIRED_KEYS = {"id", "type", "brick_class", "storage"}
_INSTITUTIONAL_REQUIRED_KEYS = {"id", "type", "path"}
_RECIPE_KINDS = {"threshold", "range", "aggregate", "correlate", "trend", "estimate", "benchmark"}
_RULE_OPS = {">", "<", ">=", "<=", "==", "!="}
_CHANNEL_TYPES = {"log", "webhook", "smtp"}
_BENCHMARKS_REQUIRED_COLS = {"metric", "p25", "p50", "p75", "unit", "source"}
_DOCS_ALLOWED_EXTENSIONS = {".md", ".txt", ".pdf"}
_DATASOURCE_KINDS = {"timeseries", "text_reports", "events"}  # events store: V5-T07/T31
_DATASOURCE_REQUIRED_KEYS = {"id", "label", "modality", "provenance_system"}
_HEX_COLOR = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")


# ── Individual file validators ────────────────────────────────────────────────


def _known_feed_types() -> Tuple[set, set]:
    """(every dispatchable feed type, the institutional subset).

    Read from the feed registry rather than restated here: a second copy of this
    list is what let feeds.yaml declare a working `timetable` feed and have the
    swap-time validator call it an unknown type with two missing keys.
    """
    try:
        from orchestrator.services.feeds.registry import (  # local: keeps validators light
            _ADAPTER_CLASSES,
            _INSTITUTIONAL_KINDS,
        )

        return set(_ADAPTER_CLASSES), set(_INSTITUTIONAL_KINDS)
    except Exception as exc:  # pragma: no cover — registry import is not required to validate
        logger.debug(f"[input_validator] feed registry unavailable ({exc}); using fallback types")
        return set(_FEED_TYPES_FALLBACK), set()


def validate_feeds_yaml(path: Path) -> Tuple[bool, List[str]]:
    """Validate feeds.yaml — each feed must have required keys and a known type."""
    issues: List[str] = []
    if not path.exists():
        return True, []  # optional file — absence is fine

    try:
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    except yaml.YAMLError as exc:
        return False, [f"feeds.yaml: YAML parse error — {exc}"]

    feeds = data.get("feeds", [])
    if not isinstance(feeds, list):
        return False, ["feeds.yaml: 'feeds' key must be a list"]

    known_types, institutional = _known_feed_types()

    seen_ids: set = set()
    for i, feed in enumerate(feeds):
        if not isinstance(feed, dict):
            issues.append(f"feeds.yaml[{i}]: entry must be a dict")
            continue
        fid = feed.get("id", f"<entry {i}>")
        if fid in seen_ids:
            issues.append(f"feeds.yaml: duplicate feed id '{fid}'")
        seen_ids.add(fid)
        ftype = feed.get("type")
        required = _INSTITUTIONAL_REQUIRED_KEYS if ftype in institutional else _FEED_REQUIRED_KEYS
        missing = required - set(feed.keys())
        if missing:
            issues.append(f"feeds.yaml[{fid}]: missing required keys: {sorted(missing)}")
        if ftype not in known_types:
            issues.append(
                f"feeds.yaml[{fid}]: type='{ftype}' not in {sorted(known_types)}"
            )
        field_map = feed.get("field_map", {})
        if field_map and "value" not in field_map.values():
            issues.append(f"feeds.yaml[{fid}]: field_map must map at least one column to 'value'")

    return len(issues) == 0, issues


def validate_recipes_yaml(path: Path) -> Tuple[bool, List[str]]:
    """Validate recipes.yaml — each recipe must have a known kind and a params dict."""
    issues: List[str] = []
    if not path.exists():
        return True, []

    try:
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    except yaml.YAMLError as exc:
        return False, [f"recipes.yaml: YAML parse error — {exc}"]

    recipes = data.get("recipes", data)
    if not isinstance(recipes, dict):
        return False, ["recipes.yaml: top-level must be a dict of recipe_id → definition"]

    for rid, recipe in recipes.items():
        if not isinstance(recipe, dict):
            issues.append(f"recipes.yaml[{rid}]: entry must be a dict")
            continue
        kind = recipe.get("kind")
        if kind not in _RECIPE_KINDS:
            issues.append(f"recipes.yaml[{rid}]: kind='{kind}' not in {_RECIPE_KINDS}")
        if "params" not in recipe:
            issues.append(f"recipes.yaml[{rid}]: missing 'params' dict")
        elif not isinstance(recipe["params"], dict):
            issues.append(f"recipes.yaml[{rid}]: 'params' must be a dict")

    return len(issues) == 0, issues


def validate_rules_yaml(path: Path) -> Tuple[bool, List[str]]:
    """Validate rules.yaml — each rule must have valid trigger operator and action type."""
    issues: List[str] = []
    if not path.exists():
        return True, []

    try:
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    except yaml.YAMLError as exc:
        return False, [f"rules.yaml: YAML parse error — {exc}"]

    rules = data.get("rules", [])
    if not isinstance(rules, list):
        return False, ["rules.yaml: 'rules' key must be a list"]

    seen_ids: set = set()
    for i, rule in enumerate(rules):
        if not isinstance(rule, dict):
            issues.append(f"rules.yaml[{i}]: entry must be a dict")
            continue
        rid = rule.get("id", f"<entry {i}>")
        if rid in seen_ids:
            issues.append(f"rules.yaml: duplicate rule id '{rid}'")
        seen_ids.add(rid)

        trigger = rule.get("trigger", {})
        if not isinstance(trigger, dict):
            issues.append(f"rules.yaml[{rid}]: 'trigger' must be a dict")
        else:
            if not trigger.get("concept") and not trigger.get("sensor_uuid"):
                issues.append(f"rules.yaml[{rid}]: trigger must have 'concept' or 'sensor_uuid'")
            op = trigger.get("op")
            if op not in _RULE_OPS:
                issues.append(f"rules.yaml[{rid}]: trigger.op='{op}' not in {_RULE_OPS}")
            if trigger.get("threshold") is None:
                issues.append(f"rules.yaml[{rid}]: trigger.threshold is required")

        action = rule.get("action", {})
        if not isinstance(action, dict):
            issues.append(f"rules.yaml[{rid}]: 'action' must be a dict")
        elif action.get("type") not in {"notify"}:
            issues.append(
                f"rules.yaml[{rid}]: action.type='{action.get('type')}' — "
                "only 'notify' is supported in this deployment"
            )

    return len(issues) == 0, issues


def validate_channels_yaml(path: Path) -> Tuple[bool, List[str]]:
    """Validate channels.yaml — each channel must have a known type."""
    issues: List[str] = []
    if not path.exists():
        return True, []

    try:
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    except yaml.YAMLError as exc:
        return False, [f"channels.yaml: YAML parse error — {exc}"]

    channels = data.get("channels", [])
    if not isinstance(channels, list):
        return False, ["channels.yaml: 'channels' key must be a list"]

    for i, ch in enumerate(channels):
        if not isinstance(ch, dict):
            issues.append(f"channels.yaml[{i}]: entry must be a dict")
            continue
        if ch.get("type") not in _CHANNEL_TYPES:
            issues.append(f"channels.yaml[{i}]: type='{ch.get('type')}' not in {_CHANNEL_TYPES}")

    return len(issues) == 0, issues


def validate_benchmarks_csv(path: Path) -> Tuple[bool, List[str]]:
    """Validate benchmarks.csv — required columns must be present in header."""
    if not path.exists():
        return True, []

    try:
        with open(path, newline="", encoding="utf-8") as f:
            reader = csv.reader(f)
            header = next(reader, None)
        if header is None:
            return False, ["benchmarks.csv: file is empty"]
        cols = {c.strip().lower() for c in header}
        missing = _BENCHMARKS_REQUIRED_COLS - cols
        if missing:
            return False, [f"benchmarks.csv: missing required columns: {sorted(missing)}"]
        return True, []
    except Exception as exc:
        return False, [f"benchmarks.csv: read error — {exc}"]


def validate_concepts_ttl(path: Path) -> Tuple[bool, List[str]]:
    """Validate concepts.ttl — must parse as Turtle and contain >=1 hbco:Concept."""
    if not path.exists():
        return True, []

    try:
        import rdflib

        g = rdflib.Graph()
        g.parse(str(path), format="turtle")
    except Exception as exc:
        return False, [f"concepts.ttl: Turtle parse error — {exc}"]

    # Optional check: warn if it claims to be a concepts overlay but has no hbco:Concept
    HBCO_CONCEPT = "http://ontosage.org/hbco#Concept"
    has_concept = any(str(o) == HBCO_CONCEPT for _, _, o in g.triples((None, None, None)))
    if not has_concept and len(g) > 0:
        # Triples exist but none declare hbco:Concept — likely a mistake
        return False, [
            "concepts.ttl: file has triples but no hbco:Concept instances "
            "(check @prefix and rdf:type declarations)"
        ]
    return True, []


def _known_ts_tables(input_root: Path) -> Optional[set]:
    """Table keys declared in database_registry.yaml, or None if not found.

    Returns None (rather than empty set) when the registry can't be read, so
    callers can skip the cross-check instead of failing every ts_table.
    """
    for candidate in (
        input_root / "database_registry.yaml",
        Path("input") / "database_registry.yaml",
    ):
        if candidate.is_file():
            try:
                with open(candidate, encoding="utf-8") as f:
                    data = yaml.safe_load(f) or {}
                dbs = data.get("databases", {})
                if isinstance(dbs, dict):
                    return set(dbs.keys())
            except Exception:
                return None
    return None


def validate_datasources_yaml(
    path: Path, input_root: Optional[Path] = None
) -> Tuple[bool, List[str]]:
    """Validate datasources.yaml — the toggleable synthetic data source manifest.

    Checks: unique ids, known kind, hex color, timeseries sources declare a
    ts_table that exists in database_registry.yaml, and timeseries points carry
    brick_class + location.
    """
    issues: List[str] = []
    if not path.exists():
        return True, []  # optional file

    try:
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    except yaml.YAMLError as exc:
        return False, [f"datasources.yaml: YAML parse error — {exc}"]

    sources = data.get("datasources", [])
    if not isinstance(sources, list):
        return False, ["datasources.yaml: 'datasources' key must be a list"]

    known_tables = _known_ts_tables(input_root or path.parent)
    seen_ids: set = set()
    for i, src in enumerate(sources):
        if not isinstance(src, dict):
            issues.append(f"datasources.yaml[{i}]: entry must be a dict")
            continue
        sid = src.get("id", f"<entry {i}>")
        if sid in seen_ids:
            issues.append(f"datasources.yaml: duplicate source id '{sid}'")
        seen_ids.add(sid)

        missing = _DATASOURCE_REQUIRED_KEYS - set(src.keys())
        if missing:
            issues.append(f"datasources.yaml[{sid}]: missing required keys: {sorted(missing)}")

        kind = src.get("kind", "timeseries")
        if kind not in _DATASOURCE_KINDS:
            issues.append(f"datasources.yaml[{sid}]: kind='{kind}' not in {_DATASOURCE_KINDS}")

        color = src.get("color", "#888888")
        if not _HEX_COLOR.match(str(color)):
            issues.append(f"datasources.yaml[{sid}]: color='{color}' is not a hex color")

        if kind == "timeseries":
            ts_table = src.get("ts_table")
            if not ts_table:
                issues.append(f"datasources.yaml[{sid}]: timeseries source requires 'ts_table'")
            elif known_tables is not None and ts_table not in known_tables:
                issues.append(
                    f"datasources.yaml[{sid}]: ts_table='{ts_table}' not declared in "
                    f"database_registry.yaml"
                )
            for j, pt in enumerate(src.get("points", []) or []):
                if not isinstance(pt, dict):
                    issues.append(f"datasources.yaml[{sid}].points[{j}]: must be a dict")
                    continue
                for key in ("local", "brick_class", "location"):
                    if not pt.get(key):
                        issues.append(f"datasources.yaml[{sid}].points[{j}]: missing '{key}'")

    return len(issues) == 0, issues


def validate_documents_dir(path: Path) -> Tuple[bool, List[str]]:
    """Validate documents/ — only allowed extensions; flag unknown file types."""
    if not path.exists():
        return True, []

    issues: List[str] = []
    for f in path.iterdir():
        if f.is_file() and f.suffix.lower() not in _DOCS_ALLOWED_EXTENSIONS:
            issues.append(
                f"documents/{f.name}: extension '{f.suffix}' not in "
                f"{_DOCS_ALLOWED_EXTENSIONS} — file will not be indexed"
            )
    return len(issues) == 0, issues


# ── Aggregate validator ───────────────────────────────────────────────────────


def _flat_building_matches(yaml_path: Path, building_id: str) -> bool:
    """True when a flat input/building.yaml belongs to `building_id`.

    Accepts it if building.yaml declares the same building_id, or declares none
    (single-building deployments often omit it). Returns False on read errors so
    a corrupt file does not silently pass validation against the wrong building.
    """
    try:
        import yaml as _yaml

        with open(yaml_path, "r", encoding="utf-8") as fh:
            data = _yaml.safe_load(fh) or {}
        declared = data.get("building_id")
        return declared is None or str(declared) == building_id
    except Exception:
        return False


_EVIDENCE_GATES = (
    "freshness",
    "completeness",
    "agreement",
    "spatial_adequacy",
    "calibration",
    "consequence",
)
_EVIDENCE_GATE_MODES = ("advisory", "enforcing")


def validate_evidence_policy_yaml(path: Path) -> Tuple[bool, List[str]]:
    """Validate the optional per-building evidence_policy.yaml overlay (V6-T04).

    The overlay narrows or widens the shipped defaults in ``config/evidence_policy.yaml``.
    The loader already ignores an unreadable overlay so a typo cannot take a building's
    evidence policy down at runtime -- but silently ignoring it is a poor way to LEARN that
    a threshold never took effect. Catching it here means the operator hears about it at
    swap time, when they can still fix it, rather than discovering weeks later that a gate
    they thought they had tuned was running on defaults.

    Absent is valid: like every other optional per-building file, absence means "use the
    defaults", not "misconfigured".
    """
    if not path.exists():
        return True, []
    issues: List[str] = []
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return False, [f"evidence_policy.yaml: YAML parse error - {exc}"]
    if data is None:
        return True, ["evidence_policy.yaml: empty; shipped defaults apply"]
    if not isinstance(data, dict):
        return False, ["evidence_policy.yaml: top level must be a mapping"]

    fresh = data.get("freshness")
    if fresh is not None:
        if not isinstance(fresh, dict):
            issues.append("evidence_policy.yaml: 'freshness' must be a mapping")
        else:
            per = fresh.get("by_modality") or {}
            if not isinstance(per, dict):
                issues.append("evidence_policy.yaml: freshness.by_modality must be a mapping")
            else:
                for modality, spec in per.items():
                    if not isinstance(spec, dict):
                        issues.append(
                            f"evidence_policy.yaml: freshness.{modality} must be a mapping"
                        )
                        continue
                    age = spec.get("max_age_minutes")
                    if age is not None and (not isinstance(age, (int, float)) or age <= 0):
                        issues.append(
                            f"evidence_policy.yaml: freshness.{modality}.max_age_minutes "
                            f"must be a positive number (got {age!r})"
                        )

    comp = data.get("completeness")
    if isinstance(comp, dict):
        cov = comp.get("min_window_coverage")
        if cov is not None and (not isinstance(cov, (int, float)) or not 0.0 <= cov <= 1.0):
            issues.append(
                "evidence_policy.yaml: completeness.min_window_coverage must be a fraction "
                f"between 0 and 1 (got {cov!r}) - 90 is not 0.90"
            )

    gates = data.get("gates")
    if gates is not None:
        if not isinstance(gates, dict):
            issues.append("evidence_policy.yaml: 'gates' must be a mapping")
        else:
            for gate, spec in gates.items():
                if gate not in _EVIDENCE_GATES:
                    issues.append(
                        f"evidence_policy.yaml: unknown gate '{gate}' "
                        f"(known: {', '.join(_EVIDENCE_GATES)}) - a typo here means the gate "
                        f"you meant to configure is still running on its default"
                    )
                    continue
                mode = (spec or {}).get("mode") if isinstance(spec, dict) else None
                if mode is not None and str(mode).lower() not in _EVIDENCE_GATE_MODES:
                    issues.append(
                        f"evidence_policy.yaml: gates.{gate}.mode must be one of "
                        f"{_EVIDENCE_GATE_MODES} (got {mode!r}); treated as advisory"
                    )

    return (not issues), issues


# ── measurand typing ────────────────────────────────────────────────────────
# A Brick Point measures ONE quantity. When an instance is asserted into two
# families at once — a volatile organic compound also typed as particulate
# matter, nitrogen dioxide also typed as carbon monoxide — a question about one
# gas can be answered with a reading of the other, against a different exposure
# limit. Both were live in bldg1 (CAVEAT-286). These families are disjoint by
# construction: nothing physically measures two of them through one Point.
_MEASURAND_FAMILIES: Dict[str, set] = {
    "particulate matter": {
        "Particulate_Matter_Sensor",
        "PM1_0_Level_Sensor",
        "PM2_5_Level_Sensor",
        "PM10_Level_Sensor",
    },
    "volatile organic compounds": {"TVOC_Level_Sensor", "TVOC_Sensor", "VOC_Level_Sensor"},
    "carbon monoxide": {"CO_Level_Sensor", "CO_Sensor"},
    "carbon dioxide": {"CO2_Level_Sensor", "CO2_Sensor"},
    "nitrogen dioxide": {"NO2_Level_Sensor", "NO2_Sensor"},
    "methane": {"Methane_Level_Sensor"},
    "ozone": {"Ozone_Level_Sensor"},
    "formaldehyde": {"Formaldehyde_Level_Sensor"},
}
_CLASS_TO_FAMILY = {c: fam for fam, cs in _MEASURAND_FAMILIES.items() for c in cs}
_INSTANCE_TYPES_RE = re.compile(r"^(\w+:[^\s]+)\s+(?:a|rdf:type)\s+([^;.]+)[;.]", re.M)


def _measurand_conflicts(text: str) -> List[Tuple[str, List[str]]]:
    """Instances in `text` that assert two mutually exclusive measurands."""
    out: List[Tuple[str, List[str]]] = []
    for subject, types in _INSTANCE_TYPES_RE.findall(text):
        fams = sorted(
            {
                _CLASS_TO_FAMILY[t]
                for t in re.findall(r"brick:(\w+)", types)
                if t in _CLASS_TO_FAMILY
            }
        )
        if len(fams) > 1:
            out.append((subject, fams))
    return out


def validate_measurand_typing(path: Path) -> Tuple[bool, List[str]]:
    """Check every *.ttl in a building directory for contradictory sensor typing."""
    if not path.is_dir():
        return True, []
    issues: List[str] = []
    for ttl in sorted(path.glob("*.ttl")):
        # Brick/vendored TBox files declare the class hierarchy itself; a class
        # legitimately sits under several parents there.
        if ttl.name.lower().startswith("brick"):
            continue
        try:
            text = ttl.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:  # pragma: no cover - unreadable file
            issues.append(f"{ttl.name}: unreadable ({exc})")
            continue
        for subject, fams in _measurand_conflicts(text):
            issues.append(
                f"{ttl.name}: {subject} is typed as both "
                + " and ".join(fams)
                + " — one Point measures one quantity, so a question about one "
                "would be answered with a reading of the other"
            )
    return (not issues), issues


def validate_building_input(building_id: str, input_root: Path) -> Tuple[bool, Dict[str, Any]]:
    """Run all optional-file validators for a building directory.

    Returns (all_ok, report) where report is a dict with per-file results.
    Does NOT validate building.yaml or TTL files (handled by swap_building.py).
    """
    bldg_dir = input_root / building_id
    report: Dict[str, Any] = {"building_id": building_id, "files": {}, "all_ok": True}

    if not bldg_dir.is_dir():
        # Flat layout (canonical): a single building's files live directly under
        # input_root (input/building.yaml, input/*.ttl, input/documents/ …). Accept
        # it when input/building.yaml declares this building_id.
        flat_yaml = input_root / "building.yaml"
        if flat_yaml.is_file() and _flat_building_matches(flat_yaml, building_id):
            bldg_dir = input_root
        else:
            report["all_ok"] = False
            report["files"]["<building dir>"] = {
                "ok": False,
                "issues": [
                    f"neither input/{building_id}/ (nested) nor input/building.yaml "
                    f"(flat, for {building_id}) found — create one with at least "
                    f"building.yaml and one *.ttl topology file "
                    f"(scaffold: python scripts/onboard_building.py --building-id "
                    f"{building_id} --scaffold)"
                ],
                "exists": False,
            }
            logger.warning(f"[input_validator] no input layout for building: {building_id}")
            return False, report

    checks: List[Tuple[str, Path, Any]] = [
        ("feeds.yaml", bldg_dir / "feeds.yaml", validate_feeds_yaml),
        ("recipes.yaml", bldg_dir / "recipes.yaml", validate_recipes_yaml),
        ("rules.yaml", bldg_dir / "rules.yaml", validate_rules_yaml),
        ("channels.yaml", bldg_dir / "channels.yaml", validate_channels_yaml),
        ("benchmarks.csv", bldg_dir / "benchmarks.csv", validate_benchmarks_csv),
        ("concepts.ttl", bldg_dir / "concepts.ttl", validate_concepts_ttl),
        ("documents/", bldg_dir / "documents", validate_documents_dir),
        (
            "datasources.yaml",
            bldg_dir / "datasources.yaml",
            lambda p: validate_datasources_yaml(p, input_root=input_root),
        ),
        ("evidence_policy.yaml", bldg_dir / "evidence_policy.yaml", validate_evidence_policy_yaml),
        ("sensor typing", bldg_dir, validate_measurand_typing),
    ]

    for name, path, validator in checks:
        ok, issues = validator(path)
        report["files"][name] = {"ok": ok, "issues": issues, "exists": path.exists()}
        if not ok:
            report["all_ok"] = False
            for issue in issues:
                logger.warning(f"[input_validator] {issue}")
        elif issues:
            for issue in issues:
                logger.debug(f"[input_validator] note: {issue}")

    return report["all_ok"], report


def format_validation_report(report: Dict[str, Any]) -> str:
    """Human-readable text version of a validate_building_input() report."""
    lines = [f"Validation report for building: {report['building_id']}"]
    lines.append("=" * 60)
    for fname, result in report["files"].items():
        status = "[OK]  " if result["ok"] else "[FAIL]"
        exists_note = "" if result["exists"] else " (absent - skipped)"
        lines.append(f"  {status}  {fname}{exists_note}")
        for issue in result.get("issues", []):
            lines.append(f"         -> {issue}")
    lines.append("=" * 60)
    lines.append("Overall: " + ("PASS" if report["all_ok"] else "FAIL — see issues above"))
    return "\n".join(lines)
