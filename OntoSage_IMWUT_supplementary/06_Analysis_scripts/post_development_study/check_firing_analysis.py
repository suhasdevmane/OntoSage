#!/usr/bin/env python3
"""How often OntoSage's two switchable checks acted, failed closed or failed open, and what they did to the answers
(TODO 5.2; plan 03 section 4.2 "count and report", section 7.6; RQ2 measures table "check-firing and fail-open
counts"). Also the claim-binding MEASUREMENT (record-only in the study: never described as stopping a number).

    python build_check_records.py      # first (reads the restricted logs, writes outcome-only records)
    python check_firing_analysis.py

Reads only e6_offline_runs/check_records_offline.csv, deidentified_v1/turn_checks.csv and the answer labels. Writes
results/checks/: check_firing_offline.csv, check_firing_live.csv, acted_comparison.csv (each comparison question
where a check acted on OntoSage's answer, with the labels of all three systems), acted_live.csv, claim_binding.csv,
numbers_checks.csv, checks_results.json.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from study_paths import DEID, E6, LABELS, RESULTS, pass1_labels, sha256  # noqa: E402

OUT = RESULTS / "checks"
REF = ["referent_refused", "referent_asked_which", "referent_bound_only_one", "referent_failed_closed",
       "referent_failed_open"]
REL = ["relevance_replaced", "relevance_objected_kept", "relevance_failed_open"]
NUMS: list = []
PASS1, LABEL_SRC = pass1_labels()


def num(key: str, value, desc: str, labels: bool = False) -> None:
    """``labels``: the number rests on answer labels (so it is provisional until the human labels exist)."""
    NUMS.append({"key": key, "value": value, "description": desc, "script": "check_firing_analysis.py",
                 "label_source": LABEL_SRC if labels else ""})


def acted(d: pd.DataFrame) -> pd.Series:
    """The answer was changed or held by a check: refused, asked which, bound, failed closed, or replaced."""
    cols = [c for c in REF[:4] + ["relevance_replaced"] if c in d]
    return d[cols].sum(axis=1) > 0


def tally(d: pd.DataFrame) -> dict:
    out = {"answers": int(len(d)), "window_shared": int((d.window_shared == 1).sum())}
    for c in REF + REL:
        out[f"answers_{c}"] = int((d[c] > 0).sum())
    out["answers_any_check_acted"] = int(acted(d).sum())
    return out


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    res = {}
    # ---------------------------------------------------------------- offline (RQ2)
    off = pd.read_csv(E6 / "check_records_offline.csv", dtype={"qid": str}).fillna("")
    for c in REF + REL + ["window_shared", "route_referent_refused", "found_in_log"]:
        off[c] = pd.to_numeric(off[c], errors="coerce").fillna(0).astype(int)
    off = off.sort_values("attempt").drop_duplicates(["run_file", "system", "qid", "run"], keep="last")  # re-run scored
    rows = []
    for (rf, sysname), g in off.groupby(["run_file", "system"]):
        t = {"run_file": rf, "system": sysname, "log_available": int(g.log_available.max()),
             "answers_route_referent_refused": int(g.route_referent_refused.sum())}
        t.update(tally(g) if g.log_available.max() else {"answers": int(len(g))})
        t["events_assigned_by_time"] = int(g.attribution.str.contains("time").sum())
        rows.append(t)
    tab = pd.DataFrame(rows).fillna("")
    tab.to_csv(OUT / "check_firing_offline.csv", index=False)
    res["offline"] = rows
    a = off[(off.system == "A")]
    res["offline_A_all"] = tally(a)
    am = off[off.system == "A-minus"]
    res["offline_Aminus_route_referent_refused"] = int(am.route_referent_refused.sum())
    for k, v in res["offline_A_all"].items():
        num(f"checks_offline_A_{k}", v, f"OntoSage+'s {res['offline_A_all']['answers']} offline answers (comparison, "
            f"T-TASK, stability): {k.replace('_', ' ')}")
    num("checks_offline_Aminus_referent_refused", res["offline_Aminus_route_referent_refused"],
        "A-minus (checks off): answers whose route records a referent refusal (expected 0)")

    # what the checks did on the comparison set: OntoSage's label where a check acted, beside A-minus and B
    lab_f = LABELS / "rq2" / "rq2_labels_comparison.csv"
    if lab_f.exists():
        lab = pd.read_csv(lab_f, dtype=str).fillna("")
        w = lab.pivot_table(index="qid", columns="system", values="label", aggfunc="first")
        ca = a[a.run_file == "comparison"]
        res["comparison_A_tally"] = tally(ca)
        ca = ca[acted(ca) | (ca.relevance_objected_kept > 0)]
        out = []
        for r in ca.itertuples():
            what = [c for c in REF + REL if getattr(r, c) > 0]
            out.append({"qid": r.qid, "set": r.set, "checks": ";".join(what), "attribution": r.attribution,
                        "form": lab[(lab.qid == r.qid)].form.iloc[0] if (lab.qid == r.qid).any() else "",
                        "label_OntoSage": w.loc[r.qid].get("A", "") if r.qid in w.index else "",
                        "label_A_minus": w.loc[r.qid].get("A-minus", "") if r.qid in w.index else "",
                        "label_B": w.loc[r.qid].get("B", "") if r.qid in w.index else ""})
        acted_cmp = pd.DataFrame(out)
        acted_cmp.to_csv(OUT / "acted_comparison.csv", index=False)
        res["acted_comparison"] = out
        res["acted_comparison_label_source"] = lab.labeller.iloc[0] if "labeller" in lab else ""
        num("checks_comparison_A_acted", len(out),
            "comparison set (100): OntoSage+ answers where a switchable check acted or objected")
        cmp_src = "HUMAN_AGREED" if str(res["acted_comparison_label_source"]).startswith("HUMAN") \
            else "PROVISIONAL_AI_PRELABEL"
        for chk, what in (("referent_refused", "referent-gate refusals"), ("relevance_replaced", "gate replacements"),
                          ("relevance_objected_kept", "objections the gate was not allowed to act on")):
            sub = acted_cmp[acted_cmp.checks.str.contains(chk)] if len(acted_cmp) else acted_cmp
            if len(sub):
                lab_a = sub.label_OntoSage.value_counts().to_dict()
                lab_m = sub.label_A_minus.value_counts().to_dict()
                NUMS.append({"key": f"checks_comparison_{chk}_labels", "script": "check_firing_analysis.py",
                             "value": f"{len(sub)}: OntoSage+ {lab_a}; A-minus {lab_m}",
                             "description": f"comparison set: {what}, labels of OntoSage+'s answer and of A-minus's "
                                            "answer to the same question", "label_source": cmp_src})
        for key, chk, lab_want, what in (
                ("checks_comparison_referent_refusals_correct", "referent_refused", "WL",
                 "comparison set: referent-gate refusals labelled WL"),
                ("checks_comparison_gate_replacements_wrong_refusal", "relevance_replaced", "FD",
                 "comparison set: relevance-gate replacements labelled FD")):
            sub = acted_cmp[acted_cmp.checks.str.contains(chk)] if len(acted_cmp) else acted_cmp
            NUMS.append({"key": key, "value": f"{int((sub.label_OntoSage == lab_want).sum()) if len(sub) else 0} "
                                              f"of {len(sub)}", "description": what,
                         "script": "check_firing_analysis.py", "label_source": cmp_src})

    # ---------------------------------------------------------------- live (RQ3 answers)
    live = pd.read_csv(DEID / "turn_checks.csv", dtype=str).fillna("")
    for c in REF + REL + ["window_shared", "found_in_log"]:
        live[c] = pd.to_numeric(live[c], errors="coerce").fillna(0).astype(int)
    rows = []
    for role, g in [("all", live)] + list(live.groupby("role")):
        t = {"role": role}
        t.update(tally(g))
        # an entry is "name: detail"; a detail can itself hold ";", so only pieces that start with a name count
        for col, tag in (("gates_applied", "gate"), ("gates_advisory", "advisory")):
            names = g[col].str.split(";").explode().str.strip().str.extract(r"^([a-z_]+)(?::|$)")[0].dropna()
            for k, v in names.value_counts().items():
                t[f"evidence_record_{tag}_{k}"] = int(v)
        rows.append(t)
    pd.DataFrame(rows).fillna(0).to_csv(OUT / "check_firing_live.csv", index=False)
    res["live"] = rows
    for k, v in rows[0].items():
        if k != "role":
            num(f"checks_live_{k}", v, f"live answers participants saw ({rows[0]['answers']}): {k.replace('_', ' ')}")

    pass1 = PASS1
    if pass1.exists():
        l1 = pd.read_csv(pass1, dtype=str).fillna("").set_index("turn_id")
        al = live[acted(live) | (live.relevance_objected_kept > 0)].copy()
        al["checks"] = al.apply(lambda r: ";".join(c for c in REF + REL if r[c] > 0), axis=1)
        al["label"] = al.turn_id.map(l1["label"]) if "label" in l1 else ""
        al[["turn_id", "role", "form", "situation", "route_final", "checks", "label"]].to_csv(
            OUT / "acted_live.csv", index=False)
        res["acted_live_labels"] = al.groupby("checks").label.value_counts().unstack(fill_value=0).to_dict("index")
        res["acted_live_label_source"] = pass1.name
        ref = al[al.checks.str.contains("referent_refused")]
        rep = al[al.checks.str.contains("relevance_replaced")]
        num("checks_live_referent_refusals_correct", f"{int((ref.label == 'WL').sum())} of {len(ref)}",
            "live: referent-gate refusals labelled WL (a correct statement of the limit)", labels=True)
        num("checks_live_gate_replacements_wrong_refusal", f"{int((rep.label == 'FD').sum())} of {len(rep)}",
            "live: relevance-gate replacements labelled FD (the replacing refusal was itself wrong)", labels=True)

    # ---------------------------------------------------------------- the decisions that followed (RQ3 link)
    dec_f = RESULTS / "rq3" / "decisions_with_labels.csv"
    if dec_f.exists():
        dec = pd.read_csv(dec_f, dtype=str).fillna("")
        ck = live.set_index("turn_id")
        rec = dec[dec.received_turn != ""].copy()
        rec["gate_replaced"] = rec.received_turn.map(ck["relevance_replaced"]).fillna(0).astype(int) > 0
        rec["referent_refused"] = rec.received_turn.map(ck["referent_refused"]).fillna(0).astype(int) > 0
        fd = rec[rec.answer_received == "FD"]
        link = {"decisions_with_a_received_answer": int(len(rec)), "received_FD": int(len(fd)),
                "received_FD_that_was_a_relevance_gate_replacement": int(fd.gate_replaced.sum()),
                "received_FD_that_was_a_referent_refusal": int(fd.referent_refused.sum()),
                "decisions_after_a_gate_replacement": int(rec.gate_replaced.sum()),
                "of_which_correct": int((rec[rec.gate_replaced].warranted == "1").sum()),
                "forms_after_a_gate_replacement": rec[rec.gate_replaced].form.value_counts().to_dict()}
        res["decisions_link"] = link
        num("checks_received_FD_from_relevance_gate",
            f"{link['received_FD_that_was_a_relevance_gate_replacement']} of {link['received_FD']}",
            "wrong refusals participants received before a decision that were the relevance gate's replacement "
            "(the rest came from the lanes themselves)", labels=True)
        num("checks_decisions_after_gate_replacement",
            f"{link['of_which_correct']} of {link['decisions_after_a_gate_replacement']} correct",
            "decisions made after receiving a relevance-gate replacement")

    # ---------------------------------------------------------------- claim binding (a measurement)
    ct = pd.to_numeric(live.claims_total, errors="coerce")
    cu = pd.to_numeric(live.claims_unbound, errors="coerce")
    cb = []
    for role, m in [("all", ct.notna())] + [(r, (live.role == r) & ct.notna()) for r in sorted(live.role.unique())]:
        tot, unb = float(ct[m].sum()), float(cu[m].sum())
        with_fig = int((ct[m] > 0).sum())
        cb.append({"role": role, "answers_with_figures": with_fig, "figures": int(tot),
                   "figures_matched_to_retrieved_rows": int(tot - unb),
                   "share_matched": round((tot - unb) / tot, 4) if tot else None,
                   "answers_with_an_unmatched_figure": int(((cu > 0) & m).sum())})
    pd.DataFrame(cb).to_csv(OUT / "claim_binding.csv", index=False)
    res["claim_binding"] = cb
    c0 = cb[0]
    num("claims_live_share_matched", f"{100 * c0['share_matched']:.1f}% ({c0['figures_matched_to_retrieved_rows']} of "
        f"{c0['figures']})", "live answers: share of OntoSage+'s figures that match a retrieved row (claim binding, "
        "record-only; a figure can be right and unmatched, e.g. a computed mean)")
    num("claims_live_answers_with_unmatched", f"{c0['answers_with_an_unmatched_figure']} of {c0['answers_with_figures']}",
        "live answers with figures that hold at least one figure not matched to a retrieved row")

    res["notes"] = [
        "Relevance-gate failures other than an exception (a timeout, a provider error, an unreadable verdict) leave "
        "the answer standing and are not logged, so its fail-open count covers exceptions only.",
        "A-minus: its container's log was not kept, so only its route is read; both checks were off by setting "
        "(confirmed inside the container).",
        "window_shared: another answer overlapped the window, so its events cannot be told apart from the other "
        "answer's.",
    ]
    for f in (E6 / "check_records_offline.csv", DEID / "turn_checks.csv"):
        res.setdefault("inputs", {})[f.name] = sha256(f)[:16]
    (OUT / "checks_results.json").write_text(json.dumps(res, indent=1, default=str), encoding="utf-8")
    pd.DataFrame(NUMS).to_csv(OUT / "numbers_checks.csv", index=False)
    print(tab.to_string(index=False))
    print(pd.DataFrame(rows).fillna(0).T.to_string())
    print(pd.DataFrame(cb).to_string(index=False))
    if "acted_comparison" in res:
        print(acted_cmp.to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
