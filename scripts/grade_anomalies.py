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
import inspect
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

# Imported AFTER the sys.path insert above — the repo is not on the path before it.
from orchestrator.services.anomaly import detectors as _detectors  # noqa: E402

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
    """A sensor with enough history, rotating by round so labels never collide.

    The offset WRAPS. It used to grow without bound as `round_no * len(INJECTION_PLAN) + i`,
    so from about round 8 it walked off the end of every small table — co2_data has 66
    eligible sensors, humidity_data 72, temperature_data 67 — and those injections were
    skipped with "no sensor with enough rows". The message says the data is missing; the
    data was there and the cursor had run past it.

    That silently shrinks the measurement: round 8 injected 4 of 9 planned faults, so recall
    was computed over whichever detectors happened to survive, and comparing it with an
    earlier round compared different question sets. Wrapping keeps every round testing the
    same plan.
    """
    cur.execute(
        f"SELECT COUNT(*) FROM (SELECT uuid FROM `{table}` "  # nosec B608
        f"GROUP BY uuid HAVING COUNT(*) >= 100) AS eligible"
    )
    row = cur.fetchone()
    eligible = int(row[0]) if row else 0
    if not eligible:
        return None
    cur.execute(
        f"SELECT uuid FROM `{table}` GROUP BY uuid HAVING COUNT(*) >= 100 "  # nosec B608
        f"ORDER BY uuid LIMIT 1 OFFSET %s",
        (offset % eligible,),
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

        # Anchor the time-window injections on THIS SENSOR'S OWN latest reading, not on
        # wall-clock now.
        #
        # BUG-360: bldg1 detected 2 of its own 8 injected faults and the reason was here.
        # Its co2, temperature and humidity tables stopped receiving rows on 2026-08-26
        # (0 of ~66-72 sensors writing in the last hour), so a window of "the last six
        # hours" contained nothing to shift, offset or delete. The UPDATE matched zero
        # rows, the label was written anyway, and the detector was then marked as having
        # missed a fault that was never injected.
        #
        # The two kinds that DID get detected -- pin and spike_row -- are exactly the two
        # that already anchored on the sensor's own newest rows (ORDER BY datetime DESC).
        cur.execute(
            f"SELECT MAX(`datetime`) FROM `{table}` WHERE uuid=%s",  # nosec B608
            (uid,),
        )
        _latest = (cur.fetchone() or [None])[0]
        anchor = _latest if isinstance(_latest, datetime) else now
        w_start = w_end = None
        magnitude = ""
        if kind == "pin":
            # Pin by TIME SPAN, not by row count.
            #
            # This pinned a fixed 60 rows, and detectors.stuck() requires the frozen run to
            # span `min_hours=6.0`. At the publisher's 30-second cadence 60 rows is THIRTY
            # MINUTES, so the injection could never satisfy the detector it was testing:
            # `stuck` scored 0/2 in every round and read as a detector defect. It is not —
            # the harness was injecting a fault below the detector's own definition, which
            # is this project's most-repeated failure in a new place.
            #
            # The span is read from the detector rather than restated here, so raising
            # min_hours cannot silently make these injections undetectable again.
            # Read by NAME, not by position: `__defaults__[-2]` gives the same 6.0 today
            # and silently becomes the wrong parameter the moment anyone adds an argument.
            _stuck_hours = float(
                inspect.signature(_detectors.stuck).parameters["min_hours"].default or 6.0
            )
            _span_hours = _stuck_hours + 1.0  # clear the boundary rather than sit on it
            cur.execute(
                f"SELECT MAX(`datetime`) FROM `{table}` WHERE uuid=%s",  # nosec B608
                (uid,),
            )
            _newest = cur.fetchone()[0]
            cur.execute(
                f"UPDATE `{table}` SET value=777.7 WHERE uuid=%s "  # nosec B608
                f"AND `datetime` > %s",
                (uid, _newest - timedelta(hours=_span_hours)),
            )
            _pinned = cur.rowcount
            # VERIFY the tail is actually constant, and re-pin if it is not.
            #
            # detectors.stuck() walks back from the NEWEST sample, so a single row written
            # after the pin ends the run at length zero and the fault vanishes. `docker stop`
            # lets the publisher finish an in-flight 30-second tick, and that one row was
            # enough: measured, the tail read [777.7 x7, 455.0] and stuck() returned nothing.
            # Run directly against a genuinely constant tail the same detector returns an
            # 8.0-hour finding at score 1.339 — it was never broken, the harness simply never
            # gave it the fault it claimed to have injected.
            for _attempt in range(3):
                cur.execute(
                    f"SELECT value FROM `{table}` WHERE uuid=%s "  # nosec B608
                    f"ORDER BY `datetime` DESC LIMIT 1",
                    (uid,),
                )
                _newest_val = (cur.fetchone() or [None])[0]
                if _newest_val is not None and abs(float(_newest_val) - 777.7) < 1e-6:
                    break
                cur.execute(
                    f"SELECT MAX(`datetime`) FROM `{table}` WHERE uuid=%s",  # nosec B608
                    (uid,),
                )
                _newest = cur.fetchone()[0]
                cur.execute(
                    f"UPDATE `{table}` SET value=777.7 WHERE uuid=%s "  # nosec B608
                    f"AND `datetime` > %s",
                    (uid, _newest - timedelta(hours=_span_hours)),
                )
                _pinned += cur.rowcount
            else:
                print(
                    f"  WARNING {table}: tail still not pinned after 3 attempts — "
                    "something is still writing to this sensor; the label would be false"
                )

            cur.execute(
                f"SELECT MIN(`datetime`), MAX(`datetime`) FROM `{table}` "  # nosec B608
                f"WHERE uuid=%s AND value=777.7",
                (uid,),
            )
            w_start, w_end = cur.fetchone()
            magnitude = f"pin=777.7x{_span_hours:g}h({_pinned}rows)"
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
            w_end = anchor
            w_start = anchor - timedelta(hours=6)
            cur.execute(
                f"UPDATE `{table}` SET value=value+500 WHERE uuid=%s "  # nosec B608
                f"AND `datetime` >= %s",
                (uid, w_start.strftime("%Y-%m-%d %H:%M:%S")),
            )
            magnitude = f"shift=+500x6h({cur.rowcount}rows)"
        elif kind == "gap":
            g_end = anchor - timedelta(hours=4)
            g_start = g_end - timedelta(hours=3)
            rcur.execute(
                f"DELETE FROM `{table}` WHERE uuid=%s AND `datetime` BETWEEN %s AND %s",  # nosec B608
                (uid, g_start.strftime("%Y-%m-%d %H:%M:%S"), g_end.strftime("%Y-%m-%d %H:%M:%S")),
            )
            w_start, w_end = g_start, g_end
            magnitude = f"gap=3h({rcur.rowcount}rows)"
        elif kind == "drift_offset":
            w_end = anchor
            w_start = anchor - timedelta(hours=7)
            cur.execute(
                f"UPDATE `{table}` SET value=value+300 WHERE uuid=%s "  # nosec B608
                f"AND `datetime` >= %s",
                (uid, w_start.strftime("%Y-%m-%d %H:%M:%S")),
            )
            magnitude = f"offset=+300x7h({cur.rowcount}rows)"
        # An injection that touched no rows is not ground truth. Labelling it would
        # charge the detector with missing a fault that was never there -- which is
        # exactly how bldg1's recall read 25% instead of what the detectors actually do.
        if "(0rows)" in magnitude:
            print(
                f"  SKIP {detector:<18} {table:<18} {uid[:12]}… nothing to inject "
                f"(no rows in the window ending {anchor}); NOT labelled"
            )
            continue

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
        # 300s was sized when the building had 19 live narrow points. It now has 1,528 with
        # a backfilled history behind them, and the sweep overran — killing the run AFTER
        # the injections had been written, which leaves labelled faults in the data with no
        # score against them. A timeout that fires mid-measurement corrupts the next round
        # as well as this one.
        timeout=int(os.environ.get("T22_SCAN_TIMEOUT_S", "1800")),
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


_PUBLISHER = "data-publisher"


def _pause_publisher() -> bool:
    """Stop the dev data publisher for the duration of a measurement. True when it stopped.

    Returns False when it was not running or could not be stopped, so the resume knows not
    to start something the operator had deliberately left down.
    """
    env = os.environ.copy()
    env["MSYS_NO_PATHCONV"] = "1"
    try:
        running = subprocess.run(  # nosec B603 B607
            ["docker", "ps", "--filter", f"name={_PUBLISHER}", "--format", "{{.Names}}"],
            capture_output=True,
            text=True,
            timeout=30,
            env=env,
        )
        if _PUBLISHER not in (running.stdout or ""):
            return False
        subprocess.run(  # nosec B603 B607
            ["docker", "stop", _PUBLISHER], capture_output=True, timeout=60, env=env
        )
        print(f"  paused {_PUBLISHER} so injected faults survive to be scanned")
        return True
    except Exception as exc:
        print(f"  WARNING: could not pause {_PUBLISHER} ({exc}) — tail injections may be buried")
        return False


def _resume_publisher(was_paused: bool) -> None:
    if not was_paused:
        return
    env = os.environ.copy()
    env["MSYS_NO_PATHCONV"] = "1"
    try:
        subprocess.run(  # nosec B603 B607
            ["docker", "start", _PUBLISHER], capture_output=True, timeout=60, env=env
        )
        print(f"  resumed {_PUBLISHER}")
    except Exception as exc:  # a stopped feed is worse than a noisy log
        print(f"  WARNING: {_PUBLISHER} did NOT restart ({exc}) — start it manually")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--round", type=int, required=True)
    ap.add_argument("--skip-inject", action="store_true")
    ap.add_argument("--skip-scan", action="store_true")
    args = ap.parse_args()

    env = _env()
    print(f"— T22 anomaly grader · round {args.round} · building {env.get('BUILDING_ID')} —")
    since = datetime.utcnow() - timedelta(hours=1)  # widened below from the labels

    # HOLD THE PUBLISHER STILL WHILE MEASURING.
    #
    # The dev publisher tops up every registered point every 30 seconds. A tail-shaped
    # injection — `stuck` pins the trailing window to one value — is therefore buried within
    # seconds of being written, and the detector correctly finds no constant run. Measured:
    # a 7-hour, 698-row pin scored 0/2, and the pinned sensor's newest rows were 185, 127,
    # 484 — fresh publisher values, not the pinned 777.7.
    #
    # This is an interaction the publisher fix (BUG-390) created: while only 19 points were
    # live, most injected sensors were never written over. Pausing is the honest fix; the
    # alternative is grading detectors against faults that no longer exist by the time they
    # look, which is how `stuck` came to read as a detector defect for three rounds.
    #
    # try/finally, because a run that dies mid-scan must not leave the building's data feed
    # stopped behind it.
    _paused = _pause_publisher()
    try:
        if not args.skip_inject:
            print("injecting labelled faults…")
            inject(env, args.round)
        if not args.skip_scan:
            print("running scanner sweep…")
            run_scan()
    finally:
        _resume_publisher(_paused)

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
