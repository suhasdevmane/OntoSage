"""TTL Validator — Phase 12B.

Validates that TTL files dropped under `input/<BUILDING_ID>/` are internally
consistent with the building's declared identity in `building.yaml`.

OntoSage v1 is single-building-at-a-time: one TTL prefix declaration must match
the one ontology_namespace in building.yaml.  When they diverge, SPARQL queries
silently return zero rows because the generated query targets a namespace no
triple actually uses.  This validator surfaces that mismatch loudly at startup
instead of leaving the operator to debug empty result sets.

Severity model
--------------
Two tiers, mirroring the user-approved 12B-3 design:

* HARD_FAIL — orchestrator startup MUST abort:
    - TTL fails to parse (syntax error)
    - TTL declares no `bldg:` (or building-prefix) namespace at all
    - TTL `bldg:` namespace differs from `building.yaml` ontology_namespace

* WARN — orchestrator continues but logs a clear warning:
    - SHACL conformance issues against the Brick reference shapes
      (only checked when `brickschema` + `pyshacl` are installed)
    - TTL declares the right namespace but contains zero triples in it
      (probably the operator forgot to actually instance any sensors)

The validator is OFFLINE — it never touches GraphDB.  It only inspects the
file contents and the building.yaml.  Wired into the FastAPI lifespan
in orchestrator/main.py.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Result types
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class TTLValidationIssue:
    """One validation finding."""

    severity: str          # "HARD_FAIL" | "WARN"
    ttl_path: str          # absolute or relative TTL location
    message: str           # operator-readable explanation

    def __str__(self) -> str:
        return f"[{self.severity}] {self.ttl_path}: {self.message}"


@dataclass
class TTLValidationReport:
    """Result of validating all TTL files for one building."""

    building_id: str
    declared_namespace: str
    ttl_files_checked: int = 0
    issues: List[TTLValidationIssue] = field(default_factory=list)

    @property
    def hard_failures(self) -> List[TTLValidationIssue]:
        return [i for i in self.issues if i.severity == "HARD_FAIL"]

    @property
    def warnings(self) -> List[TTLValidationIssue]:
        return [i for i in self.issues if i.severity == "WARN"]

    @property
    def ok(self) -> bool:
        return not self.hard_failures


# ─────────────────────────────────────────────────────────────────────────────
# Core validation
# ─────────────────────────────────────────────────────────────────────────────


def _normalize_namespace(ns: str) -> str:
    """Strip trailing whitespace; both '#' and '/' terminators are accepted
    verbatim because RDF treats them as semantically meaningful."""
    return (ns or "").strip()


def _parse_ttl(path: Path):
    """Parse a TTL file and return (rdflib.Graph, error_message_or_None).

    rdflib is a hard dependency of the orchestrator (it ships with the
    SPARQL agent), so a missing import here is a real configuration error
    we want to surface.
    """
    try:
        from rdflib import Graph
    except ImportError as e:
        return None, f"rdflib unavailable: {e}"

    g = Graph()
    try:
        g.parse(path.as_posix(), format="turtle")
        return g, None
    except Exception as e:
        return None, f"failed to parse {path.name}: {e}"


def _building_namespace_from_graph(graph, building_prefix: str) -> Optional[str]:
    """Return the URI bound to `building_prefix` in this graph, or None.

    rdflib's `namespaces()` yields (prefix, uri) pairs from the @prefix
    declarations actually present in the file.
    """
    for prefix, uri in graph.namespaces():
        if prefix == building_prefix:
            return str(uri)
    return None


def _count_triples_in_namespace(graph, namespace: str) -> int:
    """Count triples whose subject lives under `namespace`.

    Cheap warning signal: if the prefix is declared but unused, the
    building has no instances — operator probably dropped the wrong
    file.
    """
    count = 0
    for s, _p, _o in graph:
        if str(s).startswith(namespace):
            count += 1
    return count


def _shacl_validate(path: Path) -> List[str]:
    """Best-effort SHACL conformance against Brick reference shapes.

    Returns a list of WARN messages.  Empty list when:
      * brickschema or pyshacl are not installed (operator chose minimal deps)
      * validation passes cleanly

    SHACL is a soft signal — we don't HARD_FAIL on it because building TTLs
    routinely lawfully extend Brick (custom relationships, BACnet links) that
    the stock shapes flag.
    """
    try:
        from brickschema import Graph as BrickGraph  # type: ignore
    except ImportError:
        return []

    try:
        g = BrickGraph(load_brick=True)
        g.parse(path.as_posix(), format="turtle")
        ok, _results_graph, report_txt = g.validate()
        if ok:
            return []
        # Trim huge SHACL reports to one-line summaries operators can scan.
        lines = [
            ln.strip() for ln in str(report_txt).splitlines()
            if "Constraint Violation" in ln or "sh:resultMessage" in ln
        ]
        return lines[:10]  # cap to first 10 violations
    except Exception as e:  # noqa: BLE001 — best-effort
        return [f"SHACL validation aborted ({type(e).__name__}): {e}"]


def validate_building_ttls(
    building_id: str,
    declared_namespace: str,
    building_prefix: str,
    input_root: Path,
    *,
    run_shacl: bool = False,
) -> TTLValidationReport:
    """Validate every TTL under `input_root / building_id / **`.

    Parameters
    ----------
    building_id : str
        Logical id (e.g. "bldg1"); used only for report metadata.
    declared_namespace : str
        The ontology_namespace from building.yaml — the source of truth
        the TTL's @prefix declaration must match.
    building_prefix : str
        The short prefix declared in building.yaml (e.g. "bldg").
    input_root : Path
        Usually `Path("input")` in dev or `Path("/app/input")` in container.
    run_shacl : bool, default False
        Whether to attempt SHACL Brick conformance.  Off by default because
        it requires extra packages and is slow on large graphs.
    """
    report = TTLValidationReport(
        building_id=building_id,
        declared_namespace=_normalize_namespace(declared_namespace),
    )

    bldg_dir = input_root / building_id
    if not bldg_dir.exists():
        # Building dir missing is a different concern (BuildingRegistry handles
        # it); not the TTL validator's job to scream about absent input/<bldg>/.
        return report

    # Phase 12B convention: TTL files live either directly under input/<bldg>/
    # OR at the input/ root prefixed with the building id (legacy layout
    # from Phase 3, e.g. `input/bldg1_abacws_metadata.ttl`).
    ttl_paths: List[Path] = []
    ttl_paths.extend(sorted(bldg_dir.glob("**/*.ttl")))
    for legacy in sorted(input_root.glob(f"{building_id}_*.ttl")):
        ttl_paths.append(legacy)

    report.ttl_files_checked = len(ttl_paths)

    if not ttl_paths:
        # No TTLs is a soft warning — buildings without ontology still run
        # capability/floor-plan flows.
        report.issues.append(
            TTLValidationIssue(
                severity="WARN",
                ttl_path=str(bldg_dir),
                message=(
                    f"No *.ttl files found under {bldg_dir} or input/{building_id}_*.ttl. "
                    "Sensor queries that need the ontology will return empty results."
                ),
            )
        )
        return report

    for ttl in ttl_paths:
        graph, parse_err = _parse_ttl(ttl)
        if parse_err:
            report.issues.append(
                TTLValidationIssue(
                    severity="HARD_FAIL",
                    ttl_path=str(ttl),
                    message=parse_err,
                )
            )
            continue

        ttl_ns = _building_namespace_from_graph(graph, building_prefix)

        if ttl_ns is None:
            report.issues.append(
                TTLValidationIssue(
                    severity="HARD_FAIL",
                    ttl_path=str(ttl),
                    message=(
                        f"@prefix {building_prefix}: declaration is MISSING. "
                        f"Add `@prefix {building_prefix}: <{report.declared_namespace}> .` "
                        f"to the top of this file."
                    ),
                )
            )
            continue

        if _normalize_namespace(ttl_ns) != report.declared_namespace:
            report.issues.append(
                TTLValidationIssue(
                    severity="HARD_FAIL",
                    ttl_path=str(ttl),
                    message=(
                        f"@prefix {building_prefix}: mismatch.  "
                        f"TTL declares <{ttl_ns}> but building.yaml says "
                        f"ontology_namespace: <{report.declared_namespace}>.  "
                        f"SPARQL queries will return zero rows until one side is corrected."
                    ),
                )
            )
            continue

        # Prefix-in-namespace triple count — warn if zero (operator probably
        # dropped a shape/schema file instead of an instance file).
        instance_count = _count_triples_in_namespace(graph, ttl_ns)
        if instance_count == 0:
            report.issues.append(
                TTLValidationIssue(
                    severity="WARN",
                    ttl_path=str(ttl),
                    message=(
                        f"@prefix {building_prefix}: matches building.yaml, but file has "
                        "zero triples under that namespace (declared but unused)."
                    ),
                )
            )

        if run_shacl:
            for warn in _shacl_validate(ttl):
                report.issues.append(
                    TTLValidationIssue(
                        severity="WARN",
                        ttl_path=str(ttl),
                        message=f"SHACL: {warn}",
                    )
                )

    return report


# ─────────────────────────────────────────────────────────────────────────────
# Startup hook
# ─────────────────────────────────────────────────────────────────────────────


class TTLValidationError(RuntimeError):
    """Raised at startup when one or more TTLs fail HARD_FAIL checks.

    Wired into orchestrator/main.py lifespan so the orchestrator refuses to
    boot with a misconfigured ontology drop.
    """

    def __init__(self, report: TTLValidationReport) -> None:
        self.report = report
        lines = [
            f"TTL validation FAILED for building '{report.building_id}' "
            f"({report.ttl_files_checked} files checked, "
            f"{len(report.hard_failures)} hard failure(s)):"
        ]
        for issue in report.hard_failures:
            lines.append(f"  - {issue}")
        super().__init__("\n".join(lines))


def assert_ttl_validation_or_die(
    building_id: str,
    declared_namespace: str,
    building_prefix: str,
    input_root: Optional[Path] = None,
    *,
    run_shacl: bool = False,
) -> TTLValidationReport:
    """Hard-fail entrypoint for orchestrator startup.

    Returns the report on success (warnings logged but allowed).
    Raises `TTLValidationError` on any HARD_FAIL.
    """
    # Containers mount /app/input; dev runs from repo root with `input/`.
    if input_root is None:
        for candidate in (Path("/app/input"), Path("input")):
            if candidate.exists():
                input_root = candidate
                break
        if input_root is None:
            input_root = Path("input")

    report = validate_building_ttls(
        building_id=building_id,
        declared_namespace=declared_namespace,
        building_prefix=building_prefix,
        input_root=input_root,
        run_shacl=run_shacl,
    )

    for warn in report.warnings:
        logger.warning(f"[ttl_validator] {warn}")

    if not report.ok:
        for fail in report.hard_failures:
            logger.error(f"[ttl_validator] {fail}")
        raise TTLValidationError(report)

    logger.info(
        f"[ttl_validator] building '{building_id}' OK: "
        f"{report.ttl_files_checked} TTL file(s) checked, "
        f"{len(report.warnings)} warning(s)."
    )
    return report
