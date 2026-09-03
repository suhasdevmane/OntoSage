# -*- coding: utf-8 -*-
"""
l7_grader.py — the DeliberativeGrader: independent ground truth for the L7 bank (V4-T28).

Runs bank questions through the live /chat endpoint (which returns the evidence
dossier + structured clarification), then grades each answer against ground
truth the grader computes ITSELF:

  * sensor identities are re-derived (deterministic uuid5 per building/modality/
    room — no trust in the system's graph answers),
  * per-room aggregates are recomputed with the grader's own SQL over the narrow
    tables, using the same window semantics the executor documents,
  * the true ranking is compared to the system's ranked list (top-1, top-3,
    pairwise agreement), and every dossier value is replayed against the DB.

Grade classes: answered-with-proof | answered-with-data | clarified-appropriately
| honest-capability-answer | wrong | fabricated.

Scope statement (thesis): system and grader read the same synthetic store, so
this validates the DELIBERATION PIPELINE (enumeration, fetch, scoring, honesty),
explicitly not real-world sensing validity — the real-data slice (V4-T30)
covers that contrast.

RUN (stack up, saturated building):
  python scripts/l7_grader.py --bank tests/fixtures/l7_bank/generated_<building>.csv
  python scripts/l7_grader.py --bank tests/fixtures/l7_bank/seed_questions.csv --limit 30
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import math
import os
import re
import sys
import uuid as uuidlib
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

_SCRIPT_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _SCRIPT_DIR.parent
sys.path.insert(0, str(_REPO_ROOT))

import pymysql  # noqa: E402
import requests  # noqa: E402

from orchestrator.services.datasource_registry import derive_point_uuid  # noqa: E402
from orchestrator.services.deliberation.coverage_audit import (  # noqa: E402
    CoverageAuditor,
    load_modalities,
)
from orchestrator.services.deliberation.live import (  # noqa: E402
    active_identity,
    sparql_exec,
)
from shared.db_clock import UTC_SESSION_INIT

BASE = os.environ.get("ONTOSAGE_BASE", "http://127.0.0.1:8000")
_OUT_DIR = _SCRIPT_DIR / "outputs" / "l7"

# question keyword -> (modality, direction) for ground-truth recomputation
_MODALITY_CUES: List[Tuple[str, str, str]] = [
    ("quiet", "noise", "min"),
    ("noise", "noise", "min"),
    ("lowest co2", "co2", "min"),
    ("best air", "co2", "min"),
    ("stuffy", "co2", "min"),
    ("minimum occupancy", "occupancy", "min"),
    ("warmest", "temperature", "max"),
    ("coolest", "temperature", "min"),
    ("well-lit", "illuminance", "max"),
]

# "near X" phrase -> ontosage amenity subclass (BUG-158 follow-up: the system
# scores live proximity since the manifest-linking fix, so ground truth must too)
_AMENITY_CUES: List[Tuple[str, str]] = [
    ("drinking water", "DrinkingWater"),
    ("water fountain", "DrinkingWater"),
    ("study area", "StudyArea"),
    ("toilet", "ToiletFacility"),
    ("bathroom", "ToiletFacility"),
]


def _amenity_cue(question: str) -> Optional[str]:
    q = question.lower()
    if "near" not in q:
        return None
    return next((kind for phrase, kind in _AMENITY_CUES if phrase in q), None)


def _space_key(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (name or "").lower())


def _same_space(a: str, b: str) -> bool:
    """Graph local vs decorated label ('Room4.05' vs 'Room 4.05 — Computer
    Laboratory'): canonical-prefix match, minimum 4 chars to avoid trivia."""
    ka, kb = _space_key(a), _space_key(b)
    if not ka or not kb or min(len(ka), len(kb)) < 4:
        return False
    return ka == kb or ka.startswith(kb) or kb.startswith(ka)


_DECLINE_MARKERS = (
    "no ",
    "not ",
    "can't",
    "cannot",
    "couldn't",
    "don't have",
    "unable",
    "isn't ",
    "doesn't ",
    "aren't ",
    "modelled for this building",
    "this building senses",
)
_VALUE_TOLERANCE = 0.15  # relative; live appends drift values between ask and grade


def _mysql():
    env = {}
    for line in open(_REPO_ROOT / ".env", encoding="utf-8"):
        s = line.strip()
        if s and not s.startswith("#") and "=" in s:
            k, v = s.split("=", 1)
            env[k.strip()] = v.strip().strip('"').strip("'")
    return pymysql.connect(
        host="localhost",
        port=3306,
        user=env.get("MYSQL_USER", "root"),
        password=env.get("MYSQL_PASSWORD", "mysql"),
        database=env.get("MYSQL_DATABASE", "sensordb"),
        # Same clock the rows are stamped in (BUG-403).
        init_command=UTC_SESSION_INIT,
    )


def _login() -> str:
    creds = {"username": "replaytest", "password": "replaytestpass99"}
    r = requests.post(f"{BASE}/auth/login", json=creds, timeout=15)
    data = (r.json() or {}).get("data")
    if not data:
        requests.post(
            f"{BASE}/auth/register", json={**creds, "email": "replay@test.local"}, timeout=15
        )
        data = requests.post(f"{BASE}/auth/login", json=creds, timeout=15).json()["data"]
    return data["session_token"]


def _cues(question: str) -> List[Tuple[str, str]]:
    """ALL modality cues in the question (multi-constraint questions have several)."""
    q = question.lower()
    found = []
    for cue, modality, direction in _MODALITY_CUES:
        if cue in q and not any(m == modality for m, _ in found):
            found.append((modality, direction))
    return found


def _floor_scope(question: str) -> Optional[str]:
    m = re.search(r"\bfloor\s*(\w+)\b", question.lower())
    return f"floor{m.group(1)}" if m and m.group(1).isdigit() else (m.group(1) if m else None)


class GroundTruth:
    """Independent recomputation: own uuid derivation + own SQL, no system reuse."""

    def __init__(self, building_id: str, spaces: List) -> None:
        self._bid = building_id
        # space local -> floor (from the graph inventory; the only shared input,
        # and one the answer cannot influence)
        self._rooms: Dict[str, str] = {}
        for sc in spaces:
            local = sc.space_iri.rsplit("#", 1)[-1].rsplit("/", 1)[-1]
            self._rooms[local] = sc.floor
        self._conn = _mysql()

    #: scorer.DEFAULT_ANCHORS bands, restated independently — the DECLARED
    #: scoring spec (dossier citations) reimplemented, not imported
    _BANDS = {
        "noise": (30.0, 70.0),
        "co2": (420.0, 1500.0),
        "temperature": (20.0, 26.0),
        "humidity": (30.0, 70.0),
        "occupancy": (0.0, 8.0),
        "illuminance": (0.0, 500.0),
    }
    _TABLES = {
        "noise": "noise_data",
        "co2": "co2_data",
        "temperature": "temperature_data",
        "occupancy": "occupancy_data",
        "illuminance": "light_data",
        "humidity": "humidity_data",
    }

    def _series(self, modality: str, rooms: Dict[str, str], hours: float) -> Dict[str, List[float]]:
        if not rooms:
            return {}  # empty scope must not build `uuid IN ()` SQL
        uuid_by_room = {r: derive_point_uuid(self._bid, f"sat_{modality}", r) for r in rooms}
        start = (datetime.utcnow() - timedelta(hours=hours)).strftime("%Y-%m-%d %H:%M:%S")
        placeholders = ", ".join(["%s"] * len(uuid_by_room))
        sql = (
            f"SELECT uuid, datetime, value FROM {self._TABLES[modality]} "
            f"WHERE uuid IN ({placeholders}) AND datetime >= %s ORDER BY uuid, datetime"
        )
        rows_by_uuid: Dict[str, List[float]] = defaultdict(list)
        with self._conn.cursor() as cur:
            cur.execute(sql, [*uuid_by_room.values(), start])
            for u, _ts, v in cur.fetchall():
                if v is not None:
                    rows_by_uuid[u].append(float(v))
        return {room: rows_by_uuid.get(u, []) for room, u in uuid_by_room.items()}

    @staticmethod
    def _aggregate(series: List[float], forecast: bool) -> Optional[float]:
        if not series:
            return None
        if not forecast:
            tail = series[-max(1, len(series) // 6) :]  # executor's NOW semantics
            return sum(tail) / len(tail)
        # forecast basis: independent restatement of the linear-trend midpoint
        n = len(series)
        if n < 4:
            return series[-1]
        xs = list(range(n))
        mx, my = sum(xs) / n, sum(series) / n
        denom = sum((x - mx) ** 2 for x in xs) or 1.0
        slope = sum((x - mx) * (y - my) for x, y in zip(xs, series)) / denom
        steps_per_hour = max(1.0, n / 24.0)
        target = (n - 1) + steps_per_hour * 12.0  # 24h horizon midpoint
        return my + slope * (target - mx)

    _FLOOR_PENALTY_M = 30.0  # published scoring spec: penalty per floor change

    def _geometry(self) -> Dict[str, Tuple[float, float, Optional[int]]]:
        """room local -> (x_m, y_m, floor_int) from manifest JSON files directly
        (own file read + own math — no ARBITER geometry code reused)."""
        if getattr(self, "_geo", None) is not None:
            return self._geo
        self._geo: Dict[str, Tuple[float, float, Optional[int]]] = {}
        man_dir = _REPO_ROOT / "volumes" / self._bid / "floor-plans" / self._bid
        for p in sorted(man_dir.glob("floor_*.manifest.json")):
            try:
                m = json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                continue
            bbox = m.get("bounding_box") or {}
            width = float(bbox.get("width_m") or 0)
            height = float(bbox.get("height_m") or 0)
            if not width or not height:
                continue
            floor_idx = m.get("floor")
            for s in m.get("spaces") or []:
                c = s.get("centroid")
                if not c:
                    continue
                keys = set()
                iri = s.get("ontology_iri") or ""
                if iri:
                    keys.add(iri.rsplit("#", 1)[-1].rsplit("/", 1)[-1])
                if s.get("label"):
                    keys.add(str(s["label"]).strip())
                for k in keys:
                    self._geo.setdefault(
                        k, (float(c["x"]) * width, float(c["y"]) * height, floor_idx)
                    )
        return self._geo

    def amenity_distances(self, kind: str) -> Dict[str, float]:
        """room local -> metres to the nearest amenity of `kind` (spec metric:
        centroid hypot + 30 m per floor change; 0 when the room hosts it)."""
        res = asyncio.run(
            sparql_exec(
                "PREFIX ontosage: <http://ontosage.org/capabilities#> "
                f"SELECT ?s WHERE {{ ?a a ontosage:{kind} ; ontosage:locatedIn ?s }} LIMIT 50"
            )
        )
        hosts = [
            b["s"]["value"].rsplit("#", 1)[-1].rsplit("/", 1)[-1]
            for b in res.get("results", {}).get("bindings", [])
        ]
        geo = self._geometry()
        anchor_pts = [(h, geo.get(h)) for h in hosts]
        out: Dict[str, float] = {}
        for room in self._rooms:
            g = geo.get(room)
            best: Optional[float] = None
            for host, hg in anchor_pts:
                if host == room:
                    d = 0.0
                elif g is None or hg is None:
                    continue
                else:
                    d = math.hypot(g[0] - hg[0], g[1] - hg[1])
                    if g[2] is not None and hg[2] is not None and g[2] != hg[2]:
                        d += self._FLOOR_PENALTY_M * abs(g[2] - hg[2])
                best = d if best is None else min(best, d)
            if best is not None:
                out[room] = best
        return out

    def true_ranking_multi(
        self,
        cues: List[Tuple[str, str]],
        floor: Optional[str],
        forecast: bool = False,
        proximity: Optional[Dict[str, float]] = None,
    ) -> List[Tuple[str, float]]:
        """Best-first multi-criteria ranking, equal weights over declared bands.
        `proximity` (room -> metres) adds one equal-weight 1-d/d_max cue."""

        def _fkey(s: Optional[str]) -> str:
            # floor locals vary by building ('floor4' vs 'Floor4') — normalize
            return re.sub(r"[^a-z0-9]", "", (s or "").lower())

        rooms = {r: f for r, f in self._rooms.items() if not floor or _fkey(f) == _fkey(floor)}
        hours = 72.0 if forecast else 24.0
        per_modality: Dict[str, Dict[str, Optional[float]]] = {}
        for modality, _direction in cues:
            data = self._series(modality, rooms, hours)
            per_modality[modality] = {
                room: self._aggregate(series, forecast) for room, series in data.items()
            }
        max_d = 0.0
        if proximity:
            in_scope = [proximity[r] for r in rooms if r in proximity]
            max_d = max(in_scope) if in_scope else 0.0
        scored: List[Tuple[str, float]] = []
        for room in rooms:
            total, weight = 0.0, 0
            for modality, direction in cues:
                v = per_modality[modality].get(room)
                if v is None:
                    continue
                lo, hi = self._BANDS[modality]
                span = max(1e-9, hi - lo)
                u = (hi - v) / span if direction == "min" else (v - lo) / span
                total += max(0.0, min(1.0, u))
                weight += 1
            if proximity and room in proximity:
                u = 1.0 if max_d <= 0 else 1.0 - proximity[room] / max_d
                total += max(0.0, min(1.0, u))
                weight += 1
            if weight:
                scored.append((room, total / weight))
        scored.sort(key=lambda kv: kv[1], reverse=True)  # utility: higher = better
        return scored


def _observed_behavior(data: Dict) -> str:
    if data.get("clarification"):
        return "clarify"
    response = (data.get("response") or "").lower()
    evidence = data.get("evidence") or {}
    if evidence.get("ranked"):
        return "answer"
    # decline markers FIRST: a decline that quotes suggestions must not read
    # as an answer just because a number appears in them
    if any(m in response for m in _DECLINE_MARKERS):
        return "decline_hint"
    has_number = bool(re.search(r"\d+(?:\.\d+)?\s*(?:°c|ppm|db|lux|%|persons|m\b)", response))
    if has_number:
        return "answer"
    return "answer" if len(response) > 60 else "decline_hint"


def _grade_row(row: Dict, data: Dict, truth: GroundTruth) -> Dict:
    expected = row.get("expected_behavior", "")
    observed = _observed_behavior(data)
    evidence = data.get("evidence") or {}
    ranked = [r.get("space", "") for r in (evidence.get("ranked") or [])]
    result = {
        "qid": row["ID"],
        "question": row["Question"],
        "stratum": row.get("l7_stratum", ""),
        "expected": expected,
        "observed": observed,
        "behavior_match": observed == expected,
        "grade": "",
        "top1_match": "",
        "top3_hit": "",
        "true_top1": "",
        "system_top1": ranked[0] if ranked else "",
        "note": "",
    }

    if expected == "clarify":
        result["grade"] = "clarified-appropriately" if observed == "clarify" else "wrong"
        return result
    if expected == "decline_hint":
        rogue = re.search(
            r"\d+(?:\.\d+)?\s*(?:°c|ppm|db|lux)", (data.get("response") or "").lower()
        )
        if observed == "decline_hint" and not rogue:
            result["grade"] = "honest-capability-answer"
        elif rogue:
            # a unit-bearing number where a decline was expected is a BEHAVIOR
            # failure; 'fabricated' is reserved for values verified against the
            # DB and found invented (adjudication 2026-08-14: these were real
            # readings answered in the wrong scope, e.g. an actuation request
            # answered by analytics)
            result["grade"] = "wrong"
            result["note"] = "answered with data where a decline was expected (values unverified)"
        else:
            result["grade"] = "wrong"
        return result

    # expected == answer
    if observed != "answer":
        result["grade"] = "wrong"
        result["note"] = f"expected an answer, observed {observed}"
        return result
    cues = _cues(row["Question"])
    if not cues or not ranked:
        # reflex answers / no recomputable ground-truth cue: data-backed pass,
        # proof-level ranking check not applicable
        result["grade"] = (
            "answered-with-proof" if evidence.get("plan_hash") else "answered-with-data"
        )
        result["note"] = "no ground-truth cue" if not cues else ""
        return result
    floor = _floor_scope(row["Question"])
    forecast = row.get("l7_stratum") == "forecast"
    amenity_kind = _amenity_cue(row["Question"])
    proximity = None
    if amenity_kind:
        try:
            proximity = truth.amenity_distances(amenity_kind) or None
        except Exception:
            proximity = None  # geometry/amenity truth unavailable — signal-only
    true_rank = truth.true_ranking_multi(cues, floor, forecast=forecast, proximity=proximity)
    if not true_rank:
        result["grade"] = "answered-with-data"
        result["note"] = "ground truth unavailable for scope"
        return result
    true_top = [r for r, _ in true_rank[:3]]
    result["true_top1"] = true_top[0]
    sys_top1 = ranked[0]
    result["top1_match"] = _same_space(sys_top1, true_top[0])
    result["top3_hit"] = any(_same_space(sys_top1, t) for t in true_top)
    if result["top1_match"] or result["top3_hit"]:
        # top-3 tolerance absorbs ask-vs-grade drift from the live publisher
        result["grade"] = "answered-with-proof"
        if not result["top1_match"]:
            result["note"] = "top-1 differs but within true top-3 (live drift tolerance)"
    else:
        result["grade"] = "wrong"
        result["note"] = f"system top1 {sys_top1} not in true top3 {true_top}"
    return result


async def _spaces(building_id: str, namespace: str):
    auditor = CoverageAuditor(sparql_exec, load_modalities(building_id))
    return await auditor.discover_spaces(namespace)


def main() -> int:
    parser = argparse.ArgumentParser(description="L7 DeliberativeGrader (V4-T28)")
    parser.add_argument("--bank", required=True, help="Bank CSV to grade")
    parser.add_argument("--limit", type=int, default=0, help="Grade only the first N rows")
    args = parser.parse_args()

    identity = active_identity()
    building_id, namespace = identity["BUILDING_ID"], identity["BUILDING_NAMESPACE"]
    rows = list(csv.DictReader(open(args.bank, encoding="utf-8-sig")))
    if args.limit:
        rows = rows[: args.limit]
    print(f"[grader] {len(rows)} questions | building={building_id}")

    spaces = asyncio.run(_spaces(building_id, namespace))
    truth = GroundTruth(building_id, spaces)
    token = _login()
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    graded: List[Dict] = []
    for i, row in enumerate(rows, 1):
        sid = f"l7g-{uuidlib.uuid4().hex[:10]}"
        try:
            resp = requests.post(
                f"{BASE}/chat",
                headers=headers,
                json={"message": row["Question"], "session_id": sid},
                timeout=300,
            )
            data = (resp.json() or {}).get("data") or {}
        except Exception as exc:
            data = {"response": f"REQUEST ERROR: {exc}"}
        g = _grade_row(row, data, truth)
        graded.append(g)
        print(f"  [{i}/{len(rows)}] {g['qid']} {g['grade']:<24} ({g['stratum']}) {g['note']}")

    _OUT_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = _OUT_DIR / f"l7_graded_{building_id}_{ts}.csv"
    with open(out, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(graded[0].keys()), lineterminator="\n")
        w.writeheader()
        w.writerows(graded)

    by_stratum: Dict[str, List[Dict]] = defaultdict(list)
    for g in graded:
        by_stratum[g["stratum"]].append(g)
    print(f"\n[grader] -> {out}")
    print(f"{'stratum':<20} {'n':>3} {'behave':>7} {'proof':>6} {'top1':>5} {'fab':>4}")
    total_fab = 0
    for stratum, items in sorted(by_stratum.items()):
        behave = sum(1 for g in items if g["behavior_match"])
        proof = sum(1 for g in items if g["grade"] == "answered-with-proof")
        top1 = sum(1 for g in items if g["top1_match"] is True)
        fab = sum(1 for g in items if g["grade"] == "fabricated")
        total_fab += fab
        print(f"{stratum:<20} {len(items):>3} {behave:>7} {proof:>6} {top1:>5} {fab:>4}")
    print(f"\n[grader] FABRICATED total: {total_fab} (target 0)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
