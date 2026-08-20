# -*- coding: utf-8 -*-
"""
clarify_off_battery.py — V4-T29 ablation arm: clarify disabled.

Runs every clarify-expected question from the seed bank against the live stack
and records what the system does instead of asking. Run it TWICE — once with
the switch off (baseline: expect asks) and once with DELIBERATE_CLARIFY_OFF=1
set in the orchestrator's environment (expect forced binds declared as
assumptions, or honest declines for unbindable asks) — then compare the CSVs.

  python -X utf8 scripts/clarify_off_battery.py --tag baseline
  # flip DELIBERATE_CLARIFY_OFF=1 in .env, restart orchestrator, then:
  python -X utf8 scripts/clarify_off_battery.py --tag clarify_off
"""

from __future__ import annotations

import argparse
import csv
import sys
import uuid
from datetime import datetime
from pathlib import Path

import requests

_SCRIPT_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _SCRIPT_DIR.parent
sys.path.insert(0, str(_REPO_ROOT))

BASE = "http://127.0.0.1:8000"
_BANK = _REPO_ROOT / "tests" / "fixtures" / "l7_bank" / "seed_questions.csv"


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


def _observed(data: dict) -> str:
    if data.get("clarification"):
        return "clarify"
    ev = data.get("evidence") or {}
    if ev.get("ranked"):
        return "answer"
    resp = (data.get("response") or "").lower()
    declines = ("can't", "cannot", "don't have", "unable", "no ", "not ", "isn't ")
    return "decline" if any(m in resp for m in declines) else "answer"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tag", required=True, help="run label, e.g. baseline / clarify_off")
    parser.add_argument("--bank", default=str(_BANK), help="questions CSV (default: seed bank)")
    args = parser.parse_args()

    rows = [
        r
        for r in csv.DictReader(open(args.bank, encoding="utf-8-sig"))
        if r.get("expected_behavior") == "clarify"
    ]
    print(f"[clarify-battery:{args.tag}] {len(rows)} clarify-expected questions")
    tok = _login()
    H = {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}

    out_rows = []
    for i, r in enumerate(rows, 1):
        q = r["Question"]
        try:
            d = requests.post(
                f"{BASE}/chat",
                headers=H,
                json={"message": q, "session_id": f"coff-{uuid.uuid4().hex[:8]}"},
                timeout=300,
            ).json()["data"]
        except Exception as exc:
            out_rows.append({"qid": r["ID"], "question": q, "observed": f"error: {exc}"})
            continue
        obs = _observed(d)
        ev = d.get("evidence") or {}
        assumptions = "; ".join(
            a.get("text", "") for a in (ev.get("assumptions") or []) if isinstance(a, dict)
        )
        forced = "clarification disabled" in assumptions
        out_rows.append(
            {
                "qid": r["ID"],
                "question": q,
                "observed": obs,
                "forced_bind_declared": forced,
                "assumptions": assumptions[:300],
                "response_head": (d.get("response") or "")[:200].replace("\n", " | "),
            }
        )
        print(
            f"  [{i}/{len(rows)}] {r['ID']}: {obs}" + (" (forced bind declared)" if forced else "")
        )

    out = (
        _SCRIPT_DIR
        / "outputs"
        / "l7"
        / f"clarify_battery_{args.tag}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(
            f,
            fieldnames=[
                "qid",
                "question",
                "observed",
                "forced_bind_declared",
                "assumptions",
                "response_head",
            ],
            lineterminator="\n",
        )
        w.writeheader()
        w.writerows(out_rows)
    counts = {}
    for r in out_rows:
        counts[r["observed"]] = counts.get(r["observed"], 0) + 1
    print(f"[clarify-battery:{args.tag}] {counts} -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
