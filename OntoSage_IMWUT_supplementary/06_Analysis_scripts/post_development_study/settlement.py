"""What the settling meeting decided, recorded beside each agreed draft (plan 19 D7, tracker G14).

Every agreement script writes agreed_draft.csv with an empty 'disputed' column. At the meeting the two coders fill
each empty cell with the value they agree on. Where they still disagree, 'yes' goes in that row's 'disputed' column.

A disputed row is resolved one of two ways:
  - **discussed and resolved**: a documented, item-by-item discussion against the rubric settled it -- for either
    coder's label. Recorded in a sibling `resolution_log.csv` (id, agreed_label, resolved_as=coder1|coder2,
    rationale_source), built from the dated discussion record it points to (e.g.
    `E5_W_WL_disagreements_for_discussion.csv`, 28 Oct 2026: 12 live-answer disputes, 9 confirmed coder 1, 3
    confirmed coder 2 against the rubric's worked examples). This is the normal path once a discussion happened.
  - **the pre-agreed fallback (D7, decided 25 Oct 2026 before any disagreement was seen)**: for a disputed row with
    no recorded discussion, the first author's value stays. This only still applies to a row `resolution_log.csv`
    does not cover.

Each finaliser then calls kept_first_author() (a disputed, undiscussed row must carry coder 1's values; a discussed
row must carry its logged resolution) and write() (the counts the paper reports: items both coded, items the coders
disagreed on, items resolved by discussion for each coder, items still defaulted by the fallback), and
text_numbers.py reads settlement.json into the AGREE_* numbers.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

YES = {"yes", "y", "1", "true", "x"}


def disputed_ids(rows: Iterable[dict], id_col: str) -> List[str]:
    """Ids of the rows marked still disputed."""
    return [str(r[id_col]) for r in rows if str(r.get("disputed", "") or "").strip().lower() in YES]


def load_resolution_log(draft: Path) -> Dict[str, dict]:
    """A sibling resolution_log.csv, if the draft's folder has one: id -> {agreed_label, resolved_as, rationale_source}."""
    p = draft.parent / "resolution_log.csv"
    if not p.exists():
        return {}
    return {r["id"]: r for r in csv.DictReader(p.open(encoding="utf-8-sig"))}


def kept_first_author(rows: Iterable[dict], id_col: str, coder1: Dict[Tuple[str, str], str], norm=str.strip,
                       resolved: Optional[Dict[str, dict]] = None) -> List[str]:
    """Problems where a disputed row's settled value is wrong (coder1: (id, field) -> coder 1's value, for the
    disagreeing cells only). A row in `resolved` (from resolution_log.csv) must match its logged agreed_label,
    whichever coder that is; every other disputed row falls back to D7 and must keep coder 1's value."""
    disputed = set(disputed_ids(rows, id_col))
    by_id = {str(r[id_col]): r for r in rows}
    resolved = resolved or {}
    errs = []
    for (i, f), v in coder1.items():
        if i not in disputed:
            continue
        actual = str(by_id[i].get(f, ""))
        if i in resolved and f == "agreed_label":
            want = resolved[i]["agreed_label"]
            if norm(actual) != norm(want):
                errs.append(f"{i}: {f} is logged as {want!r} in resolution_log.csv, not {actual!r}")
        elif norm(actual) != norm(str(v)):
            errs.append(f"{i}: {f} is marked disputed with no logged resolution, so it keeps the first author's "
                        f"{v!r}, not {actual!r}")
    return errs


def write(draft: Path, material: str, both_coded: int, disagreeing: Iterable[str], disputed: Iterable[str],
          resolved: Optional[Dict[str, dict]] = None) -> dict:
    """settlement.json beside the draft (a test's draft sits in its own folder, so a test never writes here)."""
    dis, dsp = sorted(set(map(str, disagreeing))), sorted(set(map(str, disputed)))
    resolved = resolved or {}
    by_c1 = sorted(i for i in dsp if resolved.get(i, {}).get("resolved_as") == "coder1")
    by_c2 = sorted(i for i in dsp if resolved.get(i, {}).get("resolved_as") == "coder2")
    fallback = sorted(i for i in dsp if i not in resolved)
    res = {"material": material, "items_both_coded": int(both_coded), "items_disagreed": len(dis),
           "items_still_disputed": len(fallback), "disputed_ids": dsp,
           "items_discussed_resolved": len(by_c1) + len(by_c2),
           "items_discussed_resolved_coder1": len(by_c1), "items_discussed_resolved_coder2": len(by_c2),
           "discussed_resolved_coder2_ids": by_c2,
           "rule": ("a disputed item is settled by a documented, item-by-item discussion against the rubric where "
                    "one was held; otherwise it keeps the first author's label (plan 19 D7, decided 25 Oct 2026)")}
    out = draft.parent / "settlement.json"
    out.write_text(json.dumps(res, indent=1) + "\n", encoding="utf-8")
    print(f"settlement: {len(dis)} items disagreed, {len(by_c1)}+{len(by_c2)} discussed and resolved "
          f"(coder1/coder2), {len(fallback)} defaulted by the fallback rule -> {out}")
    return res
