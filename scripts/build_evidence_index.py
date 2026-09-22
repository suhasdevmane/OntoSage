# -*- coding: utf-8 -*-
"""Turn a capture run into the evidence pack's contents page (building-agnostic).

Reads ``answers.jsonl`` from ``scripts/capture_evidence_screenshots.py`` and writes ``INDEX.md``:
one row per question with its shape, how long it took, and a link to its screenshot, plus the
answer text so a reader can search the pack without opening 25 images.

It refuses to present an incomplete capture as evidence: any row whose answer was still streaming
when the screenshot was taken is listed in its own section, and the header says so.

    python scripts/build_evidence_index.py --dir docs/supervisor_evidence
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path
from typing import Dict, List, Optional

REPO = Path(__file__).resolve().parent.parent


def load(path: Path) -> List[Dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _quote(text: str, limit: int = 900) -> str:
    body = " ".join((text or "").split())
    if len(body) > limit:
        body = body[:limit].rstrip() + " …"
    return body or "_(no text captured)_"


_ICON = {"GOOD": "answers it", "WEAK": "**does not answer it**", "FLAGGED": "**do not rely on**"}


def render(rows: List[Dict[str, object]], model: str, user: str,
           verdicts: Optional[Dict[str, List[str]]] = None) -> str:
    verdicts = verdicts or {}
    for r in rows:
        v = verdicts.get(str(r["n"]))
        r["verdict"], r["note"] = (v[0], v[1]) if v else ("UNREVIEWED", "")
    done = [r for r in rows if r.get("complete")]
    bad = [r for r in rows if not r.get("complete")]
    secs = sorted(float(r["seconds"]) for r in done) or [0.0]
    median = secs[len(secs) // 2]
    good = [r for r in done if r["verdict"] == "GOOD"]
    weak = [r for r in done if r["verdict"] in ("WEAK", "FLAGGED")]

    out = [
        "# Evidence pack — the system answering, one screenshot per question",
        "",
        f"Captured {date.today().isoformat()} against the running stack through Open WebUI "
        f"(`{model}`), signed in as `{user}` — a facility-manager account, not an administrator, "
        "so nothing here is admin-only output.",
        "",
        "Each question was asked in a **fresh chat** with both answer caches flushed beforehand, so "
        "every answer is a first pass and none was served from cache. The screenshots are full-page "
        "captures of the real browser; the answer text below each row is what the page showed.",
        "",
        f"**{len(done)} of {len(rows)} captured completely. Every answer was then read against what "
        f"the question asked: {len(good)} answer it, {len(weak)} do not.** Median answer time "
        f"{median:.0f} s (slowest {max(secs):.0f} s).",
        "",
        "> Read this with `docs/SUPERVISOR_BRIEF.md`. Two things are deliberate. The pack includes",
        "> the questions the system **declines**, because declining what it cannot ground is the",
        "> behaviour being claimed and a pack of successes alone would not evidence it. And it",
        "> includes the answers that came out **wrong**, with what is wrong with each: a pack that",
        "> showed only the good ones would not be evidence, it would be advertising.",
        "",
    ]
    if weak:
        out += ["**Read these before the rest:**", ""]
        for r in weak:
            out.append(f"- **{r['n']}. {r['question']}** — {r['verdict']}. {r['note']}")
        out.append("")
    if bad:
        out += [
            f"> **{len(bad)} question(s) did not finish inside the time limit and are listed "
            "separately at the end. Their screenshots are not evidence of an answer.**",
            "",
        ]

    out += ["## Contents", "",
            "| # | shape | question | verdict | time | screenshot |", "|---|---|---|---|---|---|"]
    for r in done:
        out.append(
            f"| {r['n']} | {r['shape']} | {r['question']} | "
            f"{_ICON.get(str(r['verdict']), str(r['verdict']))} | {float(r['seconds']):.0f} s | "
            f"[view]({r['screenshot']}) |"
        )
    out += ["", "---", "", "## The answers", ""]
    for r in done:
        out += [
            f"### {r['n']}. {r['question']}",
            "",
            f"*Shape: {r['shape']} · {float(r['seconds']):.0f} s · "
            f"screenshot: [`{Path(str(r['screenshot'])).name}`]({r['screenshot']})*",
            "",
            f"**Verdict: {r['verdict']}.** {r['note']}" if r["note"] else f"**Verdict: {r['verdict']}.**",
            "",
            "> " + _quote(str(r["answer"])).replace("\n", "\n> "),
            "",
        ]
    if bad:
        out += ["---", "", "## Did not finish in time (not evidence of an answer)", ""]
        for r in bad:
            out += [
                f"- **{r['n']}. {r['question']}** — still generating after "
                f"{float(r['seconds']):.0f} s. Re-run this one before relying on it.",
            ]
        out.append("")
    return "\n".join(out)


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default=str(REPO / "docs" / "supervisor_evidence"))
    ap.add_argument("--model", default="ontobot-pipeline")
    ap.add_argument("--user", default="facility01")
    args = ap.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    d = Path(args.dir)
    rows = load(d / "answers.jsonl")
    review = d / "review.json"
    verdicts = (json.loads(review.read_text(encoding="utf-8")).get("verdicts")
                if review.exists() else {})
    (d / "INDEX.md").write_text(render(rows, args.model, args.user, verdicts), encoding="utf-8")
    done = sum(1 for r in rows if r.get("complete"))
    unreviewed = [r["n"] for r in rows if str(r["n"]) not in (verdicts or {})]
    print(f"wrote {d/'INDEX.md'} — {done}/{len(rows)} complete")
    if unreviewed:
        print(f"NOTE: {len(unreviewed)} row(s) carry no hand-read verdict: {unreviewed}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
