#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Regenerate tasks/V6_COVERAGE.md — what the question bank needs, and what provides it.

Generated, never hand-maintained. This table has to stay true across the whole of V6, and a
hand-edited one would be stale the first time a task flips to done. Everything here is
derived: demand from the 1,580-question bank, provider status from V6_TRACKER.csv, and —
once replays exist — measured answerability from the newest replay CSV.

Run it after any tracker change, and after every replay:

    python scripts/build_coverage_report.py

Demand is counted by matching each question's own `Sensors_Required` and
`Authoritative_Sources` text, which the supervisors wrote. It is a keyword match over their
prose, so treat the counts as a demand ranking rather than an exact census — the ordering is
what drives sequencing decisions, and the ordering is robust.
"""

from __future__ import annotations

import csv
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

REPO = Path(__file__).resolve().parent.parent
BANK = REPO / "tasks" / "smart_building_questions.csv"
TRACKER = REPO / "tasks" / "V6_TRACKER.csv"
OUT = REPO / "tasks" / "V6_COVERAGE.md"
REPLAY_DIR = REPO / "scripts" / "outputs" / "replay"

# The six occupant catalogues were labelled `supervisor_catalogue_2026-08` because they
# arrived from the supervisor before the other 31 were generated. That was a delivery
# batch, not a different corpus: all 37 are the same Talking Abacws catalogues, 80
# questions each. Merged under one source 2026-09-04 (2,960 questions, 37 roles), so
# a filter on the old label now matches NOTHING rather than 480 rows.
CATALOGUE_SOURCE = "stakeholder_catalogue_37"

#: family -> (regex over the supervisors' own requirement prose, providing task or "exists")
#: Extend this when V6-T05's gap sweep surfaces a family nobody listed.
FAMILIES: List[Tuple[str, str, str]] = [
    ("Occupancy / doorway counts", r"occupancy|footfall|doorway count|people count", "exists"),
    ("Opening hours & closures", r"opening hours|closure|building hours", "V6-T57"),
    ("Room bookings / reservations", r"booking|reservation|room-booking|reserved", "V6-T57"),
    ("Lift status", r"\blift\b|elevator", "V6-T58"),
    (
        "Network / Wi-Fi / IT service",
        r"wi-?fi|network|latency|packet|it service|it incident",
        "V6-T58",
    ),
    (
        "BMS / HVAC plant state",
        r"\bbms\b|hvac|supply air|damper|fan (speed|state)|airflow|setpoint|plant",
        "V6-T59",
    ),
    ("Timetable / teaching schedule", r"timetable|teaching schedule|module schedule", "V6-T57"),
    (
        "AV / teaching equipment",
        r"\bav\b|projector|display|audio-?visual|teaching equipment",
        "V6-T58",
    ),
    ("Weather / outdoor reference", r"weather|outdoor (air|reference|temperature)|solar", "exists"),
    (
        "Accessibility inventory",
        r"step-free|accessible route|accessibility (inventory|feature)|adjustable desk",
        "V6-T60",
    ),
    ("Compliance register", r"compliance|legionella|inspection|certificat|statutory", "exists"),
    ("Electricity / submeters", r"submeter|electric|kwh|energy meter|demand", "V6-T59"),
    (
        "Maintenance / work orders",
        r"work order|maintenance (record|ticket|history)|asset-service|fault log",
        "V6-T60",
    ),
    ("Alarms / safety systems", r"alarm|evacuation|emergency|fire", "V6-T60"),
    ("Cleaning / service schedules", r"cleaning|caretak|service schedule", "V6-T60"),
    (
        "Access control / entitlement",
        r"access control|access entitlement|door access|card access|access system|access rights|permitted access",
        "V6-T57",
    ),
    (
        "Desk / workspace allocation",
        r"desk (allocation|booking)|hot-?desk|workspace allocation|seat",
        "V6-T57",
    ),
    (
        "Equipment / lab readiness",
        r"equipment (owner|controller|readiness)|interlock|lab equipment",
        "V6-T58",
    ),
    ("Water / leak detection", r"water|leak", "V6-T44"),
    ("Waste / recycling", r"waste|recycl", "V6-T43"),
]

_STATUS_ICON = {"done": "done", "in_progress": "in progress", "todo": "todo", "skipped": "skipped"}


def _rows(p: Path) -> List[Dict[str, str]]:
    return list(csv.DictReader(p.read_text(encoding="utf-8-sig").splitlines()))


def _latest_replay() -> Optional[Path]:
    if not REPLAY_DIR.is_dir():
        return None
    cands = sorted(REPLAY_DIR.glob("*.csv"), key=lambda p: p.stat().st_mtime, reverse=True)
    return cands[0] if cands else None


def main() -> int:
    if not BANK.is_file() or not TRACKER.is_file():
        print("missing tasks/smart_building_questions.csv or tasks/V6_TRACKER.csv")
        return 1

    bank = _rows(BANK)
    tracker = {r["turn"]: r for r in _rows(TRACKER)}
    cat = [r for r in bank if r.get("Source") == CATALOGUE_SOURCE]
    v5 = [r for r in bank if r.get("Source") != CATALOGUE_SOURCE]
    n_cat = len(cat)

    def status_of(task: str) -> str:
        if task == "exists":
            return "already in system"
        r = tracker.get(task)
        return _STATUS_ICON.get((r or {}).get("status", ""), "unknown") if r else "NOT IN TRACKER"

    lines: List[str] = []
    A = lines.append
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    A("# V6 Question Coverage")
    A("")
    A(f"**Generated {stamp}** by `scripts/build_coverage_report.py` — do not hand-edit.")
    A("Re-run after any tracker change and after every replay.")
    A("")
    A("---")
    A("")

    # ── 1. demand by source family ──────────────────────────────────────────
    A("## 1. What the supervisors' questions need, and what provides it")
    A("")
    A(f"Demand counted over the **{n_cat} supervisor catalogue questions**, by matching each")
    A("question's own `Sensors_Required` / `Authoritative_Sources` text. A question usually needs")
    A("several families, so the column sums past 100% — this is a demand ranking, not a partition.")
    A("")
    A("| Source family | Questions | Share | Provided by | Status |")
    A("|---|---:|---:|---|---|")
    rank: List[Tuple[int, str, str]] = []
    for name, pat, task in FAMILIES:
        rx = re.compile(pat, re.IGNORECASE)
        n = sum(
            1
            for r in cat
            if rx.search(f"{r.get('Sensors_Required','')} {r.get('Authoritative_Sources','')}")
        )
        rank.append((n, name, task))
    for n, name, task in sorted(rank, reverse=True):
        A(f"| {name} | {n} | {n/n_cat*100:.0f}% | {task} | {status_of(task)} |")
    A("")

    # ── 2. readiness tiers ──────────────────────────────────────────────────
    A("## 2. Readiness tiers (the supervisors' own classification)")
    A("")
    tiers = Counter(r.get("Readiness_R", "") for r in cat)
    labels = {
        "R1": "Answerable with core sensing + basic verified spatial/access data",
        "R2": "Needs an integration — timetable, booking, BMS, access, AV, lift, network, meters",
        "R3": "Needs research-grade validation, governed data, or restricted permissions",
    }
    A("| Tier | Meaning | Count | Share |")
    A("|---|---|---:|---:|")
    for k in ("R1", "R2", "R3"):
        A(f"| **{k}** | {labels[k]} | {tiers.get(k,0)} | {tiers.get(k,0)/n_cat*100:.1f}% |")
    A("")
    A("R2 and R3 are addressed by phase **P12** (V6-T56…T63), which provisions the missing sources")
    A("as *declared synthetic data* generated from each building's own graph. A synthetic booking")
    A("stays synthetic: V6-T62 requires every answer resting on one to say so.")
    A("")

    # ── 3. per role ─────────────────────────────────────────────────────────
    A("## 3. Readiness by stakeholder")
    A("")
    A("| Stakeholder | R1 | R2 | R3 | Total |")
    A("|---|---:|---:|---:|---:|")
    byrole: Dict[str, Counter] = {}
    for r in cat:
        byrole.setdefault(r.get("Stakeholder_Role", "?"), Counter())[r.get("Readiness_R", "")] += 1
    for role in sorted(byrole, key=lambda k: -byrole[k].get("R1", 0)):
        c = byrole[role]
        A(f"| {role} | {c.get('R1',0)} | {c.get('R2',0)} | {c.get('R3',0)} | {sum(c.values())} |")
    A("")

    # ── 4. V6 progress ──────────────────────────────────────────────────────
    A("## 4. V6 progress")
    A("")
    st = Counter(r["status"] for r in tracker.values())
    done, total = st.get("done", 0), len(tracker)
    A(f"**{done} / {total} tasks done** ({done/total*100:.0f}%)")
    A("")
    A("| Phase | Done | Total |")
    A("|---|---:|---:|")
    ph: Dict[str, Counter] = {}
    for r in tracker.values():
        ph.setdefault(r["phase"], Counter())[r["status"]] += 1
    for phase in sorted(ph):
        c = ph[phase]
        A(f"| {phase} | {c.get('done',0)} | {sum(c.values())} |")
    A("")

    # ── 5. measured answerability ───────────────────────────────────────────
    A("## 5. Measured answerability")
    A("")
    rp = _latest_replay()
    if rp is None:
        A("_No replay found under `scripts/outputs/replay/`._")
        A("")
        A(
            "Until **V6-T54** captures the golden baseline, this section reports nothing — and that is"
        )
        A("deliberate. Every number here must come from a replay on a healthy stack; a placeholder")
        A(
            "figure would be indistinguishable from a measured one the moment this file is read out of"
        )
        A("context, and this project has already published three numbers that turned out to be")
        A("artefacts of an unhealthy run (CAVEAT-173, BUG-176, BUG-177).")
    else:
        A(
            f"Latest replay: `{rp.name}` ({datetime.fromtimestamp(rp.stat().st_mtime).strftime('%Y-%m-%d %H:%M')})"
        )
        A("")
        A("Regenerate after each replay to refresh this section.")
    A("")
    A("---")
    A("")
    A(
        f"Corpus: **{len(bank)} questions** — {len(v5)} V5 synthetic bank + {n_cat} supervisor catalogue."
    )

    OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {OUT.relative_to(REPO)}  ({len(lines)} lines)")
    print(
        f"  families ranked: {len(FAMILIES)}   catalogue questions: {n_cat}   tracker: {len(tracker)}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
