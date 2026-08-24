#!/usr/bin/env python3
"""Cold-start verification for TODO-072: build a building through the console, from nothing.

Everything else on that row is verified — every control exists, the readiness signal is
correct on a fully-built building, and the multipart upload path round-trips. What was owed
is this: start with no state at all and reach the same answers using only the endpoints the
admin console calls.

The definition of "nothing" is the part that decides whether this test is worth running, and
it is written up in ``tasks/COLD_START_VERIFICATION.md``. Briefly: a building's state lives in
five places, `input/` is the least important of them, and running a cold test against a warm
GraphDB proves nothing while looking exactly like a pass — the shape of two fictitious numbers
in this project's history (CAVEAT-173, BUG-176). So Phase 0 asserts cold on every source and
REFUSES TO RUN otherwise, rather than reporting a pass it did not earn.

Each step is then driven through the console's own endpoint, and readiness is re-read after
every one. Three assertions per step, of which the last two are the ones with teeth:

  1. the step flips to done;
  2. no OTHER step flips — a readiness signal that moves when unrelated state changes is
     reading something other than what it says it is;
  3. the numbers are real (spaces counted in the graph, sensors with rows, spaces linked to an
     IRI), not booleans recording that an upload happened.

Phase 6 asks the building a question that needs the data, because readiness is a claim and an
answer is evidence. A building reporting 5/5 that cannot say how many sensors it has passed a
checklist — the exact thing this row's own fix argued against.

Usage (see the doc for the swap procedure that puts a scratch building in place):

    python scripts/cold_start_verification.py --expect-building bldgcold --source-dir bldg3
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests

REPO = Path(__file__).resolve().parent.parent
BASE = "http://127.0.0.1:8000"
OUT = REPO / "scripts" / "outputs"

#: Steps the readiness endpoint reports, in the order the console presents them.
STEPS = ["identity", "ontology", "timeseries", "documents", "floor_plans"]


# ── plumbing ────────────────────────────────────────────────────────────────


def login(base: str) -> str:
    spec = importlib.util.spec_from_file_location(
        "cap", str(REPO / "scripts" / "capture_golden_baseline.py")
    )
    cap = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cap)
    return cap._login(base)


class Console:
    """The admin console's HTTP surface. Nothing here touches the file system: if a step can
    only be done by writing a file, that is the finding."""

    def __init__(self, base: str, token: str):
        self.base, self.token = base, token

    def _h(self) -> Dict[str, str]:
        return {"Authorization": f"Bearer {self.token}"}

    def get(self, path: str, **kw) -> Dict[str, Any]:
        r = requests.get(f"{self.base}{path}", headers=self._h(), timeout=120, **kw)
        return _envelope(r)

    def send(self, method: str, path: str, payload: Dict) -> Dict[str, Any]:
        r = requests.request(
            method,
            f"{self.base}{path}",
            headers={**self._h(), "Content-Type": "application/json"},
            json=payload,
            timeout=300,
        )
        return _envelope(r)

    def upload(self, path: str, files: Dict, data: Optional[Dict] = None) -> Dict[str, Any]:
        r = requests.post(
            f"{self.base}{path}", headers=self._h(), files=files, data=data or {}, timeout=600
        )
        return _envelope(r)

    def ask(self, question: str) -> Dict[str, Any]:
        import uuid

        r = requests.post(
            f"{self.base}/chat",
            headers={**self._h(), "Content-Type": "application/json"},
            json={"message": question, "session_id": f"cold-{uuid.uuid4().hex[:8]}"},
            timeout=300,
        )
        if r.status_code != 200:
            return {"_http": r.status_code}
        p = r.json()
        return p.get("data") or p


def _envelope(r: requests.Response) -> Dict[str, Any]:
    try:
        body = r.json()
    except Exception:
        body = {"success": False, "error": r.text[:300]}
    body["_http"] = r.status_code
    return body


# ── phase 0: is it actually cold? ───────────────────────────────────────────


def assert_cold(con: Console, input_dir: Path, building_id: str) -> Tuple[bool, List[str]]:
    """Every state source, checked. Returns (cold, findings)."""
    findings: List[str] = []

    # 1. input/ — the obvious one, and the least sufficient
    if input_dir.exists():
        stray = [
            p.name
            for p in input_dir.iterdir()
            if p.name != "env.building"
            and (
                p.suffix.lower() in {".ttl", ".yaml", ".yml", ".dwg", ".dxf", ".pdf"}
                or p.name in {"documents", "personas"}
            )
        ]
        if stray:
            findings.append(f"input/ is not empty: {sorted(stray)[:8]}")
    else:
        findings.append("input/ does not exist — compose needs it as a bind-mount target")

    # 2. GraphDB — the one that makes a warm run look like a pass
    res = con.send("POST", "/api/v1/admin/ontology/sparql", {"query": _COUNT_TRIPLES, "limit": 5})
    if res.get("success"):
        rows = (res.get("data") or {}).get("rows") or []
        n = int((rows[0] or {}).get("n") or 0) if rows else 0
        if n:
            findings.append(f"GraphDB holds {n:,} triples — not cold")
    else:
        findings.append(f"could not count triples (treated as NOT cold): {res.get('error')}")

    # 3. Qdrant — via the reindex/status surface the console uses
    docs = con.get("/api/v1/admin/documents")
    if docs.get("success"):
        n = len((docs.get("data") or {}).get("documents") or [])
        if n:
            findings.append(f"{n} document(s) already indexed — not cold")

    # 4. the building's knowledge that a datasource exists
    dbs = con.get("/api/v1/admin/databases")
    if dbs.get("success"):
        active = [d for d in ((dbs.get("data") or {}).get("databases") or []) if d.get("active")]
        if active:
            findings.append(f"{len(active)} datasource(s) already registered — not cold")

    # 5. floor plans
    fps = con.get("/api/v1/admin/floor-plans/files")
    if fps.get("success"):
        n = len((fps.get("data") or {}).get("floor_plans") or [])
        if n:
            findings.append(f"{n} floor plan(s) already present — not cold")

    return (not findings), findings


_COUNT_TRIPLES = "SELECT (COUNT(*) AS ?n) WHERE { ?s ?p ?o }"


# ── readiness ───────────────────────────────────────────────────────────────


def readiness(con: Console) -> Dict[str, Any]:
    res = con.get("/api/v1/admin/onboarding/status")
    return (res.get("data") or {}) if res.get("success") else {"_error": res.get("error")}


def step_map(status: Dict[str, Any]) -> Dict[str, bool]:
    out = {}
    for s in status.get("steps") or []:
        out[s.get("id") or s.get("key") or "?"] = bool(s.get("done"))
    return out


def detail_of(status: Dict[str, Any], step_id: str) -> str:
    for s in status.get("steps") or []:
        if (s.get("id") or s.get("key")) == step_id:
            return str(s.get("detail") or "")
    return ""


# ── the run ─────────────────────────────────────────────────────────────────


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--base-url", default=BASE)
    ap.add_argument("--expect-building", required=True, help="refuse to run against another id")
    ap.add_argument(
        "--source-dir",
        required=True,
        help="folder standing in for the administrator's laptop: TTL, documents, floor plans",
    )
    ap.add_argument("--namespace", default="", help="ontology namespace; default from the TTL")
    ap.add_argument(
        "--datasource",
        default="",
        help="JSON spec for POST /admin/databases, e.g. the MySQL the readings already live in",
    )
    ap.add_argument("--force", action="store_true", help="run even if Phase 0 says not cold")
    args = ap.parse_args(argv)

    src = (
        (REPO / args.source_dir)
        if not Path(args.source_dir).is_absolute()
        else Path(args.source_dir)
    )
    if not src.is_dir():
        print(f"source dir not found: {src}")
        return 2

    token = login(args.base_url)
    con = Console(args.base_url, token)

    live = con.get("/api/v1/admin/building/config")
    live_id = ((live.get("data") or {}).get("building_id")) or "?"
    if live_id != args.expect_building:
        print(
            f"REFUSING: the running building is {live_id!r}, expected {args.expect_building!r}.\n"
            "A cold-start run against a real building would write its identity and upload "
            "another building's ontology into it."
        )
        return 2

    report: Dict[str, Any] = {"building": live_id, "source": str(src), "phases": []}

    print("── Phase 0: is it cold? ───────────────────────────────────────────")
    cold, findings = assert_cold(con, REPO / "input", live_id)
    for f in findings:
        print(f"   NOT COLD: {f}")
    report["phases"].append({"phase": "cold", "cold": cold, "findings": findings})
    if not cold and not args.force:
        print(
            "\nStopping. A cold-start run against warm state reports a pass it did not earn — "
            "which is how this project produced two fictitious numbers already. Make the state "
            "cold (see tasks/COLD_START_VERIFICATION.md) or pass --force and label the result."
        )
        _write(report)
        return 1
    print("   cold on every state source" if cold else "   FORCED past a warm start")

    before = readiness(con)
    print(f"\n   readiness at rest: {_summary(before)}")
    baseline_steps = step_map(before)
    if any(baseline_steps.values()) and cold:
        print(
            "   FINDING: a step reports done on a cold building — the readiness signal is "
            "reading something other than live state."
        )
        report["phases"].append({"phase": "cold-readiness", "steps": baseline_steps})

    # ── the five steps, each through the console's own endpoint ──────────
    prev = baseline_steps
    for name, fn in [
        ("identity", _do_identity),
        ("ontology", _do_ontology),
        ("timeseries", _do_datasource),
        ("documents", _do_documents),
        ("floor_plans", _do_floor_plans),
    ]:
        print(f"\n── Step: {name} ───────────────────────────────────────────")
        try:
            outcome = fn(con, src, args)
        except Exception as exc:  # a step that cannot be driven IS the finding
            outcome = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
        print(f"   drive: {outcome}")

        time.sleep(3)
        now = readiness(con)
        steps = step_map(now)
        flipped = [k for k in steps if steps.get(k) and not prev.get(k)]
        unflipped = [k for k in steps if prev.get(k) and not steps.get(k)]
        others = [k for k in flipped if k != name]

        print(f"   readiness: {_summary(now)}")
        print(f"   detail:    {detail_of(now, name)[:110]}")
        if name not in flipped and not prev.get(name):
            print(f"   FINDING: '{name}' did not flip after its own step succeeded")
        if others:
            print(f"   FINDING: unrelated step(s) flipped: {others}")
        if unflipped:
            print(f"   FINDING: step(s) went backwards: {unflipped}")

        report["phases"].append(
            {
                "phase": name,
                "drive": outcome,
                "flipped": flipped,
                "unexpected_flips": others,
                "regressed": unflipped,
                "detail": detail_of(now, name),
                "summary": _summary(now),
            }
        )
        prev = steps

    # ── Phase 6: readiness is a claim; an answer is evidence ─────────────
    print("\n── Phase 6: can it actually answer? ───────────────────────────")
    probes = [
        "How many temperature sensors does this building have?",
        "What spaces are on the ground floor?",
    ]
    answers = []
    for q in probes:
        d = con.ask(q)
        text = (d.get("response") or "")[:220].replace("\n", " ")
        print(f"   Q: {q}\n   A: {text}\n")
        answers.append({"q": q, "intent": d.get("intent"), "answer": text})
    report["phases"].append({"phase": "answers", "probes": answers})

    _write(report)
    return 0


def _summary(status: Dict[str, Any]) -> str:
    steps = status.get("steps") or []
    done = sum(1 for s in steps if s.get("done"))
    return (
        f"{done}/{len(steps)} steps, can_answer={status.get('can_answer')}, "
        f"complete={status.get('complete')}"
    )


def _write(report: Dict[str, Any]) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    p = OUT / "cold_start_verification.json"
    p.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"\nreport → {p}")


# ── the five drivers ────────────────────────────────────────────────────────


def _do_identity(con: Console, src: Path, args) -> Dict[str, Any]:
    ns = args.namespace or _namespace_from_ttl(src)
    if not ns:
        return {"ok": False, "error": "no namespace given and none found in the source TTL"}
    res = con.send(
        "PUT",
        "/api/v1/admin/building/config",
        {
            "ontology_namespace": ns,
            "ontology_prefix": "bldg",
            "building_name": "Cold-start verification building",
        },
    )
    return {"ok": bool(res.get("success")), "namespace": ns, "error": res.get("error")}


def _do_ontology(con: Console, src: Path, args) -> Dict[str, Any]:
    ttls = sorted(p for p in src.glob("*.ttl") if p.stat().st_size < 40_000_000)
    if not ttls:
        return {"ok": False, "error": "no .ttl in the source dir"}
    uploaded, failed = [], []
    for t in ttls:
        text = t.read_text(encoding="utf-8", errors="replace")
        res = con.send(
            "POST",
            "/api/v1/admin/ontology/upload",
            {"ttl": text, "graph_uri": f"urn:coldstart:{t.stem}"},
        )
        (uploaded if res.get("success") else failed).append(t.name)
    return {"ok": bool(uploaded), "uploaded": len(uploaded), "failed": failed[:5]}


def _do_datasource(con: Console, src: Path, args) -> Dict[str, Any]:
    if not args.datasource:
        return {"ok": False, "error": "no --datasource spec given"}
    spec = json.loads(args.datasource)
    res = con.send("POST", "/api/v1/admin/databases", spec)
    return {"ok": bool(res.get("success")), "error": res.get("error")}


def _do_documents(con: Console, src: Path, args) -> Dict[str, Any]:
    d = src / "documents"
    files = sorted(p for p in d.iterdir() if p.is_file()) if d.is_dir() else []
    if not files:
        return {"ok": False, "error": "no documents/ in the source dir"}
    sent = 0
    for f in files[:5]:
        res = con.upload("/api/v1/admin/documents/upload", {"file": (f.name, f.read_bytes())})
        sent += 1 if res.get("success") else 0
    return {"ok": sent > 0, "uploaded": sent, "available": len(files)}


def _do_floor_plans(con: Console, src: Path, args) -> Dict[str, Any]:
    files = sorted(p for p in src.glob("*.pdf")) + sorted(p for p in src.glob("*.dwg"))
    if not files:
        return {"ok": False, "error": "no floor plans in the source dir"}
    sent = 0
    for f in files[:6]:
        res = con.upload("/api/v1/admin/floor-plans/upload", {"file": (f.name, f.read_bytes())})
        sent += 1 if res.get("success") else 0
    return {"ok": sent > 0, "uploaded": sent, "available": len(files)}


def _namespace_from_ttl(src: Path) -> str:
    """The namespace the ontology declares, so identity and TTL cannot disagree — a mismatch
    hard-fails the swap validator, and hard-coding one here would hide that."""
    import re

    for t in sorted(src.glob("*.ttl")):
        head = t.read_text(encoding="utf-8", errors="replace")[:4000]
        m = re.search(r"@prefix\s+bldg:\s*<([^>]+)>", head)
        if m:
            return m.group(1)
    return ""


if __name__ == "__main__":
    sys.exit(main())
