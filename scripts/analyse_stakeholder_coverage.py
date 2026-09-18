# -*- coding: utf-8 -*-
"""Which stakeholder questions this building can answer today, and what is missing.

WHAT THIS MEASURES, AND WHAT IT CANNOT
--------------------------------------
Two different things get confused when people say "coverage":

  DATA gap        the building holds no record or no measurement of the thing asked
                  about, so no wording could reach an answer.
  VOCABULARY gap  the building DOES hold it, but the words the question uses are not
                  in the register's lay terms, so the register lane never selects it.

Only the second is cheap to fix, and the two are indistinguishable from a pass/fail
answer log — which is why the previous triage runs (RUN1/2/3) could rank failures but
not say which kind they were. This script separates them by measuring both sides:

  demand   each catalogue record DECLARES its authoritative sources, the sensors it
           needs and the analysis required. Those declarations are matched, not the
           question text. A keyword read of the question lands on the wrong noun
           ("which room did the marketing team use" -> "team") where the declaration
           says "booking history" outright.
  supply   the live building: record classes and their instance counts and lay terms
           (record_registry), the measurand classes per floor that actually carry a
           timeseries reference (floor_modality_matrix), the floor-plan manifests, and
           config/saturation_modalities.yaml.
  reach    the LIVE product scorer (`record_registry.rank_record_classes`) is asked
           which register each question text actually selects. Reimplementing that here
           would measure the reimplementation. Demanded + held + not selected = a
           vocabulary gap, and the words those questions actually use, weighted by how
           distinctive they are, are reported as the fix.

LIMITS OF THE CLASSIFIER — read before quoting any number
---------------------------------------------------------
* It is a term matcher over the system's OWN vocabulary, not a semantic model. It
  cannot tell a question that needs a register from one that merely mentions it, and
  it cannot tell "how many work orders are open" from "why are so many work orders
  open" — both are filed as needing WorkOrder.
* Boilerplate is suppressed: any term appearing in more than ``--boilerplate-share``
  (default 10%) of declarations is dropped, because the catalogues share a long
  provenance preamble — "owner" is in 93% of the 2,960 declarations, "evidence" 91%,
  "permission" 87%, "access" 68% — and a term that common selects no register. The
  words the TBox marks ``o:qualifierTerms`` are dropped too, because BUG-545 stopped
  them selecting a register in the product. Both removals are printed, so the
  suppression is auditable rather than hidden.
* Hand-graded on a seeded sample of 24 rows (2026-09-17): the right register was in the
  top-3 demand for 17, with a spurious sibling in 5 of those, and MISSING for 7 (29%).
  Role counts survive that noise because they saturate at 37; raw question counts do
  not. Rank on roles; read every question count as +/- 30%.
* A demanded register with instances > 0 is counted as HELD. Held does not mean the
  register has the right COLUMNS for that question; this script does not check columns.
* Measured-quantity supply is counted from points that carry ``ref:hasTimeseriesId``.
  It does not verify rows exist in the backing store (BUG-531: 77 sensors carry two
  references, one synthetic and one real).
* Accuracy was checked by hand on a seeded random sample; ``--sample N`` prints it so
  the check can be repeated.

Run (needs the stack up for the live supply side; --offline reuses a cached capture):

    python scripts/analyse_stakeholder_coverage.py
    python scripts/analyse_stakeholder_coverage.py --sample 40
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Set, Tuple

REPO = Path(__file__).resolve().parents[1]
BANK = REPO / "docs" / "smart_building_questions.csv"
MODALITIES = REPO / "config" / "saturation_modalities.yaml"
RECORD_DOCS = REPO / "ontology" / "record_documents"
OUT_CSV = REPO / "docs" / "stakeholder_coverage.csv"
CACHE = REPO / "scripts" / "outputs" / "stakeholder_coverage_supply.json"

CATALOGUE_SOURCE = "stakeholder_catalogue_37"
CONTAINER = "ontosage-orchestrator"

#: The declaration fields a catalogue record uses to say what it needs. The question
#: text is deliberately NOT in here — it is used only for the reachability check.
#:
#: ``Answer_Boundary`` is deliberately EXCLUDED. It states what the answer must NOT do,
#: and reading it as demand inverts its meaning: UG-002's boundary says sound statistics
#: "cannot ... guarantee silence", and including it filed a study-space question as
#: needing the WARRANTY register, because "guarantee" is one of that register's lay
#: terms. Measured on the first pass, that one field alone produced 226 Warranty rows
#: across 28 roles, nearly all of them spurious.
DECLARATION_FIELDS = (
    "Sensors_Required",
    "Authoritative_Sources",
    "Analysis_Required",
)

#: Needs that are not a register and not a measurand. Each is matched by phrases the
#: catalogues themselves use; the phrases were read off the declaration n-grams that
#: matched NO register term and NO modality, ranked by how many roles used them, so
#: this list is discovered rather than imagined. Terms are lowercase, whole-word.
NON_REGISTER_NEEDS: Dict[str, Tuple[str, ...]] = {
    "space_area": (
        "floor area",
        "net internal area",
        "gross internal area",
        "usable area",
        "area per person",
        "square metres",
        "per square metre",
        "space inventory",
    ),
    "space_capacity": (
        "room capacity",
        "seating capacity",
        "design capacity",
        "occupancy limit",
        "capacity limit",
        "permitted capacity",
    ),
    "route_graph": (
        "route graph",
        "step-free route",
        "wayfinding",
        "walking route",
        "travel distance",
    ),
    "identity_directory": (
        "hr record",
        "staff directory",
        "student record",
        "identity record",
        "enrolment",
        "role assignment",
        "named individual",
    ),
    "it_network_telemetry": (
        "network telemetry",
        "wifi",
        "wi-fi",
        "wireless",
        "switch port",
        "server room",
        "patch record",
        "network record",
        "comms room",
        "network coverage",
    ),
    "weather_forecast": (
        "weather forecast",
        "weather data",
        "external weather",
        "outside air forecast",
        "met office",
    ),
    "cctv_video": ("cctv", "video surveillance", "camera footage", "video record"),
    "finance_ledger": (
        "general ledger",
        "purchase order",
        "invoice record",
        "finance system",
        "budget line",
        "procurement record",
    ),
    "insurance_policy": (
        "insurance policy",
        "policy schedule",
        "claims history",
        "sum insured",
        "underwriting",
    ),
    "carbon_factor": (
        "emission factor",
        "carbon factor",
        "grid intensity",
        "carbon accounting",
        "scope 1",
        "scope 2",
        "scope 3",
    ),
}

#: What the building actually holds for each non-register need, measured 2026-09-17 and
#: quoted with its count so the verdict can be re-checked rather than believed. A need
#: absent from this map is held in full and is therefore NOT a gap.
NON_REGISTER_SUPPLY: Dict[str, str] = {
    "space_area": (
        "PARTIAL: 266/354 floor-plan spaces carry area_m2, but the GRAPH holds none "
        "(brick:area count 0), so per-m2 benchmarks cannot join area to energy"
    ),
    "space_capacity": (
        "PARTIAL: 19/234 rooms carry hbco:roomCapacity; 0/354 floor-plan spaces carry " "capacity"
    ),
    "route_graph": (
        "PARTIAL: 16 AccessibleRoute records with routeFrom/routeTo/distance, 49 "
        "nearestVerticalRoute, 21 CirculationTime records, 260/354 spaces with "
        "adjacent_spaces; no whole-building traversable route graph"
    ),
    "identity_directory": (
        "ABSENT BY DESIGN: 20 Department records (team level). Named individuals are "
        "excluded by the catalogues' own answer boundaries"
    ),
    "it_network_telemetry": "ABSENT: no network, wifi or switch-port source is registered",
    "weather_forecast": (
        "PARTIAL: 3 Open-Meteo CURRENT-value feeds (temp, humidity, wind); no forecast "
        "horizon, so 'next Wednesday' questions have no weather input"
    ),
    "cctv_video": "ABSENT: no video source, and excluded by the privacy boundaries",
    "finance_ledger": "PARTIAL: 24 CostLine and 4 Tariff records; no ledger or PO feed",
    "insurance_policy": "ABSENT: no policy, claims or sum-insured record",
    "carbon_factor": (
        "PARTIAL: config/benchmarks.csv carries carbon_intensity in kgCO2e/m2/year, but "
        "its normalisation column is floor_area_m2 and the graph holds no area"
    ),
}

#: Two words that name the SAME thing to a reader and different things to a matcher.
#: Kept tiny on purpose: every entry is a claim, and a wrong one manufactures coverage.
_DOC_TERMS = (
    "policy",
    "policies",
    "procedure",
    "procedures",
    "manual",
    "guidance",
    "standard operating",
    "code of practice",
)


# ---------------------------------------------------------------------------
# supply: what the building holds, read live
# ---------------------------------------------------------------------------


def _docker(pycode: str, timeout: int = 300) -> str:
    """Run python inside the orchestrator container and return its stdout."""
    proc = subprocess.run(
        ["docker", "exec", CONTAINER, "python", "-c", pycode],
        capture_output=True,
        text=True,
        timeout=timeout,
        encoding="utf-8",
        errors="replace",
    )
    return proc.stdout or ""


def _marked(out: str, marker: str = "JSONSTART") -> object:
    for line in out.splitlines():
        if line.startswith(marker):
            return json.loads(line[len(marker) :])
    raise RuntimeError("no marked JSON in container output")


_RECORD_CAPTURE = """
import asyncio, json
from orchestrator.services import record_registry as rr
loop = asyncio.new_event_loop()
held = loop.run_until_complete(rr.record_classes())
loop.run_until_complete(rr.load_lay_terms())
print("JSONSTART" + json.dumps({
    "held": [{"name": c.local_name, "label": c.label, "n": c.instances,
              "terms": list(c.terms), "qualifiers": list(c.qualifiers)} for c in held],
    "all_terms": {k: list(v) for k, v in rr._ALL_CLASS_TERMS.items()},
}, ensure_ascii=False))
"""

_FLOORPLAN_CAPTURE = """
import glob, json
rows = []
for p in sorted(glob.glob("/app/floor_plans/*/floor_*.manifest.json")):
    d = json.load(open(p))
    sp = d.get("spaces") or []
    rows.append({
        "file": p.rsplit("/", 1)[-1],
        "schema": d.get("schema_version"),
        "spaces": len(sp),
        "with_area": sum(1 for s in sp if s.get("area_m2")),
        "with_iri": sum(1 for s in sp if s.get("ontology_iri")),
        "with_adjacent": sum(1 for s in sp if s.get("adjacent_spaces")),
        "with_capacity": sum(1 for s in sp if s.get("capacity")),
    })
print("JSONSTART" + json.dumps(rows, ensure_ascii=False))
"""


_REACH_CAPTURE = """
import asyncio, json, sys
from orchestrator.services import record_registry as rr
loop = asyncio.new_event_loop()
held = loop.run_until_complete(rr.record_classes())
loop.run_until_complete(rr.load_lay_terms())
out = {}
for qid, text in json.load(sys.stdin).items():
    pick = rr.held_record_class(text, held)
    ranked = rr.rank_record_classes(text, held)[:3]
    out[qid] = {
        "picked": pick.local_name if pick else None,
        "ranked": [c.local_name for _, c in ranked],
        "absent": rr.absent_record_class(text, held),
    }
print("JSONSTART" + json.dumps(out, ensure_ascii=False))
"""


def capture_reach(questions: List[Dict[str, str]]) -> Dict[str, Dict[str, object]]:
    """Ask the LIVE register lane which register each question actually selects.

    This is the point of the whole exercise: the reachability side must be the
    system's own scorer, not a second implementation of it in this file. A
    reimplementation would measure the reimplementation.
    """
    payload = {(q.get("﻿ID") or q.get("ID", "")): q.get("Question", "") for q in questions}
    proc = subprocess.run(
        ["docker", "exec", "-i", CONTAINER, "python", "-c", _REACH_CAPTURE],
        input=json.dumps(payload, ensure_ascii=False),
        capture_output=True,
        text=True,
        timeout=1800,
        encoding="utf-8",
        errors="replace",
    )
    return _marked(proc.stdout or "")


def capture_supply() -> Dict[str, object]:
    """Read the live building: registers, measurand classes per floor, floor plans."""
    records = _marked(_docker(_RECORD_CAPTURE))
    floorplans = _marked(_docker(_FLOORPLAN_CAPTURE))
    matrix_raw = subprocess.run(
        ["docker", "exec", CONTAINER, "python", "scripts/floor_modality_matrix.py"],
        capture_output=True,
        text=True,
        timeout=900,
        encoding="utf-8",
        errors="replace",
    ).stdout
    return {
        "records": records,
        "floorplans": floorplans,
        "matrix_text": matrix_raw,
    }


def parse_matrix(text: str) -> Tuple[List[str], Dict[str, List[int]]]:
    """Measurand class -> per-floor sensor counts, from floor_modality_matrix output."""
    floors: List[str] = []
    counts: Dict[str, List[int]] = {}
    m = re.search(r"Floors the building declares \(\d+\): (\[.*?\])", text)
    if m:
        floors = [f.strip(" '\"") for f in m.group(1).strip("[]").split("', '")]
    for line in text.splitlines():
        m2 = re.match(r"^([A-Za-z][A-Za-z0-9_.]*)\s{2,}(.*)$", line)
        if not m2:
            continue
        cells = re.findall(r"(\d+|·)", m2.group(2))
        if len(cells) < 4:
            continue
        counts[m2.group(1)] = [0 if c == "·" else int(c) for c in cells]
    return floors, counts


def load_modalities() -> Dict[str, Dict[str, object]]:
    """modality name -> {brick_classes, scope, lay terms} from the config, no guessing."""
    text = MODALITIES.read_text(encoding="utf-8")
    out: Dict[str, Dict[str, object]] = {}
    current: Optional[str] = None
    in_classes = False
    for raw in text.splitlines():
        line = raw.rstrip()
        if re.match(r"^  [a-z][a-z0-9_]*:\s*$", line):
            current = line.strip().rstrip(":")
            out[current] = {"brick_classes": [], "scope": "room", "lay": []}
            in_classes = False
            continue
        if current is None:
            continue
        if re.match(r"^\s{4}brick_classes:\s*$", line):
            in_classes = True
            continue
        if in_classes and re.match(r"^\s{6}- ", line):
            out[current]["brick_classes"].append(line.split("- ", 1)[1].strip().split(":")[-1])
            continue
        if in_classes and not re.match(r"^\s{6}- ", line):
            in_classes = False
        m = re.match(r"^\s{6}scope:\s*(\w+)", line)
        if m:
            out[current]["scope"] = m.group(1)
        m = re.match(r"^\s{4}lay_terms:\s*\[(.*)\]", line)
        if m:
            out[current]["lay"] = [t.strip() for t in m.group(1).split(",") if t.strip()]
    return out


#: Lay wordings for each modality, so a declaration that says "CO2" is matched to the
#: co2 modality without relying on the Brick class name appearing in prose. Derived from
#: the modality name itself plus the wordings the catalogues use; every entry names a
#: quantity the config already declares, so none of them invents a capability.
MODALITY_WORDS: Dict[str, Tuple[str, ...]] = {
    "temperature": ("air temperature", "room temperature", "temperature"),
    "humidity": ("relative humidity", "humidity"),
    "co2": ("co2", "co₂", "carbon dioxide", "ndir"),
    "occupancy": ("occupancy", "people count", "footfall", "headcount", "occupancy count"),
    "noise": ("sound level", "acoustic", "laeq", "noise", "sound statistics", "decibel"),
    "illuminance": ("illuminance", "lux", "light level", "daylight", "task-area illuminance"),
    "door_contact": ("door contact", "door status", "door state"),
    "window_contact": ("window contact", "window status", "window opening"),
    "pm25": ("pm2.5", "pm2,5", "particulate", "fine particulate"),
    "pm10": ("pm10",),
    "pm1": ("pm1",),
    "energy_submeter": ("submeter", "sub-meter", "energy meter", "half-hourly", "kwh"),
    "electric_power": ("electrical power", "power draw", "kw demand", "electrical demand"),
    "water_flow": ("water meter", "water consumption", "water volume"),
    "water_flow_rate": ("water flow", "flow rate"),
    "water_level": ("water level", "tank level"),
    "waste_fill": ("bin fill", "fill level", "fill threshold"),
    "waste_weight": ("waste weight", "waste tonnage", "waste mass"),
    "lift_state": ("lift status", "lift telemetry", "elevator status", "lift availability"),
    "parking_free": ("parking bay", "parking occupancy", "free bays"),
    "supply_air_temperature": ("supply-air", "supply air temperature", "discharge air"),
    "return_air_temperature": ("return air", "mixed air"),
    "fan_state": ("fan status", "fan state", "plant run status"),
    "damper_position": ("damper",),
    "filter_differential_pressure": ("filter differential", "filter pressure"),
    "supply_air_flow": ("air flow", "airflow", "ventilation rate", "air change"),
    "carbon_monoxide": ("carbon monoxide", " co ", "co level"),
    "nitrogen_dioxide": ("no2", "nitrogen dioxide"),
    "formaldehyde": ("formaldehyde",),
    "tvoc": ("tvoc", "volatile organic"),
    "gas": ("gas detection", "combustible gas"),
    "motion": ("motion", "pir"),
    "occupancy_status": ("occupancy status", "occupied status"),
    "air_quality": ("air quality", "iaq"),
    "solar_irradiance": ("solar irradiance", "irradiance"),
    "rainfall": ("rainfall",),
    "soil_moisture": ("soil moisture",),
    "lighting_cct": ("colour temperature", "color temperature", "cct"),
    "leaving_water_temperature": ("flow temperature", "leaving water"),
    "entering_water_temperature": ("return temperature", "entering water"),
    "runtime_hours": ("run hours", "runtime", "run-time"),
    "position": ("valve position", "actuator position"),
    "water_usage": ("water usage",),
    "water_flow_hot": ("hot water",),
    "water_flow_chilled": ("chilled water",),
}


# ---------------------------------------------------------------------------
# matching
# ---------------------------------------------------------------------------


def _norm(text: str) -> str:
    return " " + re.sub(r"[^a-z0-9.+ ]+", " ", text.lower()) + " "


def _hit(term: str, blob: str) -> bool:
    return f" {term} " in blob or f" {term}s " in blob or f" {term}," in blob


def build_matcher(
    class_terms: Dict[str, Sequence[str]],
    declarations: Sequence[str],
    boilerplate_share: float,
) -> Tuple[Dict[str, List[str]], List[str]]:
    """Drop terms that are catalogue boilerplate rather than a register's name.

    Every catalogue record carries the same long provenance preamble. Measured over
    the 2,960 declarations: "owner" appears in 93% of them, "evidence" 91%,
    "permission" 87%, "access" 68%. A term that common selects no register — it is
    the house style. Any term (single word OR phrase) whose declaration frequency
    exceeds ``boilerplate_share`` is removed, and the removed list is printed so the
    suppression can be argued with.
    """
    blobs = [_norm(d) for d in declarations]
    total = max(len(blobs), 1)
    every = {t for terms in class_terms.values() for t in terms}
    freq: Counter = Counter()
    for blob in blobs:
        for term in every:
            if _hit(term, blob):
                freq[term] += 1
    suppressed = {t for t, n in freq.items() if n / total > boilerplate_share}
    kept = {name: [t for t in terms if t not in suppressed] for name, terms in class_terms.items()}
    return kept, sorted(suppressed)


def match_classes(blob: str, vocab: Dict[str, List[str]], top: int = 0) -> Dict[str, str]:
    """class -> the longest of its terms found in blob, optionally the top N only.

    Scored, not all-hits. The register lane in the product does the same thing
    (``rank_record_classes``): a lane that claims every register whose vocabulary
    grazes the text is first-match behaviour wearing a different coat.
    """
    scored: List[Tuple[int, str, str]] = []
    for name, terms in vocab.items():
        best = ""
        for term in terms:
            if len(term) > len(best) and _hit(term, blob):
                best = term
        if best:
            scored.append((len(best), name, best))
    scored.sort(reverse=True)
    if top:
        scored = scored[:top]
    return {name: term for _, name, term in scored}


def match_modalities(blob: str) -> Set[str]:
    hits = set()
    for mod, words in MODALITY_WORDS.items():
        for w in words:
            if w in blob:
                hits.add(mod)
                break
    return hits


def match_phrases(blob: str, groups: Dict[str, Tuple[str, ...]]) -> Set[str]:
    return {name for name, phrases in groups.items() if any(p in blob for p in phrases)}


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


def load_questions() -> List[Dict[str, str]]:
    rows = list(csv.DictReader(BANK.open(encoding="utf-8-sig")))
    return [r for r in rows if r.get("Source") == CATALOGUE_SOURCE]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--offline", action="store_true", help="reuse the cached supply capture")
    ap.add_argument(
        "--sample", type=int, default=0, help="print N classified rows for a hand check"
    )
    ap.add_argument("--boilerplate-share", type=float, default=0.10)
    ap.add_argument("--top", type=int, default=3, help="registers kept per question")
    args = ap.parse_args()

    questions = load_questions()

    if args.offline and CACHE.exists():
        supply = json.loads(CACHE.read_text(encoding="utf-8"))
    else:
        supply = capture_supply()
        supply["reach"] = capture_reach(questions)
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        CACHE.write_text(json.dumps(supply, ensure_ascii=False), encoding="utf-8")

    reach = supply.get("reach") or {}
    held = {c["name"]: c for c in supply["records"]["held"]}
    all_terms = {k: list(v) for k, v in supply["records"]["all_terms"].items()}
    floors, matrix = parse_matrix(supply["matrix_text"])
    modalities = load_modalities()

    declarations = [" ".join(q.get(f, "") for f in DECLARATION_FIELDS) for q in questions]

    # The TBox marks some words as QUALIFIERS: attributive words like "permitted" or
    # "confirmed" that describe a record rather than name one. BUG-545 stopped them
    # counting as a register selection in the product; a demand matcher that still
    # counted them would measure a behaviour the system no longer has.
    qualifiers = {t for c in supply["records"]["held"] for t in (c.get("qualifiers") or [])}
    all_terms = {k: [t for t in v if t not in qualifiers] for k, v in all_terms.items()}

    vocab, suppressed = build_matcher(all_terms, declarations, args.boilerplate_share)

    # which measurand classes actually carry a timeseries reference, and on how many floors
    mod_supply: Dict[str, Dict[str, object]] = {}
    for mod, cfg in modalities.items():
        present_floors = set()
        total = 0
        for cls in cfg["brick_classes"]:
            row = matrix.get(cls)
            if not row:
                continue
            total += sum(row)
            for i, n in enumerate(row):
                if n:
                    present_floors.add(floors[i] if i < len(floors) else f"col{i}")
        mod_supply[mod] = {
            "sensors": total,
            "floors": sorted(present_floors),
            "scope": cfg["scope"],
        }

    rows: List[Dict[str, object]] = []
    gap_roles: Dict[Tuple[str, str], Set[str]] = defaultdict(set)
    gap_questions: Counter = Counter()
    gap_silent: Counter = Counter()  # questions where the lane selected NOTHING at all
    vocab_words: Dict[str, Counter] = defaultdict(Counter)

    word_df: Counter = Counter()
    for q in questions:
        word_df.update(set(re.findall(r"[a-z]{4,}", q.get("Question", "").lower())))
    n_q = max(len(questions), 1)

    for q, decl in zip(questions, declarations):
        role = q.get("Stakeholder_Role", "")
        qid = q.get("﻿ID") or q.get("ID", "")
        dblob = _norm(decl)
        qblob = _norm(q.get("Question", ""))

        demanded = match_classes(dblob, vocab, top=args.top)
        live = reach.get(qid) or {}
        reached = set(live.get("ranked") or [])
        mods = match_modalities(dblob)
        others = match_phrases(dblob, NON_REGISTER_NEEDS)
        wants_doc = any(t in dblob for t in _DOC_TERMS)

        for cls in demanded:
            inst = held.get(cls, {}).get("n", 0)
            if not inst:
                key = ("DATA", f"register:{cls}")
            elif cls not in reached:
                key = ("VOCABULARY", f"register:{cls}")
                for word in set(re.findall(r"[a-z]{4,}", qblob)):
                    vocab_words[cls][word] += 1
            else:
                continue
            gap_roles[key].add(role)
            gap_questions[key] += 1
            if not reached:
                gap_silent[key] += 1

        for mod in mods:
            sup = mod_supply.get(mod)
            if sup is None:
                key = ("DATA", f"quantity:{mod} (not a declared modality)")
            elif sup["sensors"] == 0:
                key = ("DATA", f"quantity:{mod}")
            elif sup["scope"] == "room" and len(sup["floors"]) < len(floors) - 2:
                key = (
                    "DATA",
                    f"quantity:{mod} (partial: {len(sup['floors'])}/{len(floors)} floors)",
                )
            else:
                continue
            gap_roles[key].add(role)
            gap_questions[key] += 1

        for other in others:
            note = NON_REGISTER_SUPPLY.get(other)
            if note is None:
                continue  # fully held; not a gap
            key = ("DATA", f"other:{other} — {note}")
            gap_roles[key].add(role)
            gap_questions[key] += 1
            if not reached:
                gap_silent[key] += 1

        rows.append(
            {
                "id": q.get("﻿ID") or q.get("ID", ""),
                "role": role,
                "question": q.get("Question", "")[:300],
                "demanded_registers": "|".join(sorted(demanded)),
                "live_register_lane_picks": "|".join(live.get("ranked") or []),
                "live_absent_class": live.get("absent") or "",
                "demanded_quantities": "|".join(sorted(mods)),
                "other_needs": "|".join(sorted(others)),
                "wants_document": "yes" if wants_doc else "no",
            }
        )

    ranked = sorted(
        gap_roles.items(), key=lambda kv: (-len(kv[1]), -gap_questions[kv[0]], kv[0][1])
    )

    # Candidate lay terms: words that are DISTINCTIVE to a register's unreachable
    # questions. A word that is common across the whole corpus scores a lift near 1 and
    # is not a candidate — adding "current" to a register's vocabulary would make that
    # register swallow everything, which is the failure mode BUG-545 was logged for.
    vocab_words_top: Dict[str, List[str]] = {}
    for cls, counter in vocab_words.items():
        block = max(gap_questions[("VOCABULARY", f"register:{cls}")], 1)
        scored = []
        for word, n in counter.items():
            if n < 5:
                continue
            lift = (n / block) / max(word_df[word] / n_q, 1e-9)
            if lift > 1.8:
                scored.append((lift, n, word))
        scored.sort(reverse=True)
        vocab_words_top[cls] = [w for _, _, w in scored[:12]]

    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    with OUT_CSV.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(
            [
                "kind",
                "gap",
                "roles_blocked",
                "questions",
                "questions_where_register_lane_selected_nothing",
                "candidate_lay_terms",
                "roles",
            ]
        )
        for (kind, gap), roles in ranked:
            cls = gap.split(":", 1)[1] if gap.startswith("register:") else ""
            w.writerow(
                [
                    kind,
                    gap,
                    len(roles),
                    gap_questions[(kind, gap)],
                    gap_silent[(kind, gap)],
                    ";".join(vocab_words_top.get(cls, [])),
                    "; ".join(sorted(roles)),
                ]
            )

    silent = sum(1 for v in reach.values() if not v.get("ranked"))
    print(f"questions: {len(questions)}  roles: {len({q['Stakeholder_Role'] for q in questions})}")
    print(f"suppressed boilerplate terms ({len(suppressed)}): {', '.join(suppressed)}")
    print(f"floors: {len(floors)}  measurand classes in matrix: {len(matrix)}")
    print(
        f"register lane selects NOTHING for {silent}/{len(reach)} questions "
        f"({100.0 * silent / max(len(reach), 1):.1f}%)"
    )
    print(f"\nTOP GAPS (ranked by stakeholder roles blocked) -> {OUT_CSV}")
    for (kind, gap), roles in ranked[:25]:
        print(
            f"  {len(roles):2d} roles  {gap_questions[(kind, gap)]:5d} q "
            f"({gap_silent[(kind, gap)]:4d} silent)  {kind:10s} {gap}"
        )

    print("\nVOCABULARY: words DISTINCTIVE to the unreachable questions, per register")
    print("(lift = share of this register's unreachable questions / share of all questions;")
    print(" a word common everywhere scores ~1 and is not a candidate lay term)")
    for cls, words in sorted(
        vocab_words_top.items(),
        key=lambda kv: -gap_questions[("VOCABULARY", f"register:{kv[0]}")],
    )[:16]:
        print(f"  {cls}: {', '.join(words)}")

    if args.sample:
        seeded = sorted(rows, key=lambda r: hashlib.sha256(r["id"].encode()).hexdigest())
        print(f"\nSAMPLE ({args.sample}) for a hand check:")
        for r in seeded[: args.sample]:
            print(json.dumps(r, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
