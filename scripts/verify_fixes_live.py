"""Targeted live verification of the 2026-06-12 fixes (run after orchestrator restart).

Usage:
    python scripts/verify_fixes_live.py            # all checks
Requires the stack on 127.0.0.1:8000. Creates throwaway users.
Each check prints PASS/FAIL plus a snippet; exits non-zero on any FAIL.
"""

from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request

if hasattr(sys.stdout, "reconfigure"):  # Windows cp1252 console safety
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE = "http://127.0.0.1:8000"
PASSWORD = "Str0ngPass!2026"


def _post(path: str, body: dict, token: str = "", timeout: int = 240):
    req = urllib.request.Request(BASE + path, data=json.dumps(body).encode(), method="POST")
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


def _register_login(username: str) -> str:
    _post("/auth/register", {"username": username, "password": PASSWORD})
    s, b = _post("/auth/login", {"username": username, "password": PASSWORD})
    assert s == 200, f"login failed for {username}: {b[:200]}"
    return json.loads(b)["data"]["session_token"]


def _chat(token: str, message: str, session: str) -> tuple[int, str]:
    s, b = _post("/chat", {"message": message, "session_id": session}, token=token)
    if s != 200:
        return s, b
    return s, (json.loads(b).get("data") or {}).get("response", "")


def main() -> int:
    ts = int(time.time())
    fm_token = _register_login(f"vfix_fm_{ts}")  # default role: facility_manager
    results: list[tuple[str, bool, str]] = []

    def check(name: str, ok: bool, snippet: str) -> None:
        results.append((name, ok, snippet))
        print(f"[{'PASS' if ok else 'FAIL'}] {name}\n       {snippet[:160]}\n")

    # 1. Data question must hit the data pipeline (not capability KB)
    s, ans = _chat(fm_token, "What is the latest CO2 in room 5.01?", f"vfix-{ts}-1")
    check(
        "data question → pipeline value (not building-info hijack)",
        s == 200
        and ("ppm" in ans.lower() or any(c.isdigit() for c in ans))
        and "smart building" not in ans.lower(),
        ans,
    )

    # 2. Control as facility_manager → pending approval (T25 first half)
    s, ans = _chat(fm_token, "Set the setpoint of room 5.01 to 22 degrees", f"vfix-{ts}-2")
    ok_pending = s == 200 and ("approval" in ans.lower() or "approve" in ans.lower())
    check("control as facility_manager → pending approval", ok_pending, ans)

    # 3. Approve round-trip (T25 second half) — extract id and approve it
    if ok_pending:
        import re

        m = re.search(r"\b([a-f0-9]{6,8})\b", ans)
        if m:
            s, ans2 = _chat(fm_token, f"approve {m.group(1)}", f"vfix-{ts}-2")
            check(
                "approve <id> executes via sim driver",
                s == 200 and ("executed" in ans2.lower() or "audit" in ans2.lower()),
                ans2,
            )
        else:
            check("approve <id> executes via sim driver", False, "no approval id in reply")
    else:
        check("approve <id> executes via sim driver", False, "skipped — no pending approval")

    # 4. Alert intent routes to alert management (not the data pipeline)
    s, ans = _chat(fm_token, "list my alerts", f"vfix-{ts}-3")
    check(
        "alert intent → alert management node",
        s == 200
        and "power sensor" not in ans.lower()
        and ("alert" in ans.lower() or "no rules" in ans.lower() or "none" in ans.lower()),
        ans,
    )

    # 5. Preference store round-trip (T35)
    s, ans = _chat(
        fm_token, "Remember that I prefer temperatures between 22 and 24 degrees", f"vfix-{ts}-4"
    )
    check(
        "preference storage accepted for authenticated user",
        s == 200 and ("22" in ans or "preference" in ans.lower() or "remember" in ans.lower()),
        ans,
    )

    # 6. Automation-capability question → honest answer, not control decline
    s, ans = _chat(
        fm_token,
        "Can the building automatically close the blinds when it gets sunny?",
        f"vfix-{ts}-5",
    )
    check(
        "automation-capability question → honest T22 answer",
        s == 200
        and "don't have permission" not in ans.lower()
        and "couldn't generate" not in ans.lower(),
        ans,
    )

    # 7. Interventional what-if → estimate path (no forecast deflection)
    s, ans = _chat(
        fm_token,
        "What would happen to energy use if we lowered the heating setpoint by 2 degrees?",
        f"vfix-{ts}-6",
    )
    check(
        "interventional what-if answered with estimate",
        s == 200 and ("%" in ans or "percent" in ans.lower() or "estimate" in ans.lower()),
        ans,
    )

    failed = [n for n, ok, _ in results if not ok]
    print("=" * 60)
    print(f"{len(results) - len(failed)}/{len(results)} live checks passed")
    if failed:
        print("FAILED:", ", ".join(failed))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
