# -*- coding: utf-8 -*-
"""compile_v5_results.py — V5-T45/T36: one results table set from the run artifacts.

Reads the newest ``V5_SCORECARD_<building>_*.md`` for each building, the leak-benchmark
CSVs for both privacy arms, and the model-benchmark report, and writes
``scripts/outputs/V5_RESULTS.md``. Re-run any time; it always takes the newest artifact.

**A building that was never certified says so.** It is not omitted and it is not shown
blank, because a table with four buildings and three rows reads as "the fourth scored
nothing" to everyone who did not run it. Half of this project's discarded artifacts came
from a number whose provenance nobody could reconstruct, so every figure here carries
the file it came from and the date it was measured.

**A run that declared itself invalid is never aggregated.** ``certify_building.py``
stamps ``## Run validity: VALID|INVALID`` into the scorecard it produces; an INVALID
scorecard is listed with its reason and excluded from every total. Averaging a run whose
stack died mid-way is how CAVEAT-173 and BUG-177 produced numbers that had to be thrown
away.

Usage:
  python scripts/compile_v5_results.py
  python scripts/compile_v5_results.py --buildings bldg1,bldg2,bldg3
"""

from __future__ import annotations

import argparse
import csv
import glob
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

_SCRIPT_DIR = Path(__file__).resolve().parent
_OUT = _SCRIPT_DIR / "outputs"

_DEFAULT_BUILDINGS = ["bldg1", "bldg2", "bldg3", "bldg4"]

#: The four pillars, in the order the thesis presents them.
_PILLARS = ["coverage", "privacy", "detect", "predict"]


def _newest(pattern: str) -> Optional[Path]:
    hits = sorted(glob.glob(str(_OUT / pattern)))
    return Path(hits[-1]) if hits else None


def _scorecard(bid: str) -> Optional[Path]:
    return _newest(f"V5_SCORECARD_{bid}_*.md")


def _validity(text: str) -> str:
    """VALID / INVALID / UNKNOWN, from the stamp certify_building writes."""
    m = re.search(r"^##\s*Run validity:\s*(\w+)", text, re.MULTILINE)
    return (m.group(1).upper() if m else "UNKNOWN").strip()


def _pillar_blocks(text: str) -> Dict[str, Dict[str, Any]]:
    """The per-stratum JSON blocks, keyed by stratum name.

    Parsed from the scorecard rather than recomputed from the raw CSVs on purpose: the
    scorecard is what was published, so a discrepancy between it and a recomputation is
    a fact worth seeing rather than something to paper over silently.
    """
    out: Dict[str, Dict[str, Any]] = {}
    for match in re.finditer(
        r"^###\s+(\w+)\s*\n+```json\n(.*?)\n```", text, re.MULTILINE | re.DOTALL
    ):
        name = match.group(1).strip().lower()
        try:
            out[name] = json.loads(match.group(2))
        except json.JSONDecodeError:
            out[name] = {"status": "unparseable"}
    return out


def _fmt_pct(value: Any) -> str:
    try:
        return f"{float(value):.1f}%"
    except (TypeError, ValueError):
        return "—"


def _coverage_cell(b: Dict[str, Any]) -> str:
    if not b or b.get("status") not in ("ok", None):
        return f"_{b.get('status', 'not measured')}_"
    quarantined = b.get("quarantined_no_response") or 0
    tail = f" (+{quarantined} quarantined)" if quarantined else ""
    return (
        f"{_fmt_pct(b.get('data_backed_pct'))} data · "
        f"{_fmt_pct(b.get('combined_pct'))} combined<br>"
        f"{b.get('questions', '—')} graded{tail}"
    )


def _privacy_cell(b: Dict[str, Any]) -> str:
    if not b:
        return "_not measured_"
    return (
        f"{_fmt_pct(b.get('leak_pct'))} leak<br>"
        f"{b.get('traps', '—')} traps · arm={b.get('arm', '—')}<br>"
        f"{_fmt_pct(b.get('wrongful_denial_pct'))} wrongful denial"
    )


def _detect_cell(b: Dict[str, Any]) -> str:
    if not b:
        return "_not measured_"
    recall = b.get("recall_pct", b.get("recall"))
    return f"{_fmt_pct(recall)} recall<br>{b.get('detected', '—')}/{b.get('injected', '—')} faults"


def _predict_cell(b: Dict[str, Any]) -> str:
    """CI95 coverage and the modality count, read from the grader's own field names.

    ``mean_ci95_raw`` is what grade_forecasts emits. A first pass guessed
    ``ci95_coverage`` and rendered an em dash for a pillar that had in fact been
    measured — a missing number and an unmeasured one look identical in a table, and
    only one of them is true.
    """
    if not b:
        return "_not measured_"
    ci = b.get("mean_ci95_raw", b.get("ci95_coverage", b.get("ci95")))
    try:
        ci_s = f"{float(ci):.2f}"
    except (TypeError, ValueError):
        ci_s = "—"
    mods = b.get("modalities") or []
    detail = f"{b.get('cells', '—')} registry cells"
    if mods:
        detail += f" · {len(mods)} modalities"
    return f"CI95 {ci_s} (nominal 0.95)<br>{detail}"


_CELL = {
    "coverage": _coverage_cell,
    "privacy": _privacy_cell,
    "detect": _detect_cell,
    "predict": _predict_cell,
}


def _leak_arms() -> List[Dict[str, Any]]:
    """One row per privacy ARM, so 'enforced by construction' can be compared with
    'prompt-only guards' rather than asserted."""
    rows = []
    for arm in ("construction", "guards-only"):
        path = _newest(f"v5_t42_leak_{arm}_*.csv")
        if not path:
            rows.append({"arm": arm, "status": "not run"})
            continue
        with path.open(encoding="utf-8-sig") as fh:
            data = list(csv.DictReader(fh))
        verdicts = [r.get("verdict", "") for r in data]
        na = verdicts.count("NA_REFERENT_ABSENT")
        n = (len(verdicts) - na) or 1
        rows.append(
            {
                "arm": arm,
                "status": "ok",
                "n": len(verdicts) - na,
                "na": na,
                "leak_pct": 100.0 * verdicts.count("LEAK") / n,
                "pass_pct": 100.0 * verdicts.count("PASS") / n,
                "denial_pct": 100.0 * verdicts.count("WRONGFUL_DENIAL") / n,
                "src": path.name,
                "transcript": (
                    path.name.replace(".csv", "_transcript.jsonl")
                    if (path.parent / path.name.replace(".csv", "_transcript.jsonl")).is_file()
                    else ""
                ),
            }
        )
    return rows


def _model_table() -> str:
    """The per-model benchmark, quoted from its own report rather than recomputed."""
    path = _newest("V5_T44_MODEL_BENCHMARK_*.md")
    if not path:
        return "_No model benchmark artifact found (V5-T44 not run here)._\n"
    text = path.read_text(encoding="utf-8", errors="replace")
    tables = re.findall(r"(^\|.*\n(?:^\|.*\n)+)", text, re.MULTILINE)
    body = tables[0] if tables else "_(report contains no table)_\n"
    return f"Source: `outputs/{path.name}`\n\n{body}"


def build(buildings: List[str]) -> str:
    lines: List[str] = [
        "# V5 Results — certification across buildings",
        "",
        "Compiled by `scripts/compile_v5_results.py` from each run's own artifact. Every "
        "figure names the file it came from; nothing here is retyped by hand.",
        "",
    ]

    found: Dict[str, Dict[str, Any]] = {}
    invalid: List[str] = []
    missing: List[str] = []

    for bid in buildings:
        card = _scorecard(bid)
        if card is None:
            missing.append(bid)
            continue
        text = card.read_text(encoding="utf-8", errors="replace")
        validity = _validity(text)
        if validity == "INVALID":
            invalid.append(f"{bid} (`{card.name}`)")
            continue
        found[bid] = {
            "blocks": _pillar_blocks(text),
            "card": card.name,
            "validity": validity,
        }

    # ── the certification table ──────────────────────────────────────────────
    lines += ["## Certification by building", ""]
    if not found:
        lines += ["_No valid scorecard for any requested building._", ""]
    else:
        header = "| pillar | " + " | ".join(found) + " |"
        lines += [header, "|---|" + "---|" * len(found)]
        for pillar in _PILLARS:
            cells = [_CELL[pillar](found[b]["blocks"].get(pillar, {})) for b in found]
            lines.append(f"| {pillar.upper()} | " + " | ".join(cells) + " |")
        lines.append("")
        lines += ["| building | scorecard | run validity |", "|---|---|---|"]
        for b, meta in found.items():
            lines.append(f"| {b} | `outputs/{meta['card']}` | {meta['validity']} |")
        lines.append("")

    # ── what is NOT here, said out loud ──────────────────────────────────────
    if missing or invalid:
        lines += ["### Not included", ""]
        for bid in missing:
            lines.append(f"- **{bid}** — no scorecard found; this building was not certified.")
        for entry in invalid:
            lines.append(
                f"- **{entry}** — the run declared itself INVALID and is excluded from "
                f"every total above."
            )
        lines.append("")

    # ── privacy arms ─────────────────────────────────────────────────────────
    lines += [
        "## Privacy: enforced by construction vs prompt-only guards",
        "",
        "The comparison the PROTECT claim rests on. Both arms replay the same trap bank; "
        "they differ only in whether the policy decision point is enforced.",
        "",
        "| arm | traps | leak | pass | wrongful denial | artifact |",
        "|---|---|---|---|---|---|",
    ]
    for row in _leak_arms():
        if row["status"] != "ok":
            lines.append(f"| {row['arm']} | — | — | — | — | _not run_ |")
            continue
        na = f" (+{row['na']} n/a)" if row["na"] else ""
        src = f"`outputs/{row['src']}`"
        if row["transcript"]:
            src += f"<br>replies: `outputs/{row['transcript']}`"
        lines.append(
            f"| {row['arm']} | {row['n']}{na} | {row['leak_pct']:.1f}% | "
            f"{row['pass_pct']:.1f}% | {row['denial_pct']:.1f}% | {src} |"
        )
    lines.append("")

    # ── models ───────────────────────────────────────────────────────────────
    lines += ["## Per-model behaviour and plan invariance", "", _model_table(), ""]
    lines += [
        "> Plan invariance must be read beside its NOISE FLOOR — the same model run "
        "twice. Cross-model agreement measured at or below that floor once "
        "(CAVEAT-327), which made the claim unmeasurable rather than false. The "
        "compile cache pins a repeat of a question to its own plan, and "
        "`CQIR_COMPILE_CACHE=false` turns it off so the floor can still be measured "
        "honestly.",
        "",
    ]
    return "\n".join(lines) + "\n"


def main(argv: List[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument(
        "--buildings",
        default=",".join(_DEFAULT_BUILDINGS),
        help="comma list; a building with no scorecard is reported, not skipped",
    )
    ap.add_argument("--out", default=str(_OUT / "V5_RESULTS.md"))
    args = ap.parse_args(argv)

    buildings = [b.strip() for b in args.buildings.split(",") if b.strip()]
    text = build(buildings)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    print(f"wrote {out}")
    print(text[: text.index("## Privacy") if "## Privacy" in text else 1200])
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
