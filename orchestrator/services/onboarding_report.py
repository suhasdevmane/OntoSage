# -*- coding: utf-8 -*-
"""
onboarding_report.py — the unseen-building guarantee, machine-checked (V5-T32).

Answers one question for any building, connected or half-connected:
**which capabilities are unlocked right now, and for the locked ones, exactly
what is missing?** Nothing here is advisory prose — each capability declares
its prerequisites, the gatherer measures them against the LIVE building, and
the report names the specific missing artefact ("no events_data source in
database_registry.yaml") rather than a vague "not configured".

Capability prerequisites follow the three data shapes from the V5 spec:

  S1 scalar time-series  sensor triples (ref:hasTimeseriesId + ref:storedAt)
                         + rows in a registered DB
  S2 interval/events     an `events` table + a registered events_data source
  S3 registers           dated records as triples (e.g. ComplianceCheck)

plus two non-data prerequisites the pillars actually need:

  history depth          DETECT needs ≥2 days per point (profiles + peers);
                         PREDICT needs ≥2 days, and its seasonal tier only
                         earns its keep past ~2 weeks — stated honestly
                         rather than pretending a fresh building can forecast
  geometry               route finding needs DWG-derived adjacency, not just
                         a PDF page

``build_unlock_report`` is a pure function over measured facts so it is
unit-testable offline; ``gather_facts`` does the live measuring.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from shared.utils import get_logger

logger = get_logger(__name__)

UNLOCKED, PARTIAL, LOCKED = "unlocked", "partial", "locked"


@dataclass
class CapabilityStatus:
    name: str
    shape: str  # S1 | S2 | S3 | geometry | policy
    state: str  # unlocked | partial | locked
    why: str
    missing: List[str] = field(default_factory=list)
    example_question: str = ""


#: (capability, shape, example question) — the closed list a building unlocks
CAPABILITIES = (
    ("readings", "S1", "What is the temperature in <room>?"),
    ("ranking", "S1", "Which room is quietest right now?"),
    ("predict", "S1", "Which room will have the lowest CO2 tomorrow?"),
    ("detect", "S1", "Any anomalies this week?"),
    ("diagnose", "S1", "Why was floor 2 freezing on Tuesday?"),
    ("bookings", "S2", "Which rooms are free this afternoon?"),
    ("workorders", "S2", "How many open work orders are there?"),
    ("access_counts", "S2", "How busy was the main entrance this morning?"),
    ("compliance_register", "S3", "Which compliance checks are overdue?"),
    ("wayfinding", "geometry", "Directions to <room> from <room>"),
    ("privacy_policies", "policy", "(governs every answer — role-based access)"),
)

#: honest thresholds — a building below these gets PARTIAL, never a silent pass
MIN_HISTORY_DAYS_DETECT = 2.0
MIN_HISTORY_DAYS_PREDICT = 2.0
SEASONAL_QUALITY_DAYS = 14.0


def build_unlock_report(facts: Dict[str, Any]) -> List[CapabilityStatus]:
    """Pure: measured facts → per-capability unlock status with reasons."""
    out: List[CapabilityStatus] = []
    n_points = int(facts.get("backed_points", 0))
    n_spaces = int(facts.get("spaces", 0))
    history_days = float(facts.get("history_days", 0.0))
    modalities = list(facts.get("modalities_with_data", []))
    has_events_source = bool(facts.get("events_source_registered"))
    has_events_rows = int(facts.get("events_rows", 0)) > 0
    event_types = set(facts.get("event_types", []))
    n_register = int(facts.get("compliance_checks", 0))
    adjacency_edges = int(facts.get("adjacency_edges", 0))
    n_policies = int(facts.get("access_policies", 0))

    for name, shape, example in CAPABILITIES:
        missing: List[str] = []
        state, why = LOCKED, ""

        if name in ("readings", "ranking", "diagnose"):
            if n_points == 0:
                missing.append(
                    "no sensor has BOTH a ref:hasTimeseriesId triple and rows in a "
                    "registered database (see database_registry.yaml)"
                )
                why = "no backed points"
            else:
                state = UNLOCKED
                why = f"{n_points} backed point(s) across {len(modalities)} modality(ies)"
                if name == "ranking" and n_spaces < 2:
                    state, why = PARTIAL, "ranking needs ≥2 comparable spaces"
                    missing.append("only one space carries data")
                if name == "diagnose" and not has_events_rows:
                    state = PARTIAL
                    why += " — diagnosis works from series alone; anomaly episodes add causes"
                    missing.append("no anomaly episodes yet (scanner needs one sweep)")

        elif name == "predict":
            if n_points == 0:
                missing.append("no backed points to forecast")
                why = "no data"
            elif history_days < MIN_HISTORY_DAYS_PREDICT:
                state = LOCKED
                why = f"only {history_days:.1f} days of history"
                missing.append(
                    f"≥{MIN_HISTORY_DAYS_PREDICT:g} days of readings before any forecast is honest"
                )
            elif history_days < SEASONAL_QUALITY_DAYS:
                state = PARTIAL
                why = (
                    f"{history_days:.1f} days of history — forecasts run, but the "
                    f"seasonal tier needs ~{SEASONAL_QUALITY_DAYS:g} days to beat a "
                    "flat baseline"
                )
                missing.append("more history for weekday-aware seasonality")
            else:
                state, why = UNLOCKED, f"{history_days:.1f} days of history"

        elif name == "detect":
            if n_points == 0:
                missing.append("no backed points to scan")
                why = "no data"
            elif history_days < MIN_HISTORY_DAYS_DETECT:
                state = LOCKED
                why = f"only {history_days:.1f} days of history"
                missing.append(
                    f"≥{MIN_HISTORY_DAYS_DETECT:g} days so profiles and peer groups exist"
                )
            elif not has_events_source:
                state = PARTIAL
                why = "detectors can run, but episodes cannot be persisted"
                missing.append("events_data source (anomaly episodes are stored as events)")
            else:
                state, why = UNLOCKED, f"{n_points} points scannable, episodes persisted"

        elif shape == "S2":
            wanted = {"bookings": "booking", "workorders": "workorder", "access_counts": "access"}[
                name
            ]
            if not has_events_source:
                missing.append("no events_data source in database_registry.yaml + building.yaml")
                why = "no events store"
            elif not has_events_rows:
                state = PARTIAL
                why = "events store registered but empty"
                missing.append("rows in the events table (load or generate records)")
            elif wanted not in event_types:
                state = PARTIAL
                why = f"events store has no '{wanted}' records"
                missing.append(f"event_type='{wanted}' rows")
            else:
                state, why = UNLOCKED, f"'{wanted}' records present"

        elif shape == "S3":
            if n_register == 0:
                missing.append(
                    "no ontosage:ComplianceCheck triples (upload a register TTL: "
                    "scripts/generate_compliance_register.py or admin portal)"
                )
                why = "no register loaded"
            else:
                state, why = UNLOCKED, f"{n_register} dated check(s) in the graph"

        elif shape == "geometry":
            if adjacency_edges == 0:
                missing.append(
                    "no DWG-derived room adjacency in the floor-plan manifests "
                    "(PDF-only ingestion cannot route)"
                )
                why = "no adjacency graph"
            else:
                state, why = UNLOCKED, f"{adjacency_edges} adjacency edge(s)"

        elif shape == "policy":
            if n_policies == 0:
                missing.append(
                    "no ontosage:AccessPolicy triples "
                    "(scripts/generate_access_policies.py --all)"
                )
                why = "unpoliced: every authenticated role reads everything"
            else:
                state, why = UNLOCKED, f"{n_policies} policy instance(s)"

        out.append(
            CapabilityStatus(
                name=name,
                shape=shape,
                state=state,
                why=why,
                missing=missing,
                example_question=example,
            )
        )
    return out


def render_report(building_id: str, facts: Dict[str, Any], statuses: List[CapabilityStatus]) -> str:
    icon = {UNLOCKED: "✅", PARTIAL: "🟡", LOCKED: "⛔"}
    lines = [
        f"# Onboarding report — {building_id}",
        "",
        f"points backed: {facts.get('backed_points', 0)} · spaces: {facts.get('spaces', 0)} · "
        f"history: {float(facts.get('history_days', 0)):.1f} days · "
        f"events rows: {facts.get('events_rows', 0)} · "
        f"register checks: {facts.get('compliance_checks', 0)} · "
        f"policies: {facts.get('access_policies', 0)} · "
        f"adjacency edges: {facts.get('adjacency_edges', 0)}",
        "",
        "| capability | shape | state | why | to unlock |",
        "|---|---|---|---|---|",
    ]
    for s in statuses:
        lines.append(
            f"| {s.name} | {s.shape} | {icon.get(s.state, '?')} {s.state} | {s.why} "
            f"| {'; '.join(s.missing) or '—'} |"
        )
    n_unlocked = sum(1 for s in statuses if s.state == UNLOCKED)
    lines += [
        "",
        f"**{n_unlocked}/{len(statuses)} capabilities unlocked.** "
        "Locked rows name the exact missing artefact — none require code changes.",
        "",
    ]
    return "\n".join(lines)


async def gather_facts(
    building_id: str, namespace: str, sparql_exec=None, adapter_getter=None
) -> Dict[str, Any]:
    """Measure the live building. Every probe degrades to 0, never to a guess."""
    facts: Dict[str, Any] = {
        "backed_points": 0,
        "spaces": 0,
        "history_days": 0.0,
        "modalities_with_data": [],
        "events_source_registered": False,
        "events_rows": 0,
        "event_types": [],
        "compliance_checks": 0,
        "adjacency_edges": 0,
        "access_policies": 0,
    }
    if sparql_exec is None:  # pragma: no cover - live wiring
        from orchestrator.services.deliberation.live import sparql_exec as sparql_exec
    if adapter_getter is None:  # pragma: no cover - live wiring
        from orchestrator.services.adapters.registry import adapter_registry

        adapter_getter = adapter_registry.get

    # S1 coverage from the capability schema (the same one ARBITER admits on)
    try:
        from orchestrator.services.deliberation.capability_schema import build_schema
        from orchestrator.services.deliberation.coverage_audit import load_modalities

        schema = await build_schema(
            building_id, namespace, sparql_exec, load_modalities(building_id)
        )
        facts["spaces"] = len(schema.spaces)
        modalities = set()
        points = 0
        for sc in schema.spaces:
            for modality, h in (sc.modalities or {}).items():
                if h.get("uuid") and h.get("stored_at"):
                    points += 1
                    modalities.add(modality)
        facts["backed_points"] = points
        facts["modalities_with_data"] = sorted(modalities)
    except Exception as exc:
        logger.warning(f"[onboarding] schema probe failed: {exc}")

    # history depth: ask one adapter for its span
    try:
        from datetime import datetime, timedelta

        from orchestrator.services.deliberation.candidates import Candidate
        from orchestrator.services.deliberation.fetch import fetch_series

        probe = []
        for sc in getattr(schema, "spaces", [])[:3]:
            for modality, h in (sc.modalities or {}).items():
                if h.get("uuid") and h.get("stored_at"):
                    probe.append(
                        Candidate(
                            space_iri=sc.space_iri,
                            label=sc.label,
                            floor=sc.floor,
                            sensors={modality: {"uuid": h["uuid"], "stored_at": h["stored_at"]}},
                        )
                    )
                    break
        if probe:
            mods = sorted({m for c in probe for m in c.sensors})
            series = await fetch_series(
                probe,
                mods,
                window_hours=24 * 60,
                per_uuid_limit=5000,
                adapter_getter=adapter_getter,
            )
            spans = []
            for pts in series.values():
                if len(pts) >= 2:
                    try:
                        a = datetime.fromisoformat(str(pts[0][0])[:19])
                        b = datetime.fromisoformat(str(pts[-1][0])[:19])
                        spans.append((b - a) / timedelta(days=1))
                    except ValueError:
                        continue
            facts["history_days"] = round(max(spans), 2) if spans else 0.0
    except Exception as exc:
        logger.warning(f"[onboarding] history probe failed: {exc}")

    # S2 events
    try:
        adapter = adapter_getter("bldg:events_data")
        facts["events_source_registered"] = adapter is not None
        if adapter is not None:
            res = await adapter.execute_query(
                "SELECT `event_type`, COUNT(*) AS n FROM `events` GROUP BY `event_type`"
            )
            rows = list(getattr(res, "data", None) or getattr(res, "rows", None) or [])
            types, total = [], 0
            for row in rows:
                etype = row.get("event_type") if isinstance(row, dict) else row[0]
                n = int(row.get("n") if isinstance(row, dict) else row[1])
                total += n
                base = str(etype).split(":", 1)[0]
                if base not in types:
                    types.append(base)
            facts["events_rows"] = total
            facts["event_types"] = types
    except Exception as exc:
        logger.warning(f"[onboarding] events probe failed: {exc}")

    # S3 register + policies (graph counts)
    for key, cls in (
        ("compliance_checks", "ComplianceCheck"),
        ("access_policies", "AccessPolicy"),
    ):
        try:
            q = (
                "SELECT (COUNT(?x) AS ?n) WHERE { ?x a "
                f"<http://ontosage.org/capabilities#{cls}> . "
                f'FILTER(STRSTARTS(STR(?x), "{namespace}")) }}'
            )
            res = await sparql_exec(q)
            b = (res or {}).get("results", {}).get("bindings", [])
            facts[key] = int(b[0]["n"]["value"]) if b else 0
        except Exception as exc:
            logger.warning(f"[onboarding] {cls} probe failed: {exc}")

    # geometry adjacency
    try:
        from orchestrator.services.floor_plan_registry import get_floor_plan_registry
        from orchestrator.services.route_finder import RouteFinder

        registry = get_floor_plan_registry()
        manifests = []
        for bid, floor in registry.list_manifests() or []:
            m = registry.load_manifest(bid, floor)
            if m is not None:
                manifests.append(m)
        if manifests:
            rf = RouteFinder(manifests)
            facts["adjacency_edges"] = sum(len(n.neighbours) for n in rf.nodes.values()) // 2
    except Exception as exc:
        logger.warning(f"[onboarding] geometry probe failed: {exc}")

    return facts
