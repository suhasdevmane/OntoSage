# -*- coding: utf-8 -*-
"""onboarding_status.py — can this building answer questions yet, and what is missing?

TODO-072. The portability claim is that a building is onboarded entirely through
the Admin Console from an empty ``input/``: set identity, upload the TTL, connect
the datasource, add documents, add floor plans. Every one of those steps already
had an endpoint. What did not exist was a way to ASK whether they had been done —
so "is this building ready?" could only be answered by running questions at it
and seeing what came back, which conflates a missing step with a bad answer.

This module answers it directly, and answers it from the LIVE SYSTEM rather than
from a checklist someone ticked: the ontology step counts spaces in the graph,
the time-series step compares sensors the graph DECLARES against UUIDs that
actually have rows, and the floor-plan step reports the share of spaces linked to
an ontology IRI. A step is "done" because the data is there, not because a file
was uploaded.

Two steps are marked ``blocking``: without an identity and without an ontology
the system cannot answer anything at all. Documents and floor plans are
enrichment — their absence narrows what can be answered rather than breaking it,
and saying so is more useful than a red cross that implies failure.

Relationship to ``onboarding_report`` (V5-T32), which sits next to this and
answers an adjacent question: that module reports which CAPABILITIES a building
has unlocked ("ranking", "forecasting") and what each locked one still needs;
this module reports which SETUP STEPS have been done. They are two halves of one
screen — what have I configured, and what does that let the building do — so
``collect_status`` returns the capability report alongside its own steps rather
than measuring the same building twice in two places.

Building-agnostic: every value is resolved from the ACTIVE building
(settings.BUILDING_ID / BUILDING_NAMESPACE, its input folder, its graph). No
building is named here.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from shared.config import settings
from shared.utils import get_logger

logger = get_logger(__name__)

DOC_EXTS = frozenset({".md", ".txt", ".pdf"})
FLOOR_PLAN_EXTS = frozenset({".pdf", ".dwg", ".dxf"})


def _step(
    key: str,
    label: str,
    done: bool,
    detail: str,
    blocking: bool = False,
    hint: str = "",
) -> Dict[str, Any]:
    return {
        "key": key,
        "label": label,
        "done": bool(done),
        "detail": detail,
        "blocking": bool(blocking),
        "hint": hint if not done else "",
    }


def _input_root() -> Path:
    return Path(getattr(settings, "INPUT_ROOT", "") or "/app/input")


def _identity_step() -> Dict[str, Any]:
    """Identity is the one thing nothing else can be resolved without."""
    from orchestrator.services import admin_config

    try:
        cfg = admin_config.read_building_config() or {}
    except Exception as exc:
        return _step(
            "identity",
            "Building identity",
            False,
            f"could not read building.yaml: {exc}",
            blocking=True,
            hint="Set the building name and ontology namespace.",
        )
    bid = (cfg.get("building_id") or "").strip()
    name = (cfg.get("building_name") or "").strip()
    ns = (cfg.get("ontology_namespace") or "").strip()
    # A namespace left at the shipped example is not an identity: every TTL the
    # admin uploads would be validated against a namespace nobody owns.
    placeholder = (not ns) or ns.startswith("http://example.org/")
    done = bool(bid and name and not placeholder)
    detail = f"{name or '(no name)'} — {bid or '(no id)'}, namespace {ns or '(unset)'}"
    return _step(
        "identity",
        "Building identity",
        done,
        detail,
        blocking=True,
        hint="Set the building name and a real ontology namespace before uploading TTL.",
    )


async def _ontology_step() -> Dict[str, Any]:
    """Spaces in the graph — the unit almost every question is scoped to."""
    from orchestrator.services.ontology_manager import run_sparql_select

    ns = (getattr(settings, "BUILDING_NAMESPACE", "") or "").strip()
    # Same shape the coverage audit uses to find spaces — subclass closure over
    # brick:Room, scoped to this building's namespace — so this screen and the
    # deliberation lane cannot disagree about how many spaces the building has.
    query = (
        "PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#> "
        "PREFIX brick: <https://brickschema.org/schema/Brick#> "
        "SELECT (COUNT(DISTINCT ?space) AS ?spaces) WHERE { "
        "  ?space a ?cls . ?cls rdfs:subClassOf* brick:Room . "
        f'  FILTER(STRSTARTS(STR(?space), "{ns}")) '
        "}"
    )
    try:
        result = await run_sparql_select(query)
        if not result.get("ok"):
            raise RuntimeError(result.get("error") or "query rejected")
        rows = result.get("rows") or []
        spaces = int((rows[0].get("spaces") if rows else 0) or 0)
    except Exception as exc:
        logger.warning(f"[onboarding] ontology probe failed: {type(exc).__name__}: {exc}")
        return _step(
            "ontology",
            "Ontology (TTL)",
            False,
            f"graph unreachable ({type(exc).__name__}: {exc})",
            blocking=True,
            hint="Upload the building's Brick/BACnet TTL on the Ontology tab.",
        )
    return _step(
        "ontology",
        "Ontology (TTL)",
        spaces > 0,
        f"{spaces} space(s) in this building's namespace",
        blocking=True,
        hint="Upload the building's Brick/BACnet TTL on the Ontology tab.",
    )


async def _timeseries_step(answerability: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Both halves: a sensor is a triple AND its readings are rows somewhere.

    Reported together on purpose — a graph full of sensors with no rows behind
    them is the failure mode that looks like success on every other screen.
    """
    from orchestrator.services import admin_config

    try:
        dbs = admin_config.read_databases() or []
    except Exception as exc:
        dbs = []
        logger.warning(f"[onboarding] datasource read failed: {exc}")
    declared = int((answerability or {}).get("total_declared") or 0)
    with_data = int((answerability or {}).get("total_with_data") or 0)
    if not dbs:
        return _step(
            "timeseries",
            "Sensor data",
            False,
            "no datasource registered",
            blocking=False,
            hint="Register the time-series database on the Databases tab.",
        )
    detail = (
        f"{len(dbs)} datasource(s); {with_data} of {declared} declared sensor(s) have rows"
        if declared
        else f"{len(dbs)} datasource(s); the ontology declares no sensors yet"
    )
    return _step(
        "timeseries",
        "Sensor data",
        declared > 0 and with_data > 0,
        detail,
        blocking=False,
        hint="Register the database and link sensors with ref:hasTimeseriesId + ref:storedAt.",
    )


def _documents_step() -> Dict[str, Any]:
    d = _input_root() / "documents"
    files = (
        [p for p in d.iterdir() if p.is_file() and p.suffix.lower() in DOC_EXTS]
        if d.is_dir()
        else []
    )
    return _step(
        "documents",
        "Documents",
        bool(files),
        f"{len(files)} document(s) available for prose answers",
        blocking=False,
        hint="Upload policies or manuals so the building can answer from its own text.",
    )


def _floor_plans_step() -> Dict[str, Any]:
    """Manifests, and the share of spaces that resolved to an ontology IRI.

    The link rate is the number that matters: an unlinked space has geometry
    nothing can join to a sensor, which is why it sat undetected at exactly 50%
    across every floor until BUG-147.
    """
    try:
        from orchestrator.services.floor_plan_registry import get_floor_plan_registry

        registry = get_floor_plan_registry()
        pairs = registry.list_manifests() or []
        total = linked = 0
        for bid, floor in pairs:
            manifest = registry.load_manifest(bid, floor)
            if manifest is None:
                continue
            for space in manifest.spaces or []:
                total += 1
                if (space.ontology_iri or "").strip():
                    linked += 1
    except Exception as exc:
        logger.warning(f"[onboarding] floor-plan probe failed: {exc}")
        return _step(
            "floor_plans",
            "Floor plans",
            False,
            f"unavailable: {exc}",
            hint="Upload floor-plan PDF/DWG files named '<building> floor <N>.pdf'.",
        )
    if not pairs:
        return _step(
            "floor_plans",
            "Floor plans",
            False,
            "no floor plans ingested",
            hint="Upload floor-plan PDF/DWG files named '<building> floor <N>.pdf'.",
        )
    rate = (linked / total * 100) if total else 0.0
    return _step(
        "floor_plans",
        "Floor plans",
        total > 0,
        f"{len(pairs)} floor(s), {linked}/{total} space(s) linked to the ontology ({rate:.0f}%)",
        hint="Upload floor-plan PDF/DWG files named '<building> floor <N>.pdf'.",
    )


async def collect_status(answerability: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Per-step readiness for the ACTIVE building.

    ``answerability`` is the batch result the Databases tab already computes; it
    is passed in rather than recomputed so opening this screen does not fire a
    second round of probes at every datasource.
    """
    steps: List[Dict[str, Any]] = [
        _identity_step(),
        await _ontology_step(),
        await _timeseries_step(answerability),
        _documents_step(),
        _floor_plans_step(),
    ]
    blocking_done = all(s["done"] for s in steps if s["blocking"])
    return {
        "building_id": getattr(settings, "BUILDING_ID", ""),
        "can_answer": blocking_done,
        "complete": all(s["done"] for s in steps),
        "steps_done": sum(1 for s in steps if s["done"]),
        "steps_total": len(steps),
        "steps": steps,
        "capabilities": await _capability_report(),
    }


async def _capability_report() -> List[Dict[str, Any]]:
    """What the configured steps actually let this building DO (V5-T32).

    Reuses onboarding_report rather than re-deriving it: that module already
    declares each capability's prerequisites and names the specific missing
    artefact for the locked ones ("no events_data source in
    database_registry.yaml") instead of a vague "not configured". Surfacing it
    here is the point — it had no caller outside a CLI script, so the admin who
    most needed it never saw it.

    Degrades to an empty list: a screen that shows the setup steps is still
    useful when the deeper probe cannot run.
    """
    try:
        from orchestrator.services.onboarding_report import (
            build_unlock_report,
            gather_facts,
        )

        facts = await gather_facts(
            getattr(settings, "BUILDING_ID", ""),
            getattr(settings, "BUILDING_NAMESPACE", "") or "",
        )
        return [
            {
                "name": s.name,
                "state": s.state,
                "why": s.why,
                "missing": list(s.missing),
                "example_question": s.example_question,
            }
            for s in build_unlock_report(facts)
        ]
    except Exception as exc:
        logger.warning(f"[onboarding] capability report unavailable: {exc}")
        return []
