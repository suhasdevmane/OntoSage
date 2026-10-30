#!/usr/bin/env python3
"""Numbers the article's prose needs that the analyses write only into tables: one key per number.

    python text_numbers.py

Reads the analyses' own outputs (never the data) and writes results/text/numbers_text.csv in the numbers format
(key, value, description, script, label_source). build_article_assets.py folds it into results_numbers.csv, and
make_number_macros.py turns every key into \\sv{key} for the article. A number that rests on answer labels carries the
label source its table carries; a number that rests only on the decisions and the keys has none (it is final).

Covers: decisions after each kind of answer (E2), what people chose after a wrong refusal or an unsupported answer,
recovery after a first answer, the labels of the answers participants received in tasks and to their own questions,
helpfulness by answer (C2), per-form results, the GEE and the exploratory mixed model without S3.
"""

from __future__ import annotations

import csv
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from study_paths import LABELS, REPO, RESULTS  # noqa: E402

R3 = RESULTS / "rq3"
OUT = RESULTS / "text"
ROWS: list = []


def add(key: str, value, desc: str, src: str = "") -> None:
    ROWS.append({"key": key, "value": str(value), "description": desc, "script": "text_numbers.py", "label_source": src})


def read(name: str) -> list:
    with (R3 / name).open(encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def pct(x: float) -> str:
    return f"{100 * float(x):.0f}"


AGREE_DIRS = {"live": "agreement", "offline": "agreement_comparison", "reasons": "qual/agreement",
              "mixed": "rq1/agreement", "partA": "partA/agreement"}
SECOND = "SECOND_CODER"        # measured against the second coder: final once computed (make_number_macros)


def f2(x) -> str:
    return "n/a" if x is None or x != x else f"{float(x):.2f}"


def agreement_numbers(root: Path = None, out: Path = None) -> None:
    """AGREE_*: agreement with the second coder and what the settling meeting left disputed, per material, from the
    agreement scripts' agreement.json and the finalisers' settlement.json (settlement.py). Nothing is written for a
    material whose files do not exist yet, so the article keeps its pending marks until they do."""
    root = root or LABELS
    rows = []

    def add(key, value, desc, src):
        rows.append({"key": key, "value": str(value), "description": desc, "script": "text_numbers.py",
                     "label_source": src})

    tot = {"disagreed": 0, "disputed": 0, "materials": 0}
    for m, sub in AGREE_DIRS.items():
        d = root / sub
        a = json.loads((d / "agreement.json").read_text(encoding="utf-8")) if (d / "agreement.json").exists() else None
        if a and m in ("live", "offline"):
            h = a["humans"]
            add(f"AGREE_{m}_n", h["n"], f"{m} answers both coders labelled", SECOND)
            add(f"AGREE_{m}_kappa", f2(h["kappa"]), f"{m} answers: Cohen's kappa, first author vs second coder", SECOND)
            add(f"AGREE_{m}_kappa_ci", f"{f2(h['kappa_ci'][0])}--{f2(h['kappa_ci'][1])}",
                f"{m} answers: bootstrap 95% interval of kappa", SECOND)
            add(f"AGREE_{m}_pct", pct(h["percent_agreement"]), f"{m} answers: % of labels the coders agreed on", SECOND)
            add(f"AGREE_{m}_kappa_U", f2(h["kappa_U_vs_not_U"]), f"{m} answers: kappa on U against every other label",
                SECOND)
        elif a and m == "reasons":
            ks = [v["kappa"] for v in a["per_code"].values() if v["kappa"] is not None]
            add("AGREE_reasons_n", a["units_both_coded"], "reasons both coders coded", SECOND)
            add("AGREE_reasons_pct", pct(a["overall_raw_agreement"]), "reasons: % of code cells the coders agreed on",
                SECOND)
            if ks:
                add("AGREE_reasons_kappa_median", f2(sorted(ks)[len(ks) // 2]), "reasons: median kappa over the codes",
                    SECOND)
                add("AGREE_reasons_kappa_range", f"{f2(min(ks))}--{f2(max(ks))}", "reasons: lowest and highest kappa",
                    SECOND)
            for c, v in a["per_code"].items():
                add(f"AGREE_reasons_kappa_{c}", f2(v["kappa"]), f"reasons: kappa for {c}", SECOND)
        elif a:                                    # mixed, Part A: analysis_partA.agreement
            add(f"AGREE_{m}_n", a["n_pairs"], f"{m} questions both coders coded", SECOND)
            for f, v in a.items():
                if isinstance(v, dict) and "kappa" in v:
                    add(f"AGREE_{m}_kappa_{f.split('_', 1)[0]}", f2(v["kappa"]), f"{m}: Cohen's kappa for {f}", SECOND)
                elif isinstance(v, dict) and "mean_jaccard" in v:
                    add(f"AGREE_{m}_jaccard_{f.split('_', 1)[0]}", f2(v["mean_jaccard"]), f"{m}: mean Jaccard for {f}",
                        SECOND)
        s = json.loads((d / "settlement.json").read_text(encoding="utf-8")) if (d / "settlement.json").exists() else None
        if s:
            add(f"AGREE_{m}_disagreed", s["items_disagreed"], f"{m}: items the two coders labelled differently", SECOND)
            add(f"AGREE_{m}_disputed", s["items_still_disputed"],
                f"{m}: items with no recorded discussion, decided by the pre-agreed fallback rule (kept the first "
                f"author's label, plan 19 D7)", SECOND)
            if "items_discussed_resolved" in s:
                add(f"AGREE_{m}_discussed", s["items_discussed_resolved"],
                    f"{m}: items settled by a documented, item-by-item discussion against the rubric", SECOND)
                add(f"AGREE_{m}_discussed_coder1", s["items_discussed_resolved_coder1"],
                    f"{m}: of those, discussion confirmed the first author's label", SECOND)
                add(f"AGREE_{m}_discussed_coder2", s["items_discussed_resolved_coder2"],
                    f"{m}: of those, discussion confirmed the second coder's label instead", SECOND)
            tot = {"disagreed": tot["disagreed"] + s["items_disagreed"],
                   "disputed": tot["disputed"] + s["items_still_disputed"], "materials": tot["materials"] + 1}
    if tot["materials"] == len(AGREE_DIRS):     # the totals only once every material is settled
        add("AGREE_all_disagreed", tot["disagreed"], "items the two coders labelled differently, all materials", SECOND)
        add("AGREE_all_disputed", tot["disputed"], "items decided by the pre-agreed rule, all materials", SECOND)
    out = out or RESULTS / "agreement"           # tests pass their own folder: the article must never see them
    out.mkdir(parents=True, exist_ok=True)
    with (out / "numbers_agreement.csv").open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["key", "value", "description", "script", "label_source"],
                           lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    print(f"{len(rows)} agreement numbers -> {out / 'numbers_agreement.csv'}")


def main() -> int:
    for r in read("e2_by_answer_received.csv"):
        if r["basis"] != "answer_received":
            continue
        L, src = r["label"], r["label_source"]
        add(f"E2_{L}_k_n", f"{r['k_warranted']}/{r['n']}", f"correct decisions after a last answer labelled {L}", src)
        if r["rate"] not in ("", "nan"):                      # n < 10 is reported as a count only
            add(f"E2_{L}_pct", pct(r["rate"]), f"% correct after a last answer labelled {L}", src)
        if r["lo"] not in ("", "nan"):
            add(f"E2_{L}_ci", f"{pct(r['lo'])}-{pct(r['hi'])}", f"95% CI for % correct after {L}", src)
    src = read("e2_by_answer_received.csv")[0]["label_source"]
    kinds = {"accepted an unsupported claim": "unsup", "false absence or limit": "falseabs",
             "under-reliance (could not find out)": "cnf", "warranted": "correct"}
    for r in read("decision_kind_by_answer_received.csv"):
        for col, short in kinds.items():
            add(f"E2_{r['answer_received']}_{short}", r[col],
                f"decisions after a last answer labelled {r['answer_received']}: {col}", src)
    for r in read("recovery.csv"):
        L, s = r["first_answer"], r["label_source"]
        add(f"REC_{L}_n", r["n_tasks"], f"tasks whose first answer was labelled {L}", s)
        add(f"REC_{L}_followup", r["asked_follow_up"], f"... of which the participant asked a follow-up", s)
        add(f"REC_{L}_correct", r["final_warranted"], f"... of which the decision was correct", s)
        add(f"REC_{L}_followup_correct", r["follow_up_and_warranted"], f"... follow-up asked and decision correct", s)
    dist = read("task_answer_label_distribution.csv")
    labels = [c for c in dist[0] if c != "situation"]
    totals = {L: 0 for L in labels}
    for r in dist:
        n = sum(int(r[L]) for L in labels)
        add(f"TA_{r['situation']}_n", n, f"task answers received in {r['situation']}", src)
        for L in labels:
            totals[L] += int(r[L])
            add(f"TA_{r['situation']}_{L}", r[L], f"task answers in {r['situation']} labelled {L}", src)
    for L, v in totals.items():
        add(f"TA_{L}", v, f"task answers labelled {L} (all situations)", src)
    add("TA_n", sum(totals.values()), "task answers received (all situations)", src)
    for r in read("own_question_answer_labels.csv"):
        add(f"OWN_{r['label']}", r["own-question answers"], f"answers to own questions labelled {r['label']}", src)
    for r in read("c2_helpfulness_by_answer_received.csv"):
        add(f"C2_{r['answer_received']}_mean", f"{float(r['mean']):.1f}",
            f"mean helpfulness (1-5) after a last answer labelled {r['answer_received']}", r["label_source"])
    sens = read("e2_sensitivity.csv")
    fd = [float(r["rate"]) for r in sens if r["label"] == "FD"]
    u = [float(r["rate"]) for r in sens if r["label"] == "U"]
    add("E2sens_FD_range", f"{pct(min(fd))}-{pct(max(fd))}", "% correct after FD across the label variants", src)
    add("E2sens_U_range", f"{pct(min(u))}-{pct(max(u))}", "% correct after U across the label variants", src)
    for r in read("per_form.csv"):
        f = r["form"]
        add(f"FORM_{f}_k_n", f"{r['k_warranted']}/{r['n']}", f"correct decisions, form {f}")
        add(f"FORM_{f}_pct", pct(r["warranted_rate"]), f"% correct, form {f}")
        for o in "abcdef":
            v = r.get(f"opt_{o}", "")
            if v not in ("", "0"):
                add(f"FORM_{f}_opt_{o}", v, f"decisions choosing option ({o}), form {f}")
    j = json.loads((R3 / "rq3_results.json").read_text(encoding="utf-8"))
    g = j["E1_gee_coefficients"]
    for s in ("S2", "S4"):
        c = g[f"C(situation, Treatment('S1'))[T.{s}]"]
        add(f"GEE_{s}_p", f"{c['p']:.3f}", f"GEE (exchangeable within participant): {s} vs S1, p")
    add("C1_p_boot", f"{j['C1_S2_minus_S1']['p_boot']:.3f}", "C1 bootstrap p (unadjusted)")
    c2 = j["C2_helpfulness_WL_minus_FD"]
    add("C2_diff", f"{c2['diff']:+.2f}", "C2: helpfulness WL minus FD (1-5 scale)", c2["label_source"])
    add("C2_ci", f"{c2['lo']:+.2f} to {c2['hi']:+.2f}", "C2 95% bootstrap CI", c2["label_source"])
    add("C2_p_boot", f"{c2['p_boot']:.2f}", "C2 bootstrap p (unadjusted)", c2["label_source"])
    add("SUS_sd", f"{j['usability']['sus_sd']:.1f}", "SUS standard deviation")
    ow = j["own_questions"]
    add("OWN_linked", ow["linked"], "own questions asked live that could be linked to their answers", src)
    add("OWN_last_unwarranted", ow["last_answer_unwarranted"],
        "linked own questions whose last answer was FD, U or OT", src)
    # RQ2: Holm values split out of their JSON cells, error kinds per system, answer times, OntoSage against A-minus.
    # A4 (28 Oct): each group below gets the label source of the ONE set it actually came from -- never one
    # blanket value for the whole file. `src2`, the previous blanket, silently picked whichever row's label_source
    # came first in numbers_rq2.csv (always a comparison-set row, always HUMAN_AGREED) and stamped it onto the
    # stability numbers too, which are genuinely still AI-only: the wrong direction of error, hiding exactly the
    # orange mark a reader needs.
    R2 = RESULTS / "rq2"
    with (R2 / "numbers_rq2.csv").open(encoding="utf-8-sig", newline="") as fh:
        n2 = list(csv.DictReader(fh))
    for r in n2:
        if r["key"].endswith("_holm"):
            for k, v in json.loads(r["value"]).items():
                add(f"{r['key']}_{k.replace('+', '')}", f"{float(v):.3f}", f"{r['key']}: Holm-adjusted p for {k}",
                    r["label_source"])          # this row's own source -- already correct per set, not a blanket
    j2 = json.loads((R2 / "rq2_results.json").read_text(encoding="utf-8"))
    by_set = j2.get("label_source_by_set", {})
    norm = lambda k: "PROVISIONAL_AI_PRELABEL_BLIND_SHEET" if k == "PROVISIONAL_AI_PRELABEL" else k  # noqa: E731
    src_comparison = norm(by_set.get("comparison", "PROVISIONAL_AI_PRELABEL"))
    src_stability = norm(by_set.get("stability", "PROVISIONAL_AI_PRELABEL"))
    for system, k in j2["empty_answers"].items():
        add(f"RQ2_{system.replace('-', '')}_empty", k, f"comparison set: answers of {system} that reached the step limit empty",
            src_comparison)
    # every kind for every system, 0 included: a kind no answer carries is a count of zero, not a missing number
    kinds = ["scope", "proxy", "temporal", "fabricated", "criterion_drop", "causal", "wrong_value", "wrong_source"]
    for system, subs in j2["u_subtypes_all"].items():
        for st in kinds + [s for s in subs if s not in kinds]:
            add(f"USUB_{system}_{st}", subs.get(st, 0), f"comparison set: U answers of {system} with the error kind {st}",
                src_comparison)
    with (R2 / "comparison_timing_by_system.csv").open(encoding="utf-8-sig", newline="") as fh:
        for r in csv.DictReader(fh):
            add(f"TIME_{r['system']}_median", f"{float(r['50%']):.0f}", f"comparison set: median seconds, {r['system']}",
                src_comparison)
            add(f"TIME_{r['system']}_p90", f"{float(r['90%']):.0f}", f"comparison set: 90th percentile seconds, {r['system']}",
                src_comparison)
    lab = LABELS / "rq2" / "rq2_labels_comparison.csv"
    with lab.open(encoding="utf-8-sig", newline="") as fh:
        lr = list(csv.DictReader(fh))
    a = {r["qid"]: r["label"] for r in lr if r["system"] == "A"}
    m = {r["qid"]: r["label"] for r in lr if r["system"] == "A-minus"}
    add("RQ2_A_vs_Aminus_label_differ", f"{sum(a[q] != m.get(q) for q in a)} of {len(a)}",
        "comparison set: questions where OntoSage+ and OntoSage+ with two checks off got different labels", src_comparison)
    with (R2 / "stability_labels_by_system.csv").open(encoding="utf-8-sig", newline="") as fh:
        for r in csv.DictReader(fh):
            for L in ("W", "WL", "FD", "U", "OT", "PF"):
                add(f"STAB_{r['system']}_{L}", r.get(L, "0"), f"stability runs: answers of {r['system']} labelled {L}",
                    src_stability)
    # RQ3: the first question's phrasing against the first answer's label
    with (R3 / "phrasing_by_label.csv").open(encoding="utf-8-sig", newline="") as fh:
        for r in csv.DictReader(fh):
            tag = {"all needed specifics stated": "complete", "something missing": "incomplete", "All": "all"}[r["all_needed_specified"]]
            for L in ("FD", "OT", "U", "W", "WL", "All"):
                add(f"PHR_{tag}_{L}", r[L], f"first questions ({tag}) whose first answer was labelled {L}", src)
    # Reasons: limits named, and whether they matched the key, by situation and form
    with (RESULTS / "qual" / "limit_match.csv").open(encoding="utf-8-sig", newline="") as fh:
        qs = json.loads((RESULTS / "qual" / "qual_results.json").read_text(encoding="utf-8")).get("label_source", "")
        for r in csv.DictReader(fh):
            if r["by"] in ("situation", "form", "correct"):
                add(f"LIM_{r['by']}_{r['value']}_named", r["n_limit_named"], f"reasons naming a limit, {r['by']} {r['value']}", qs)
                add(f"LIM_{r['by']}_{r['value']}_match", r["matches_key"], "... of which the limit matches the key", qs)
    corpus = REPO / "paper" / "Survey analysis and results" / "corpus" / "classified_corpus.csv"
    if corpus.exists():                                       # the context gap: Phase 1's lexicon classifier, by stage
        with corpus.open(encoding="utf-8-sig", newline="") as fh:
            cr = list(csv.DictReader(fh))
        for st in sorted({r["Stage"] for r in cr}):
            sub = [r for r in cr if r["Stage"] == st]
            other = sum(r["domain_l1"] == "OTHER" for r in sub)
            add(f"CG_S{st}_other_pct", f"{100 * other / len(sub):.1f}",
                f"Phase 1 stage {st}: share of questions the lexicon classifier put in OTHER (no building-vocabulary domain)")
            add(f"CG_S{st}_n", len(sub), f"Phase 1 stage {st}: questions")
    for r in read("table1_sample.csv"):                       # the sample (multi-select items count people per option)
        item = r["item"].split(" ", 1)[0]
        slug = re.sub(r"[^a-z0-9]+", "_", r["value"].lower()).strip("_")[:40]
        add(f"SAMPLE_{item}_{slug}", r["n"], f"participants: {r['item']} = {r['value']}")
    summ = LABELS / "author_check" / "check_summary.json"
    s = json.loads(summ.read_text(encoding="utf-8")) if summ.exists() else {}
    # The first author reviews every proposed answer label (offline, live) and every proposed code (reasons, mixed,
    # Part A, Stage 5) in the checking tool (plan 19, Option A); the repeated-run and T-TASK labels stay the AI's.
    # "Changed" is the main label for an answer, the code set for a reason or Stage 5 answer, and any field for a question.
    groups = {"answers": (("offline", "live"), "label_changed", "answer labels"),
              "codes": (("reasons", "mixed", "partA", "stage5"), "changed", "coded items (questions, reasons, Stage 5 answers)")}
    every = {"checked": 0, "total": 0, "minutes": 0.0, "done": True}
    for g, (mats, ck, what) in groups.items():
        tot = {"checked": 0, "total": 0, ck: 0, "minutes": 0.0}
        done = True
        for m in mats:
            e = s.get(m, {})
            ok = bool(e) and e.get("checked") == e.get("total") and e.get("exported") is not False   # a too-fast pass is not a review
            done = done and ok
            state = "AUTHOR_CHECK_COMPLETE" if ok else "AUTHOR_CHECK_IN_PROGRESS"
            minutes = float((e.get("pace") or {}).get("active_minutes") or 0)
            for k, v in (("checked", e.get("checked", 0)), ("total", e.get("total", 0)), (ck, e.get(ck, 0))):
                add(f"AC_{m}_{k}", v, f"the first author's review of the proposed {what}, {m}: {k}", state)
                tot[k] += int(v)
            add(f"AC_{m}_hours", f"{minutes / 60:.1f}", f"the first author's review, {m}: active hours in the tool's record", state)
            tot["minutes"] += minutes
        state = "AUTHOR_CHECK_COMPLETE" if done else "AUTHOR_CHECK_IN_PROGRESS"
        add(f"AC_{g}_checked", f"{tot['checked']:,}", f"proposed {what} the first author reviewed", state)
        add(f"AC_{g}_total", f"{tot['total']:,}", f"proposed {what} to review", state)
        add(f"AC_{g}_{ck}", tot[ck], f"{what} the first author changed", state)
        add(f"AC_{g}_hours", f"{tot['minutes'] / 60:.1f}", f"active hours of the first author's review of the {what} (tool record)", state)
        every = {"checked": every["checked"] + tot["checked"], "total": every["total"] + tot["total"],
                 "minutes": every["minutes"] + tot["minutes"], "done": every["done"] and done}
    sub = sum(int(s.get(m, {}).get("subtype_only_changed", 0)) for m in ("offline", "live"))
    state = "AUTHOR_CHECK_COMPLETE" if every["done"] else "AUTHOR_CHECK_IN_PROGRESS"
    add("AC_answers_subtype_changed", sub, "unsupported answers whose label was kept but whose kinds of error were changed", state)
    add("AC_all_checked", f"{every['checked']:,}", "proposed labels and codes the first author reviewed (all six materials)", state)
    add("AC_all_total", f"{every['total']:,}", "proposed labels and codes to review (all six materials)", state)
    add("AC_all_hours", f"{every['minutes'] / 60:.1f}", "active hours of the first author's whole review (tool record)", state)
    agreement_numbers()
    t = (R3 / "lme4_sensitivity_without_S3.txt").read_text(encoding="utf-8", errors="replace")
    block = t.split("====")[2] if t.count("====") >= 2 else t
    m = re.search(r"S2 / S1\s+([\d.]+)\s+[\d.]+\s+Inf\s+1\s+([\d.-]+)\s+([\d.]+)", block)
    if m:
        add("lme4_noS3_S2_OR", m.group(1), "exploratory model without S3, participant and form effects: odds ratio S2/S1")
        add("lme4_noS3_S2_p", f"{float(m.group(3)):.2f}", "exploratory model without S3, participant and form effects: p S2/S1")
    OUT.mkdir(parents=True, exist_ok=True)
    with (OUT / "numbers_text.csv").open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["key", "value", "description", "script", "label_source"], lineterminator="\n")
        w.writeheader()
        w.writerows(ROWS)
    print(f"{len(ROWS)} numbers -> {OUT / 'numbers_text.csv'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
