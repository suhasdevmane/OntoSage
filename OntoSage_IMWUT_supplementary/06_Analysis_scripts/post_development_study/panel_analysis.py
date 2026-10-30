#!/usr/bin/env python3
"""OntoSage's evidence panel on the answers participants saw: what it said, and whether its kind of claim agrees with
what the answer did (pre-registered descriptive "evidence panel accuracy", Analysis_Specification RQ2 table; rubric
step 2). A deterministic consistency check, not the rubric's per-panel judgement: whether the listed sources support
the text (panel_supports_text) and whether the panel itself is wrong (panel_wrong) stay with the human pass, because
the panel names sources by kind ("Sensor reading", "Building model"), not by room or period.

    python panel_analysis.py

Reads deidentified_v1/turns.csv (the answer as shown, with its panel) and the pass-1 labels (agreed, else the AI
pre-labels). Writes results/panels/: panel_fields.csv (one row per answer: kind of claim, operation, kind of source,
number of sources, completeness and checks lines), claim_by_label.csv, numbers_panels.csv, panels_results.json.

Two contradictions are counted:
  evidence claimed for a wrong refusal   label FD, panel kind 'observed' or 'calculated' (the text says there is no
                                          data; the panel says it read or calculated some)
  no evidence claimed for an answer       label W or U, panel kind 'not_assessable' (the panel says the evidence could
                                          not support an answer; the text gives one)
and one exposure: unsupported answers (U) whose panel claims evidence.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from study_paths import DEID, RESULTS, pass1_labels, sha256  # noqa: E402

OUT = RESULTS / "panels"
PANEL_RE = re.compile(r'<details type="evidence">(.*?)</details>', re.S)
FIELD_RE = re.compile(r"^- \*\*([^*]+?):\*\*\s*(.*)$")
EVIDENCE = {"observed", "calculated", "inferred", "predicted", "recommended"}


def fields(panel: str) -> dict:
    out = {"kind": "", "operation": "", "source_kind": "", "n_sources": 0, "completeness": "", "compared_against": "",
           "checks_fired": "", "when": ""}
    for line in panel.splitlines():
        m = FIELD_RE.match(line.strip())
        if not m:
            continue
        k, v = m.group(1).strip(), m.group(2).strip()
        if k == "Kind of claim":
            out["kind"] = v.split(" — ")[0].split(" - ")[0].strip()
        elif k == "Operation performed":
            out["operation"] = v
        elif k == "Kind of source that led":
            out["source_kind"] = v
        elif k.startswith("Sources ("):
            out["n_sources"] = int(re.search(r"\((\d+)\)", k).group(1))
        elif k == "Completeness":
            out["completeness"] = v
        elif k == "Compared against":
            out["compared_against"] = v
        elif k == "Checks that fired":
            out["checks_fired"] = v
        elif k == "When":
            out["when"] = v
    return out


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    t = pd.read_csv(DEID / "turns.csv", dtype=str, keep_default_na=False)
    lab_f, src = pass1_labels()
    lab = pd.read_csv(lab_f, dtype=str, keep_default_na=False).set_index("turn_id")
    rows = []
    for r in t.itertuples():
        m = PANEL_RE.search(r.answer_as_shown or "")
        f = fields(m.group(1)) if m else {}
        rows.append({"turn_id": r.turn_id, "role": r.role, "form": r.form, "situation": r.situation,
                     "panel_present": int(bool(m)), "label": lab["label"].get(r.turn_id, ""), **f})
    d = pd.DataFrame(rows)
    d.to_csv(OUT / "panel_fields.csv", index=False)
    p = d[d.panel_present == 1]
    ct = pd.crosstab(p.kind, p.label, margins=True)
    ct.to_csv(OUT / "claim_by_label.csv")
    fd, wu, u = p[p.label == "FD"], p[p.label.isin(["W", "U"])], p[p.label == "U"]
    res = {
        "label_source": src, "answers": int(len(d)), "with_panel": int(len(p)),
        "fd_with_evidence_claim": [int(fd.kind.isin(EVIDENCE).sum()), int(len(fd))],
        "w_or_u_with_not_assessable": [int((wu.kind == "not_assessable").sum()), int(len(wu))],
        "u_with_evidence_claim": [int(u.kind.isin(EVIDENCE).sum()), int(len(u))],
        "with_completeness_line": int((p.completeness != "").sum()),
        "with_checks_line": int((p.checks_fired != "").sum()),
        "kind_counts": p.kind.value_counts().to_dict(),
        "inputs": {DEID.name + "/turns.csv": sha256(DEID / "turns.csv")[:16], lab_f.name: sha256(lab_f)[:16]},
    }
    (OUT / "panels_results.json").write_text(json.dumps(res, indent=1), encoding="utf-8")
    nums = [
        ("panels_present", f"{res['with_panel']} of {res['answers']}", "live answers that carried an evidence panel", ""),
        ("panels_fd_with_evidence_claim", f"{res['fd_with_evidence_claim'][0]} of {res['fd_with_evidence_claim'][1]}",
         "wrong refusals (FD) whose panel says the answer was observed or calculated", src),
        ("panels_w_or_u_not_assessable", f"{res['w_or_u_with_not_assessable'][0]} of {res['w_or_u_with_not_assessable'][1]}",
         "answers labelled W or U whose panel says the evidence could not support an answer", src),
        ("panels_u_with_evidence_claim", f"{res['u_with_evidence_claim'][0]} of {res['u_with_evidence_claim'][1]}",
         "unsupported answers (U) whose panel claims observed or calculated evidence", src),
    ]
    pd.DataFrame([{"key": k, "value": v, "description": dsc, "script": "panel_analysis.py", "label_source": ls}
                  for k, v, dsc, ls in nums]).to_csv(OUT / "numbers_panels.csv", index=False)
    print(ct.to_string())
    print(json.dumps({k: v for k, v in res.items() if k != "inputs"}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
