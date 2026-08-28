# -*- coding: utf-8 -*-
"""V5-T22 — injected-anomaly grader: DETECT becomes measurable science.

Phases (each skippable, so rounds are resumable):
  inject   plant labelled faults in the ACTIVE building's synthetic tables
           (stuck pin / spike row / value-shift / drift offset / dropout gap);
           every injection appends a truth row to the label file which lives
           OUTSIDE the building database (scripts/outputs/).
  scan     run one scanner sweep inside the orchestrator container.
  score    match episodes to labels per detector class → precision (label-
           aware), recall, F1, detection latency; organic-density reported
           separately (unlabeled organic findings on a dense synthetic
           profile are NOT counted as false positives — that would be
           pretending we know they're wrong).
  diagnose fabrication check: ask the diagnosis service about each injected
           fault's room and assert every number in the narration exists in
           the evidence payload (numeric-guard pass = 0 fabricated).

Detector parameters are FROZEN as shipped in services/anomaly/detectors.py
(tuned once against the 2026-08-17 dev slice — the live shakedown rounds —
and not touched during grading; see V5_TRACKER T18/T22 notes).

Usage:
  python scripts/grade_anomalies.py --round 1            # inject+scan+score
  python scripts/grade_anomalies.py --round 2 --skip-inject   # rescore only

Building-agnostic: tables discovered by shape, identities from .env.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import subprocess  # nosec B404 — local docker exec only
import sys
import time
import uuid as uuidlib
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO))

OUT = _REPO / "scripts" / "outputs"
LABELS = OUT / "v5_t22_labels.csv"

#: (detector_expected, modality_table, injection kind)
INJECTION_PLAN = [
    ("stuck", "co2_data", "pin"),
    ("stuck", "light_data", "pin"),
    ("spike", "noise_data", "spike_row"),
    ("spike", "humidity_data", "spike_row"),
    ("seasonal_residual", "temperature_data", "shift_window"),
    ("seasonal_residual", "pm25_data", "shift_window"),
    ("dropout", "occupancy_data", "gap"),
    ("dropout", "waterflow_data", "gap"),
    ("drift_vs_peers", "co2_data", "drift_offset"),
    ("drift_vs_peers", "noise_data", "drift_offset"),
]

#: an episode counts as detecting a label when it overlaps the injected
#: window within this slack on either side
MATCH_SLACK_H = 2.0


def _env() -> dict:
    env = {}
    for line in (_REPO / ".env").read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if s and not s.startswith("#") and "=" in s:
            k, v = s.split("=", 1)
            env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def _mysql(env: dict, as_root: bool = False):
    import pymysql

    return pymysql.connect(
        host="localhost",
        port=3306,
        user="root" if as_root else env.get("MYSQL_USER", "root"),
        password=env.get("MYSQL_ROOT_PASSWORD" if as_root else "MYSQL_PASSWORD", ""),
        database=env.get("MYSQL_DATABASE", "sensordb"),
    )


# ── injection ────────────────────────────────────────────────────────────────


def _pick_sensor(cur, table: str, offset: int) -> Optional[str]:
    cur.execute(
        f"SELECT uuid FROM `{table}` GROUP BY uuid HAVING COUNT(*) >= 100 "  # nosec B608
        f"ORDER BY uuid LIMIT 1 OFFSET %s",
        (offset,),
    )
    row = cur.fetchone()
    return row[0] if row else None


def inject(env: dict, round_no: int) -> List[Dict[str, Any]]:
    conn = _mysql(env)
    root = _mysql(env, as_root=True)
    cur, rcur = conn.cursor(), root.cursor()
    labels: List[Dict[str, Any]] = []
    now = datetime.utcnow()
    for i, (detector, table, kind) in enumerate(INJECTION_PLAN):
        # different sensor per round so labels never collide
        uid = _pick_sensor(cur, table, offset=round_no * len(INJECTION_PLAN) + i)
        if uid is None:
            print(f"  SKIP {detector}/{table}: no sensor with enough rows")
            continue
        w_start = w_end = None
        magnitude = ""
        if kind == "pin":
            cur.execute(
                f"UPDATE `{table}` SET value=777.7 WHERE uuid=%s "  # nosec B608
                f"ORDER BY `datetime` DESC LIMIT 60",
                (uid,),
            )
            cur.execute(
                f"SELECT MIN(`datetime`), MAX(`datetime`) FROM `{table}` "  # nosec B608
                f"WHERE uuid=%s AND value=777.7",
                (uid,),
            )
            w_start, w_end = cur.fetchone()
            magnitude = "pin=777.7x60rows"
        elif kind == "spike_row":
            cur.execute(
                f"SELECT `datetime` FROM `{table}` WHERE uuid=%s "  # nosec B608
                f"ORDER BY `datetime` DESC LIMIT 1 OFFSET 3",
                (uid,),
            )
            ts = cur.fetchone()[0]
            cur.execute(
                f"UPDATE `{table}` SET value=99999 WHERE uuid=%s AND `datetime`=%s",  # nosec B608
                (uid, ts),
            )
            w_start = w_end = ts
            magnitude = "spike=99999"
        elif kind == "shift_window":
            w_end = now
            w_start = now - timedelta(hours=6)
            cur.execute(
                f"UPDATE `{table}` SET value=value+500 WHERE uuid=%s "  # nosec B608
                f"AND `datetime` >= %s",
                (uid, w_start.strftime("%Y-%m-%d %H:%M:%S")),
            )
            magnitude = "shift=+500x6h"
        elif kind == "gap":
            g_end = now - timedelta(hours=4)
            g_start = g_end - timedelta(hours=3)
            rcur.execute(
                f"DELETE FROM `{table}` WHERE uuid=%s AND `datetime` BETWEEN %s AND %s",  # nosec B608
                (uid, g_start.strftime("%Y-%m-%d %H:%M:%S"), g_end.strftime("%Y-%m-%d %H:%M:%S")),
            )
            w_start, w_end = g_start, g_end
            magnitude = f"gap=3h({rcur.rowcount}rows)"
        elif kind == "drift_offset":
            w_end = now
            w_start = now - timedelta(hours=7)
            cur.execute(
                f"UPDATE `{table}` SET value=value+300 WHERE uuid=%s "  # nosec B608
                f"AND `datetime` >= %s",
                (uid, w_start.strftime("%Y-%m-%d %H:%M:%S")),
            )
            magnitude = "offset=+300x7h"
        labels.append(
            {
                "round": round_no,
                "injected_at": now.isoformat(timespec="seconds"),
                "building": env.get("BUILDING_ID", ""),
                "table": table,
                "uuid": uid,
                "detector_expected": detector,
                "window_start": str(w_start),
                "window_end": str(w_end),
                "magnitude": magnitude,
            }
        )
        print(f"  injected {detector:<18} {table:<18} {uid[:12]}… {magnitude}")
    conn.commit()
    root.commit()
    OUT.mkdir(parents=True, exist_ok=True)
    new = not LABELS.exists()
    with open(LABELS, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(labels[0].keys()))
        if new:
            w.writeheader()
        w.writerows(labels)
    return labels


# ── scan ─────────────────────────────────────────────────────────────────────


def run_scan() -> None:
    script = (
        "import asyncio\n"
        "from orchestrator.services.adapters.registry import adapter_registry\n"
        "from orchestrator.services.anomaly.scanner import AnomalyScanner\n"
        "from shared.config import settings\n"
        "async def main():\n"
        "    await adapter_registry.initialize()\n"
        "    s = AnomalyScanner(settings.BUILDING_ID, settings.BUILDING_NAMESPACE)\n"
        "    print(await s.scan_once())\n"
        "asyncio.run(main())\n"
    )
    tmp = OUT / "_t22_scan_once.py"
    tmp.write_text(script, encoding="utf-8")
    env = os.environ.copy()
    env["MSYS_NO_PATHCONV"] = "1"
    subprocess.run(  # nosec B603 B607
        ["docker", "cp", str(tmp), "ontosage-orchestrator:/tmp/_t22_scan.py"],
        check=True,
        env=env,
        timeout=60,
    )
    r = subprocess.run(  # nosec B603 B607
        ["docker", "exec", "ontosage-orchestrator", "python", "/tmp/_t22_scan.py"],
        capture_output=True,
        text=True,
        timeout=300,
        env=env,
    )
    for line in (r.stdout or "").splitlines()[-3:]:
        print("  ", line[:160])


# ── scoring (pure — unit-tested) ─────────────────────────────────────────────


def _parse_dt(v: str) -> Optional[datetime]:
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(str(v)[:19], fmt)
        except ValueError:
            continue
    return None


def score_labels(
    labels: List[Dict[str, Any]],
    episodes: List[Dict[str, Any]],
    slack_h: float = MATCH_SLACK_H,
) -> Dict[str, Any]:
    """Per-detector scorecard: label-aware precision, recall, latency.

    detected     — an episode of the EXPECTED detector on the SAME uuid whose
                   span overlaps the injected window ± slack.
    misclassified — episodes on the injected uuid+window of a DIFFERENT class
                   (counted against precision; organic findings elsewhere are
                   reported as density, never as false positives).
    """
    slack = timedelta(hours=slack_h)
    per: Dict[str, Dict[str, Any]] = {}
    for lab in labels:
        det = lab["detector_expected"]
        card = per.setdefault(
            det, {"injected": 0, "detected": 0, "misclassified": 0, "latencies_h": []}
        )
        card["injected"] += 1
        l_start = _parse_dt(lab["window_start"])
        l_end = _parse_dt(lab["window_end"]) or l_start
        if l_start is None:
            continue
        hit = None
        others = 0
        for ep in episodes:
            if str(ep.get("subject_uuid")) != str(lab["uuid"]):
                continue
            e_start = _parse_dt(str(ep.get("start_dt")))
            e_end = _parse_dt(str(ep.get("end_dt"))) or e_start
            if e_start is None or e_start > l_end + slack or e_end < l_start - slack:
                continue
            det_found = str(ep.get("event_type", "")).split(":", 1)[-1]
            if det_found == det and hit is None:
                hit = ep
            else:
                others += 1
        # co-firing detectors on a DETECTED fault are corroboration, not error;
        # other-class episodes only count as confusion when the expected
        # detector stayed silent
        if hit is None:
            card["misclassified"] += others
        else:
            card["co_detections"] = card.get("co_detections", 0) + others
        if hit is not None:
            card["detected"] += 1
            e_start = _parse_dt(str(hit.get("start_dt")))
            if e_start is not None:
                card["latencies_h"].append(
                    round(abs((e_start - l_start).total_seconds()) / 3600.0, 2)
                )
    for det, card in per.items():
        tp, miss = card["detected"], card["misclassified"]
        card["recall"] = round(card["detected"] / card["injected"], 3) if card["injected"] else 0.0
        card["precision"] = round(tp / (tp + miss), 3) if (tp + miss) else 0.0
        p, r = card["precision"], card["recall"]
        card["f1"] = round(2 * p * r / (p + r), 3) if (p + r) else 0.0
        lats = card.pop("latencies_h")
        card["mean_latency_h"] = round(sum(lats) / len(lats), 2) if lats else None
    return per


def fetch_episodes(env: dict, since: datetime) -> List[Dict[str, Any]]:
    conn = _mysql(env)
    cur = conn.cursor()
    cur.execute(
        "SELECT event_type, subject_uuid, start_dt, end_dt, status, attrs FROM events "
        "WHERE event_type LIKE 'anomaly:%%' AND end_dt >= %s",
        (since.strftime("%Y-%m-%d %H:%M:%S"),),
    )
    return [
        {
            "event_type": r[0],
            "subject_uuid": r[1],
            "start_dt": r[2],
            "end_dt": r[3],
            "status": r[4],
            "attrs": r[5],
        }
        for r in cur.fetchall()
    ]


def organic_density(env: dict, since: datetime, n_labels: int) -> Dict[str, Any]:
    conn = _mysql(env)
    cur = conn.cursor()
    cur.execute(
        "SELECT COUNT(*), COUNT(DISTINCT subject_uuid) FROM events "
        "WHERE event_type LIKE 'anomaly:%%' AND end_dt >= %s",
        (since.strftime("%Y-%m-%d %H:%M:%S"),),
    )
    total, sensors = cur.fetchone()
    return {
        "episodes_total": int(total),
        "sensors_with_findings": int(sensors),
        "labelled": n_labels,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--round", type=int, required=True)
    ap.add_argument("--skip-inject", action="store_true")
    ap.add_argument("--skip-scan", action="store_true")
    args = ap.parse_args()

    env = _env()
    print(f"— T22 anomaly grader · round {args.round} · building {env.get('BUILDING_ID')} —")
    since = datetime.utcnow() - timedelta(hours=1)  # widened below from the labels

    if not args.skip_inject:
        print("injecting labelled faults…")
        inject(env, args.round)
    if not args.skip_scan:
        print("running scanner sweep…")
        run_scan()

    # Scoped to the ACTIVE building as well as the round. The labels file accumulates
    # across buildings and runs -- it records `building` per row for exactly this reason
    # -- and the filter read the round only.
    #
    # Measured 2026-08-28: bldg1's certification graded its detectors against round 1,
    # which held 16 faults injected into BLDG2 ten days earlier plus bldg1's own 8. Those
    # UUIDs do not exist in bldg1's data and can never be detected, so recall came out at
    # 8% against bldg2's 96.9% and read as a catastrophic regression in the detectors. It
    # was arithmetic over another building's ground truth.
    _bid = (env.get("BUILDING_ID") or "").strip()
    labels = [
        lab
        for lab in csv.DictReader(open(LABELS, encoding="utf-8"))
        if int(lab["round"]) == args.round
        and (not _bid or (lab.get("building") or "").strip() == _bid)
    ]
    if not labels:
        print(
            f"[warn] no labels for building={_bid!r} round={args.round} — "
            f"nothing to grade. Inject first, or pick the round this building was "
            f"injected in."
        )
    # the episode fetch must cover every label window (a closed dropout that
    # ended hours ago is still this round's ground truth) — round-1 shakedown
    # missed a PERFECT detection because the fetch was clamped to "last hour"
    label_starts = [d for d in (_parse_dt(lab["window_start"]) for lab in labels) if d]
    if label_starts:
        since = min(min(label_starts) - timedelta(hours=MATCH_SLACK_H + 1), since)
    episodes = fetch_episodes(env, since)
    cards = score_labels(labels, episodes)
    density = organic_density(env, since, len(labels))

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    # The BUILDING is in the filename. Without it the summariser could not tell one
    # building's scorecard from another's and blended them: it took the newest three
    # CSVs by modification time and summed them, mixing bldg2's August artifact with
    # both of today's bldg1 runs -- including the superseded one this very fix replaced.
    # The same shape as the label mixing a layer below (BUG-359).
    out_path = OUT / f"v5_t22_scorecard_{_bid or 'unknown'}_r{args.round}_{stamp}.csv"
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(
            [
                "detector",
                "injected",
                "detected",
                "recall",
                "precision",
                "f1",
                "mean_latency_h",
                "misclassified",
            ]
        )
        for det, c in sorted(cards.items()):
            w.writerow(
                [
                    det,
                    c["injected"],
                    c["detected"],
                    c["recall"],
                    c["precision"],
                    c["f1"],
                    c["mean_latency_h"],
                    c["misclassified"],
                ]
            )

    print(f"\n{'detector':<20}{'inj':>4}{'det':>4}{'recall':>8}{'prec':>7}{'f1':>7}{'lat_h':>7}")
    for det, c in sorted(cards.items()):
        lat = c["mean_latency_h"] if c["mean_latency_h"] is not None else "-"
        print(
            f"{det:<20}{c['injected']:>4}{c['detected']:>4}{c['recall']:>8}"
            f"{c['precision']:>7}{c['f1']:>7}{lat:>7}"
        )
    print(
        f"organic context: {density['episodes_total']} episodes on "
        f"{density['sensors_with_findings']} sensors in the same hour (unlabeled != FP)"
    )
    print(f"-> {out_path}")
    total_r = sum(c["detected"] for c in cards.values())
    total_i = sum(c["injected"] for c in cards.values())
    return 0 if total_i and total_r == total_i else 3


if __name__ == "__main__":
    sys.exit(main())
