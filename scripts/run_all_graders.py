# -*- coding: utf-8 -*-
"""V5-T30 — one harness, all strata: run every grader and compile ONE scorecard.

Runs (each independently skippable, each already self-contained):

  coverage   scripts/corpus_replay.py          question bank → data-backed %
  privacy    scripts/leak_benchmark.py         39 policy traps → leak rate
  detect     scripts/grade_anomalies.py        injected faults → recall/precision
  predict    scripts/grade_forecasts.py        time-travel fits → MAE + CI coverage

and compiles ``scripts/outputs/V5_SCORECARD_<building>_<ts>.md`` — the single
artifact the certification legs (T33–T36) attach per building.

Reads each grader's OWN output artifact rather than parsing stdout, so a
grader can be run by hand and this still summarises it (``--skip-run`` uses
the newest existing artifacts).

Usage:
  python scripts/run_all_graders.py                       # everything
  python scripts/run_all_graders.py --only detect,predict
  python scripts/run_all_graders.py --skip-run            # compile only
  python scripts/run_all_graders.py --quick               # small samples

Building-agnostic: identity from .env; every grader is already per-building.
"""

from __future__ import annotations

import argparse
import csv
import json
import subprocess  # nosec B404 — runs sibling scripts in this repo only
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


def _safe_print(*parts: object) -> None:
    """print(), but survives a console that cannot encode the glyph we chose.

    A Windows cp1252 console raises UnicodeEncodeError on the box-drawing and
    arrow characters used for progress headers, and that traceback killed this
    harness before it ran a single grader (BUG-186). Degrade the glyph, never the
    run. Takes *parts so it is a drop-in for every existing print() call site,
    including the multi-argument ones.
    """
    text = " ".join(str(p) for p in parts)
    try:
        print(text, flush=True)
    except UnicodeEncodeError:
        enc = sys.stdout.encoding or "ascii"
        print(text.encode(enc, errors="replace").decode(enc, errors="replace"), flush=True)


_REPO = Path(__file__).resolve().parents[1]
OUT = _REPO / "scripts" / "outputs"
STRATA = ("coverage", "privacy", "detect", "predict")


def _env() -> dict:
    env = {}
    env_path = _REPO / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            s = line.strip()
            if s and not s.startswith("#") and "=" in s:
                k, v = s.split("=", 1)
                env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def _newest(pattern: str) -> Optional[Path]:
    hits = sorted(OUT.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)
    return hits[0] if hits else None


def _run(cmd: List[str], label: str, timeout: int = 5400) -> bool:
    _safe_print(f"\n▶ {label}: {' '.join(cmd[1:])}")
    try:
        r = subprocess.run(  # nosec B603 — fixed argv, repo-local scripts
            cmd, cwd=str(_REPO), capture_output=True, text=True, timeout=timeout
        )
    except subprocess.TimeoutExpired:
        _safe_print(f"  TIMEOUT after {timeout}s — artifact may be partial")
        return False
    tail = [ln for ln in (r.stdout or "").splitlines() if ln.strip()][-3:]
    for ln in tail:
        _safe_print("   ", ln[:150])
    if r.returncode != 0:
        _safe_print(f"  (exit {r.returncode} — recorded, not fatal)")
    return r.returncode == 0


# ── per-stratum summarisers (read artifacts, never stdout) ───────────────────


#: a coverage headline below this many questions is a smoke run, not a measurement
MIN_CERTIFICATION_QUESTIONS = 100


def _coverage_artifacts() -> List[Path]:
    """Newest-first, but a CERTIFICATION-SIZED run outranks a fresher smoke run."""
    hits = list((OUT / "replay").glob("*_summary.csv")) + list(
        (OUT / "replay").glob("replay_*.csv")
    )
    return sorted(hits, key=lambda p: p.stat().st_mtime, reverse=True)


def summarise_coverage() -> Dict[str, Any]:
    candidates = _coverage_artifacts()
    if not candidates:
        return {"status": "no artifact", "detail": "run corpus_replay.py"}
    # prefer the newest run that is big enough to certify; fall back to newest
    latest = None
    for path in candidates:
        try:
            n = sum(1 for _ in csv.DictReader(open(path, encoding="utf-8")))
        except OSError:
            continue
        agg_hint = n >= MIN_CERTIFICATION_QUESTIONS
        if agg_hint:
            latest = path
            break
    smoke_only = latest is None
    latest = latest or candidates[0]
    from datetime import datetime as _dt

    measured_at = _dt.fromtimestamp(latest.stat().st_mtime).strftime("%Y-%m-%d")
    rows = list(csv.DictReader(open(latest, encoding="utf-8")))
    if rows and "grade" in rows[0]:
        # A turn the LLM never answered is not a coverage failure — corpus_replay
        # excludes those from its own aggregate (BUG-176), and this summariser must
        # agree or the scorecard reports a different number than the replay report.
        invalid = sum(1 for r in rows if r.get("grade") == "invalid-no-response")
        graded = [r for r in rows if r.get("grade") != "invalid-no-response"]
        total = len(graded)
        backed = sum(1 for r in graded if r.get("grade") == "answered-with-data")
        honest = sum(1 for r in graded if "honest" in str(r.get("grade", "")))
        return {
            "status": "smoke-sample (NOT certification grade)" if smoke_only else "ok",
            "artifact": latest.name,
            "measured_at": measured_at,
            "questions": total,
            "quarantined_no_response": invalid,
            "data_backed_pct": round(100 * backed / total, 1) if total else 0.0,
            "honest_decline_pct": round(100 * honest / total, 1) if total else 0.0,
            "combined_pct": round(100 * (backed + honest) / total, 1) if total else 0.0,
        }
    total = len(rows)
    agg = next((r for r in rows if r.get("level") == "ALL"), None)
    if agg:
        tot = int(agg.get("total") or 0)
        db = int(agg.get("data_backed") or 0)
        return {
            "status": (
                "smoke-sample (NOT certification grade)"
                if (smoke_only or tot < MIN_CERTIFICATION_QUESTIONS)
                else "ok"
            ),
            "artifact": latest.name,
            "measured_at": measured_at,
            "questions": tot,
            "data_backed_pct": round(100 * db / tot, 1) if tot else 0.0,
        }
    return {"status": "unparsed", "artifact": latest.name}


#: the leak benchmark's full trap bank; a --ids subset must never headline
MIN_LEAK_TRAPS = 39


def live_enforcement_mode() -> str:
    """Ask the CONTAINER what PDP mode is actually live (CAVEAT-182).

    `leak_benchmark --arm construction` names the enforced arm but only WARNS if
    .env disagrees, so a scorecard could label a shadow-mode run "construction" —
    and a shadow-mode leak count is not a privacy result at all, because the PDP
    logs without blocking. Read it from the running container rather than trusting
    a file or a flag.
    """
    try:
        out = subprocess.run(  # nosec B603 B607 — fixed local command
            [
                "docker",
                "exec",
                "ontosage-orchestrator",
                "python",
                "-c",
                "from orchestrator.services.privacy.enforcement import enforcement_mode as e;"
                "print('PDP=' + e())",
            ],
            capture_output=True,
            text=True,
            timeout=120,
        )
        for line in reversed((out.stdout or "").splitlines()):
            if line.startswith("PDP="):
                return line.split("=", 1)[1].strip()
    except Exception:
        pass
    return "unknown"


def summarise_privacy() -> Dict[str, Any]:
    # newest FULL-bank run wins: targeted --ids re-probes (e.g. 4 traps) are
    # debugging artifacts and would otherwise headline a 100% pass rate
    candidates = sorted(
        OUT.glob("v5_t42_leak_*.csv"), key=lambda p: p.stat().st_mtime, reverse=True
    )
    latest = None
    for path in candidates:
        try:
            n = sum(1 for _ in csv.DictReader(open(path, encoding="utf-8")))
        except OSError:
            continue
        if n >= MIN_LEAK_TRAPS:
            latest = path
            break
    if latest is None:
        if not candidates:
            return {"status": "no artifact", "detail": "run leak_benchmark.py"}
        latest = candidates[0]
    rows = list(csv.DictReader(open(latest, encoding="utf-8")))
    counts: Dict[str, int] = {}
    for r in rows:
        counts[r["verdict"]] = counts.get(r["verdict"], 0) + 1
    invalid = counts.get("INVALID_NO_RESPONSE", 0)
    # A trap naming a space THIS building does not have is not applicable here
    # (CAVEAT-190), so it must not sit in the denominator — the same rule COVERAGE
    # applies to quarantined turns. Reporting 1/39 where only 37 traps could be
    # asked understates every rate on this row.
    not_applicable = counts.get("NA_REFERENT_ABSENT", 0)
    n = (len(rows) - not_applicable) or 1
    arm = rows[0].get("arm", "?") if rows else "?"
    # Prefer the mode the RUN recorded. Reading it live here reports whatever is
    # live at COMPILE time, which mislabelled an enforced run as shadow after the
    # driver switched modes for a later leg (CAVEAT-182 follow-on). Fall back to
    # the live probe only for artifacts written before pdp_mode existed.
    pdp = (rows[0].get("pdp_mode") or "").strip() if rows else ""
    if not pdp:
        pdp = live_enforcement_mode()
    # A "construction" arm measured while the PDP was only shadowing is not a
    # privacy result — it measures the honesty guards alone. Say so instead of
    # publishing a leak rate that reads as a certification (CAVEAT-182).
    mislabelled = arm == "construction" and pdp not in ("on", "unknown")
    if invalid:
        status = f"{invalid} trap(s) got no response — NOT certification grade"
    elif mislabelled:
        status = (
            f"arm=construction but the live PDP is '{pdp}' — the PDP did not block, "
            "so this is NOT certification grade"
        )
    elif len(rows) >= MIN_LEAK_TRAPS:
        status = "ok"
    else:
        status = "partial subset (NOT certification grade)"
    return {
        "status": status,
        "invalid_no_response": invalid,
        "artifact": latest.name,
        "traps": len(rows),
        "leak_pct": round(100 * counts.get("LEAK", 0) / n, 1),
        "pass_pct": round(100 * counts.get("PASS", 0) / n, 1),
        "wrongful_denial_pct": round(100 * counts.get("WRONGFUL_DENIAL", 0) / n, 1),
        "arm": arm,
        "pdp_mode": pdp,
        "not_applicable": not_applicable,
        "applicable_traps": n,
    }


def summarise_detect() -> Dict[str, Any]:
    cards = sorted(OUT.glob("v5_t22_scorecard_r*.csv"), key=lambda p: p.stat().st_mtime)[-3:]
    if not cards:
        return {"status": "no artifact", "detail": "run grade_anomalies.py"}
    inj = det = 0
    per: Dict[str, List[float]] = {}
    for c in cards:
        for r in csv.DictReader(open(c, encoding="utf-8")):
            inj += int(r["injected"])
            det += int(r["detected"])
            per.setdefault(r["detector"], []).append(float(r["recall"]))
    return {
        "status": "ok",
        "rounds": len(cards),
        "injected": inj,
        "detected": det,
        "recall_pct": round(100 * det / inj, 1) if inj else 0.0,
        "per_detector_recall": {k: round(sum(v) / len(v), 2) for k, v in sorted(per.items())},
    }


def summarise_predict(building: str) -> Dict[str, Any]:
    reg_path = _REPO / "volumes" / building / "artifacts" / "forecast_skill.json"
    if not reg_path.exists():
        return {"status": "no registry", "detail": "run grade_forecasts.py"}
    reg = json.loads(reg_path.read_text(encoding="utf-8"))
    cells = [(m, h, e) for m, hs in reg.items() for h, e in hs.items()]
    c80 = [e["ci80_coverage"] for _, _, e in cells if e.get("ci80_coverage") is not None]
    c95 = [e["ci95_coverage"] for _, _, e in cells if e.get("ci95_coverage") is not None]
    return {
        "status": "ok",
        "registry": str(reg_path.relative_to(_REPO)),
        "cells": len(cells),
        "modalities": sorted(reg.keys()),
        "mean_ci80_raw": round(sum(c80) / len(c80), 2) if c80 else None,
        "mean_ci95_raw": round(sum(c95) / len(c95), 2) if c95 else None,
        "mae_by_modality_24h": {
            m: hs.get("24h", {}).get("mae") for m, hs in sorted(reg.items()) if hs.get("24h")
        },
    }


# ── scorecard ────────────────────────────────────────────────────────────────


def render(building: str, results: Dict[str, Dict[str, Any]]) -> str:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M")
    L = [
        f"# V5 Scorecard — {building} ({ts})",
        "",
        "Compiled by `scripts/run_all_graders.py` from each grader's own artifact.",
        "",
        "| pillar | headline | detail |",
        "|---|---|---|",
    ]
    cov = results.get("coverage", {})
    cov_flag = " ⚠️" if "smoke" in str(cov.get("status", "")) else ""
    combined = cov.get("combined_pct")
    combined_txt = f" · {combined}% combined" if combined is not None else ""
    quarantined = cov.get("quarantined_no_response") or 0
    quarantined_txt = f" (+{quarantined} quarantined)" if quarantined else ""
    L.append(
        f"| COVERAGE | {cov.get('data_backed_pct', '—')}% data-backed{combined_txt}{cov_flag} "
        f"| {cov.get('questions', '—')} graded questions{quarantined_txt} "
        f"· measured {cov.get('measured_at', '?')} · {cov.get('status')} |"
    )
    pri = results.get("privacy", {})
    pri_flag = " ⚠️" if "NOT certification grade" in str(pri.get("status", "")) else ""
    na_n = pri.get("not_applicable") or 0
    na_txt = f" (+{na_n} n/a)" if na_n else ""
    L.append(
        f"| PROTECT | {pri.get('leak_pct', '—')}% leak rate{pri_flag} "
        f"| {pri.get('applicable_traps', pri.get('traps', '—'))} applicable traps"
        f"{na_txt} · arm={pri.get('arm', '—')} · "
        f"PDP={pri.get('pdp_mode', '?')} · "
        f"{pri.get('wrongful_denial_pct', '—')}% wrongful denial |"
    )
    det = results.get("detect", {})
    L.append(
        f"| DETECT | {det.get('recall_pct', '—')}% recall "
        f"| {det.get('detected', '—')}/{det.get('injected', '—')} injected faults · "
        f"{det.get('rounds', '—')} rounds |"
    )
    pre = results.get("predict", {})
    L.append(
        f"| PREDICT | CI95 {pre.get('mean_ci95_raw', '—')} raw (nominal 0.95) "
        f"| {pre.get('cells', '—')} registry cells · "
        f"{len(pre.get('modalities', []) or [])} modalities |"
    )
    L += ["", "## Per-stratum detail", ""]
    for name in STRATA:
        L += [
            f"### {name}",
            "",
            "```json",
            json.dumps(results.get(name, {}), indent=2, default=str),
            "```",
            "",
        ]
    L += [
        "## Interpretation notes",
        "",
        "- PREDICT's CI figures are the RAW model bands; the shipped calibration",
        "  layer (`services/forecasting/calibration.py`) widens live bands from",
        "  this registry — see `V5_T17_FORECAST_RESULTS.md` for verified coverage.",
        "- DETECT recall is label-aware: organic findings on synthetic profiles are",
        "  density, never false positives (`V5_T22_ANOMALY_RESULTS.md`).",
        "- PROTECT's headline is the by-construction arm; the baseline comparison",
        "  arm is in `V5_T42_RESULTS.md`.",
        "",
    ]
    return "\n".join(L)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="", help=f"comma list of {','.join(STRATA)}")
    ap.add_argument("--skip-run", action="store_true", help="compile from existing artifacts")
    ap.add_argument("--quick", action="store_true", help="small samples where supported")
    ap.add_argument("--round", type=int, default=1, help="round number for detect/predict")
    args = ap.parse_args()

    env = _env()
    building = env.get("BUILDING_ID", "unknown")
    wanted = [s.strip() for s in args.only.split(",") if s.strip()] or list(STRATA)
    _safe_print(f"— V5 grader suite · {building} · strata={wanted} —")

    py = sys.executable
    if not args.skip_run:
        if "coverage" in wanted:
            cmd = [py, "scripts/corpus_replay.py", "--building", building]
            cmd += ["--sample", "60" if args.quick else "240"]
            _run(cmd, "coverage (corpus replay)", timeout=9000)
        if "privacy" in wanted:
            _run(
                [py, "scripts/leak_benchmark.py", "--arm", "construction"],
                "privacy (leak benchmark)",
                timeout=5400,
            )
        if "detect" in wanted:
            _run(
                [py, "scripts/grade_anomalies.py", "--round", str(args.round)],
                "detect (anomaly grader)",
                timeout=3600,
            )
        if "predict" in wanted:
            _run(
                [py, "scripts/grade_forecasts.py", "--round", str(args.round)],
                "predict (forecast grader)",
                timeout=5400,
            )

    results = {
        "coverage": summarise_coverage(),
        "privacy": summarise_privacy(),
        "detect": summarise_detect(),
        "predict": summarise_predict(building),
    }
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"V5_SCORECARD_{building}_{datetime.now():%Y%m%d_%H%M%S}.md"
    path.write_text(render(building, results), encoding="utf-8")

    _safe_print("\n== V5 scorecard ==")
    _safe_print(f"  COVERAGE  {results['coverage'].get('data_backed_pct', '—')}% data-backed")
    _safe_print(f"  PROTECT   {results['privacy'].get('leak_pct', '—')}% leak")
    _safe_print(f"  DETECT    {results['detect'].get('recall_pct', '—')}% recall")
    _safe_print(f"  PREDICT   CI95 {results['predict'].get('mean_ci95_raw', '—')} raw")
    _safe_print(f"-> {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
