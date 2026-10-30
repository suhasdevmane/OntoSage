#!/usr/bin/env python3
"""A COPY of the article with the generated tables and figures placed in the empty RQ1 / RQ2 / RQ3 stubs (TODO 7.2).

    python insert_results_draft.py        # after build_article_assets.py

Reads paper/research paper v9.tex (never changed) and writes
paper/research paper v9 - results inserted (draft).tex. Only \\input lines and the figure blocks from
generated/study_v9/fig_blocks.tex are added - no prose: the text of the results is the first author's to write (the third author,
13 Oct). Each block ends with \\clearpage so the floats stay inside their own subsection. Build it with
pdflatex + bibtex under its own name; the original's build files are not touched.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from study_paths import REPO  # noqa: E402

PAPER = REPO / "paper"
SRC = PAPER / "research paper v9.tex"
DST = PAPER / "research paper v9 - results inserted (draft).tex"
GEN = "generated/study_v9"
RQ1 = ["fig:rq1-fresh"]     # the stub's "Figure 1 (F2/F4, corpus vs fresh)"; its table twin is for the supplement
RQ2 = ["tab:rq2-outcomes", "fig:rq2-frontier", "fig:rq2-frontier-sets", "fig:rq2-anatomy", "tab:rq2-cost",
       "tab:rq2-stability", "tab:checks"]
RQ3 = ["tab:record-flow", "tab:rq3-e1", "fig:rq3-e1", "tab:rq3-e2", "fig:rq3-e2", "fig:rq3-reliance",
       "fig:rq3-calibration", "fig:rq3-own", "fig:rq3-reasons", "tab:measures", "fig:measures", "tab:deviations"]
TABLES = {"tab:rq2-outcomes": "tab_rq2_outcomes", "tab:rq2-cost": "tab_rq2_cost", "tab:rq2-stability": "tab_rq2_stability",
          "tab:record-flow": "tab_record_flow", "tab:rq3-e1": "tab_rq3_e1", "tab:rq3-e2": "tab_rq3_e2",
          "tab:measures": "tab_measures", "tab:deviations": "tab_deviations", "tab:checks": "tab_checks"}
HEAD = ("% ==== DRAFT INSERTION by insert_results_draft.py: generated tables and figures only, no prose. Write the "
        "text yourself; the captions are factual drafts; items marked PROVISIONAL rest on AI pre-labels. ====")


def figure_blocks() -> dict:
    text = (PAPER / GEN / "fig_blocks.tex").read_text(encoding="utf-8")
    out = {}
    for m in re.finditer(r"(%[^\n]*\n)?\\begin\{figure\}.*?\\end\{figure\}", text, re.S):
        lab = re.search(r"\\label\{([^}]+)\}", m.group(0))
        if lab:
            out[lab.group(1)] = m.group(0).strip()
    return out


def block(labels: list, figs: dict) -> list:
    lines = [HEAD]
    for lab in labels:
        if lab in TABLES:
            if (PAPER / GEN / f"{TABLES[lab]}.tex").exists():
                lines.append(rf"\input{{{GEN}/{TABLES[lab]}.tex}}")
        elif lab in figs:
            lines.append(figs[lab])
    lines += [r"\clearpage", "% ==== END OF DRAFT INSERTION ===="]
    return lines


def main() -> int:
    src = SRC.read_text(encoding="utf-8").splitlines()
    figs = figure_blocks()
    out, done = [], set()
    i = 0
    while i < len(src):
        line = src[i]
        out.append(line)
        for key, labels in ((r"\label{sec:rq1}", RQ1), (r"\label{sec:rq2}", RQ2), (r"\label{sec:rq3}", RQ3)):
            if line.strip() == key and key not in done:
                while i + 1 < len(src) and src[i + 1].lstrip().startswith("%"):
                    i += 1
                    out.append(src[i])
                out += block(labels, figs)
                done.add(key)
        i += 1
    if len(done) != 3:
        print(f"stubs not found: {done}")
        return 1
    DST.write_text("\n".join(out) + "\n", encoding="utf-8")
    print(f"{DST.name}: {len(out) - len(src)} lines added in the RQ1, RQ2 and RQ3 stubs; figures "
          f"{len([lab for lab in RQ1 + RQ2 + RQ3 if lab in figs])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
