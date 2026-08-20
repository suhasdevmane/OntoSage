# -*- coding: utf-8 -*-
"""
competitor_classes_run.py — V4-T34: run the competitor question classes live.

Three classes, modeled on the related-work systems' capability envelopes:
  static_brick             BuildingGPT2-style: ontology-only QA
  single_system_analytics  JARVIS-style: one-system time-series analytics
  arbiter_only             classes NO competitor expresses: multi-space
                           constraint ranking, forecast-conditioned selection,
                           amenity-anchored choice

Records per question: routed intent, observed behavior, evidence presence,
response head — the raw material for the T34 comparison table.

  python -X utf8 scripts/competitor_classes_run.py            # active building
"""

from __future__ import annotations

import csv
import sys
import uuid
from datetime import datetime
from pathlib import Path

import requests

_SCRIPT_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _SCRIPT_DIR.parent
sys.path.insert(0, str(_REPO_ROOT))

from orchestrator.services.deliberation.live import active_identity  # noqa: E402

BASE = "http://127.0.0.1:8000"
_BANK = _REPO_ROOT / "tests" / "fixtures" / "l7_bank" / "competitor_classes.csv"


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
        return "answer_with_dossier"
    resp = (data.get("response") or "").lower()
    declines = ("can't", "cannot", "don't have", "unable", "no data", "isn't ", "not available")
    if any(m in resp for m in declines) and len(resp) < 400:
        return "decline"
    return "answer"


def main() -> int:
    bid = active_identity()["BUILDING_ID"]
    rows = list(csv.DictReader(open(_BANK, encoding="utf-8-sig")))
    print(f"[competitor-classes] {len(rows)} questions on {bid}")
    tok = _login()
    H = {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}

    out_rows = []
    for i, r in enumerate(rows, 1):
        q = r["Question"]
        try:
            d = requests.post(
                f"{BASE}/chat",
                headers=H,
                json={"message": q, "session_id": f"cc-{uuid.uuid4().hex[:8]}"},
                timeout=300,
            ).json()["data"]
        except Exception as exc:
            out_rows.append(
                {
                    "qid": r["ID"],
                    "class": r["question_class"],
                    "question": q,
                    "intent": "",
                    "observed": f"error: {str(exc)[:80]}",
                    "response_head": "",
                }
            )
            continue
        obs = _observed(d)
        out_rows.append(
            {
                "qid": r["ID"],
                "class": r["question_class"],
                "question": q,
                "intent": d.get("intent", ""),
                "observed": obs,
                "response_head": (d.get("response") or "")[:220].replace("\n", " | "),
            }
        )
        print(
            f"  [{i}/{len(rows)}] {r['ID']} [{r['question_class']}]: "
            f"intent={d.get('intent')} -> {obs}"
        )

    out = (
        _SCRIPT_DIR
        / "outputs"
        / "l7"
        / f"competitor_classes_{bid}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(
            f,
            fieldnames=["qid", "class", "question", "intent", "observed", "response_head"],
            lineterminator="\n",
        )
        w.writeheader()
        w.writerows(out_rows)

    print(f"\n[competitor-classes] per-class outcome on {bid}:")
    for cls in ("static_brick", "single_system_analytics", "arbiter_only"):
        sub = [r for r in out_rows if r["class"] == cls]
        ok = sum(1 for r in sub if r["observed"].startswith("answer"))
        print(f"  {cls:26s} answered {ok}/{len(sub)}")
    print(f"[competitor-classes] -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
