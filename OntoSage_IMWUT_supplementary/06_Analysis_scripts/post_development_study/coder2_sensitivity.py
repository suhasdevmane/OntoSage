#!/usr/bin/env python3
"""Task A3 (plan 20 section 3): recompute every result that rests on a field below the 0.60 kappa rule, swapping
in the second coder's codes on the items he sampled (everything else stays the first author's). Per plan 20
decision E2, this currently covers only the two reason codes two RQ3 sentences rest on (LIMIT_MATCH,
DECLINE_ACCEPTED) and the live answer labels (RQ3 answer-type / E2 warranted-rate split); F3a/F3b/F3c are NOT
recomputed here because the article already reports them as the first author's coding alone, used in no
comparison (plan 20 E2) -- there is nothing comparative to re-run.

    python coder2_sensitivity.py

Writes results/text/numbers_sens_c2.csv (SENS_C2_* keys), read by build_article_assets.py like every other
per-analysis numbers file. Never edits the author's files; only ever swaps the sampled subset for this one
computation.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import qual_analysis as QA  # noqa: E402
import rq3_live_analysis as R3A  # noqa: E402
from study_paths import LABELS, RESULTS  # noqa: E402

OUT = RESULTS / "text" / "numbers_sens_c2.csv"
ROWS: list = []


def add(key: str, value, desc: str) -> None:
    # SECOND_CODER, not an invented string: make_number_macros.py whitelists exactly this one for "settled, not
    # orange" -- these numbers rest on the first author's reviewed codes plus the second coder's actual return,
    # nothing provisional about them.
    ROWS.append({"key": key, "value": str(value), "description": desc, "script": "coder2_sensitivity.py",
                 "label_source": "SECOND_CODER"})


def reasons_sensitivity() -> None:
    d, src = QA.load()
    c2 = pd.read_csv(LABELS / "second_coder_return" / "coder2_qual.csv", dtype=str).fillna("")
    c2 = c2.set_index("unit_id")
    swapped = d.set_index("unit_id").copy()
    cols = [c for c in QA.REASON + QA.CLOSING if c in c2.columns]
    n_swapped = 0
    for uid in c2.index:
        if uid in swapped.index:
            for c in cols:
                swapped.loc[uid, c] = pd.to_numeric(c2.loc[uid, c], errors="coerce") if c2.loc[uid, c] != "" else 0
            n_swapped += 1
    swapped = swapped.reset_index()
    add("SENS_C2_qual_n_swapped", n_swapped, "reasons/closing units where the second coder's codes replaced the "
                                              "first author's for this check")

    tr = swapped[swapped.unit == "task_reason"]
    lim = tr[tr.LIMIT_RECOGNISED == 1]
    fd, wl = tr[tr.answer_received == "FD"], tr[tr.answer_received == "WL"]
    add("SENS_C2_qual_reasons_limit_named", len(lim), "on his codes: reasons naming a limit")
    add("SENS_C2_qual_reasons_limit_matches_key", int(lim.LIMIT_MATCH.sum()), "on his codes: of which the limit named is real")
    add("SENS_C2_qual_after_FD_n", len(fd), "on his codes: reasons after a wrong refusal")
    add("SENS_C2_qual_after_FD_decline_accepted", int(fd.DECLINE_ACCEPTED.sum()),
        "on his codes: of which took the refusal as the answer")
    add("SENS_C2_qual_after_WL_n", len(wl), "on his codes: reasons after a stated limit")
    add("SENS_C2_qual_after_WL_decline_accepted", int(wl.DECLINE_ACCEPTED.sum()),
        "on his codes: of which took the refusal as the answer")
    for s, g in lim.groupby("situation"):
        add(f"SENS_C2_LIM_situation_{s}_named", len(g), f"on his codes: reasons naming a limit, situation {s}")
        add(f"SENS_C2_LIM_situation_{s}_match", int(g.LIMIT_MATCH.sum()), f"on his codes: ... of which real, situation {s}")


def live_e2_sensitivity() -> None:
    dec, par, turns, own, labels, label_source = R3A.load()
    c2 = pd.read_csv(LABELS / "second_coder_return" / "coder2_pass1.csv", dtype=str).fillna("")
    c2_map = dict(zip(c2.answer_id, c2.label))  # answer_id IS turn_id (finalise_agreed_labels.py)
    lab = labels.set_index("turn_id")["label"].to_dict()
    swapped = {**lab, **{k: v for k, v in c2_map.items() if k in lab}}
    add("SENS_C2_live_n_swapped", sum(1 for k in c2_map if k in lab),
        "live answers where the second coder's label replaced the first author's for this check")
    d = dec.copy()
    d["recv"] = d.received_turn.map(swapped).fillna("none")
    for L in R3A.LAB + ["none"]:
        sub = d[d.recv == L]
        if len(sub):
            add(f"SENS_C2_E2_{L}_n", len(sub), f"on his labels: decisions after an answer labelled {L}")
            add(f"SENS_C2_E2_{L}_pct", round(100 * sub.warranted.mean(), 1),
                f"on his labels: % of those decisions the data support")


def main() -> int:
    reasons_sensitivity()
    live_e2_sensitivity()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(ROWS).to_csv(OUT, index=False)
    print(f"{len(ROWS)} sensitivity numbers -> {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
