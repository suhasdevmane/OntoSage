# -*- coding: utf-8 -*-
"""
demo_rehearsal.py — V4-T35: execute the 10-minute demo script end-to-end.

Runs the API side of every demo beat against the ACTIVE building and asserts
the expected behavior for each. Exit code 0 = the whole script ran without
intervention. Run twice for the T35 acceptance.

  python -X utf8 scripts/demo_rehearsal.py
"""

from __future__ import annotations

import sys
import time
import uuid
from pathlib import Path

import requests

_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT))

from orchestrator.services.deliberation.live import active_identity  # noqa: E402

BASE = "http://127.0.0.1:8000"


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


def _chat(H, session, message):
    t0 = time.monotonic()
    d = requests.post(
        f"{BASE}/chat",
        headers=H,
        json={"message": message, "session_id": session},
        timeout=300,
    ).json()["data"]
    return d, round(time.monotonic() - t0, 1)


def _flush_cache() -> None:
    """Best-effort resp_cache flush — stale cached answers are the #1 demo killer."""
    import subprocess

    try:
        subprocess.run(
            [
                "docker",
                "exec",
                "redis-memory-store",
                "sh",
                "-c",
                'redis-cli --scan --pattern "resp_cache:*" | xargs -r redis-cli DEL; '
                'redis-cli --scan --pattern "cache:intent:*" | xargs -r redis-cli DEL',
            ],
            capture_output=True,
            timeout=30,
        )
        print("[rehearsal] resp_cache flushed")
    except Exception as exc:
        print(f"[rehearsal] cache flush skipped ({exc}) — cached beats may lack fresh traces")


def main() -> int:
    bid = active_identity()["BUILDING_ID"]
    print(f"[rehearsal] building={bid}")
    _flush_cache()
    tok = _login()
    H = {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}
    failures = []

    def beat(name, ok, detail):
        mark = "PASS" if ok else "FAIL"
        print(f"  [{mark}] {name}: {detail}")
        if not ok:
            failures.append(name)

    # Beat 1 — flagship multi-constraint question with dossier + plan trace
    d, secs = _chat(
        H,
        f"demo1-{uuid.uuid4().hex[:8]}",
        "I'm visiting tomorrow - where can I sit that's quiet, with good air, "
        "near drinking water?",
    )
    ev = d.get("evidence") or {}
    pt = d.get("plan_trace") or {}
    beat(
        "flagship ranked+dossier",
        bool(ev.get("ranked")) and pt.get("kind") == "deliberative" and bool(pt.get("plan_hash")),
        f"{secs}s, top1={(ev.get('ranked') or [{}])[0].get('space', '?')}, "
        f"trace={pt.get('kind')}/{(pt.get('plan_hash') or '')[:8]}",
    )

    # Beat 2 — clarify -> resume round-trip in ONE session.
    # A nonexistent floor triggers the SCHEMA-validation clarify (floor slot,
    # concrete options) deterministically — no LLM-compile variance, unlike
    # vague phrasings ("upstairs") which can wobble into a signals-ask.
    session = f"demo2-{uuid.uuid4().hex[:8]}"
    d, secs = _chat(H, session, "Which room on floor 99 is the quietest right now?")
    clar = d.get("clarification") or {}
    beat(
        "clarify asks with options",
        bool(clar.get("options")),
        f"{secs}s, slot={clar.get('slot')}, options={len(clar.get('options') or [])}",
    )
    if clar.get("options"):
        d2, secs2 = _chat(H, session, "1")
        ev2 = d2.get("evidence") or {}
        beat(
            "resume after option-1 reply",
            bool(ev2.get("ranked")),
            f"{secs2}s, top1={(ev2.get('ranked') or [{}])[0].get('space', '?')}",
        )
    else:
        beat("resume after option-1 reply", False, "skipped: no options to bind")

    # Beat 3 — honest decline names sensed modalities, never fabricates
    d, secs = _chat(
        H, f"demo3-{uuid.uuid4().hex[:8]}", "Which room has the lowest radiation right now?"
    )
    resp = (d.get("response") or "").lower()
    beat(
        "honest decline (radiation)",
        not (d.get("evidence") or {}).get("ranked")
        and ("sense" in resp or "isn't" in resp or "not" in resp),
        f"{secs}s, head='{resp[:60]}'",
    )

    # Beat 4 — reflex answer carries a reflex plan trace (brain routes everything)
    d, secs = _chat(H, f"demo4-{uuid.uuid4().hex[:8]}", "How many rooms are on floor 2?")
    pt = d.get("plan_trace") or {}
    beat(
        "reflex plan trace",
        pt.get("kind") == "reflex" and bool(pt.get("steps")),
        f"{secs}s, steps={pt.get('steps')}",
    )

    # Beat 5 — superlative ranking with simulated-flag disclosure in the dossier
    d, secs = _chat(
        H, f"demo5-{uuid.uuid4().hex[:8]}", "Which room on floor 2 is the quietest right now?"
    )
    ev = d.get("evidence") or {}
    cells = ev.get("evidence") or []
    flagged = any(c.get("simulated") is not None for c in cells)
    beat(
        "superlative + provenance flags",
        bool(ev.get("ranked")) and flagged,
        f"{secs}s, evidence rows={len(cells)}, simulated flags present={flagged}",
    )

    print(f"\n[rehearsal] {'ALL BEATS PASS' if not failures else 'FAILED: ' + ', '.join(failures)}")
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
