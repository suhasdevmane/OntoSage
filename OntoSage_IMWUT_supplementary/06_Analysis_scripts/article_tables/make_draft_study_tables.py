"""Generate the expanded article's new study tables and extra study values (plan 21, W5 and W8).

WHY
    The expanded article (paper/draft1Novsubmission/) needs tables that v9 did not have: inter-coder agreement by
    material and field (Method, "Who labelled"), the same in full with the results on the second coder's labels
    (Appendix E), what each task's key rests on (Appendix G), and the four situations of the task bank (Method),
    which v9 typed by hand. It also needs a few counts in prose that v9 typed ("Four of the twelve tasks ...").
    Every number here is read from a file that a script or the frozen task bank produced; nothing is typed.

INPUTS (read only)
    phd plan/[anonymised]/11_Study_Materials/F_Analysis/results/agreement/numbers_agreement.csv   kappa, CI, % same
    phd plan/[anonymised]/11_Study_Materials/F_Analysis/results/agreement/affected_fields.md      counts behind the
                                                                                               fields below 0.60
    phd plan/[anonymised]/11_Study_Materials/F_Analysis/results/results_numbers.csv               results as reported
                                                                                               and on the second
                                                                                               coder's labels
    phd plan/[anonymised]/11_Study_Materials/C_Task_Bank_and_Keys/task_bank.csv                   the task bank, frozen
                                                                                               14 Oct 2026 (study
                                                                                               material, not data)
    paper/generated/study_v9/numbers.tex                                                       to refuse a key that
                                                                                               already exists, and
                                                                                               to round values
                                                                                               already printed
    phd plan/[anonymised]/11_Study_Materials/F_Analysis/results/partA/numbers_partA.csv           Part A shares and
                                                                                               intervals (Section 6)
    .../F_Analysis/results/rq1/fresh_vs_corpus.csv          own questions against the 90 corpus questions
    .../F_Analysis/results/rq3/first_question_page.csv      decisions by where the first question was asked
    .../F_Analysis/results/rq3/e2_by_answer_received.csv    decisions by the last and by the worst answer
    .../F_Analysis/results/rq3/answer_timing.csv            decisions with no answer before deciding, and why
    .../F_Analysis/results/rq3/lme4_sensitivity_without_S3.txt   the exploratory model's unrounded p
    .../F_Analysis/results/rq2/blinding_check.csv           the second coder's system guesses, by system
    .../F_Analysis/results/qual/code_counts.csv             people per code and closing question

OUTPUTS (paper/generated/draft1Nov/)
    numbers_extra.tex / numbers_extra.csv     \\sv{} values in the sv@ namespace, each with its source
    tab_agreement.tex / .csv / _notes.txt     Method: agreement by material and field
    tab_agreement_full.tex / .csv / _notes.txt   Appendix E: every field, with the counts and how disagreements
                                                 were settled
    tab_agreement_c2.tex / .csv / _notes.txt  Appendix E: the results that rest on low-agreement fields, as reported
                                              and with the second coder's labels or codes on his sample
    tab_live_confusion.tex / .csv / _notes.txt   Appendix E: the double-coded live answers, first author's label
                                                 against the second coder's (from G_Study_Data/labels/agreement/
                                                 agreed_draft.csv, checked against confusion.csv)
    tab_task_sources.tex / .csv / _notes.txt  Appendix G: what each task's key rests on
    tab_situations.tex / .csv / _notes.txt    Method: the four situations, with one form of each and its key
    tab_partA_needs.tex / .csv / _notes.txt   Section 6: the Part A codes, stage-weighted, with their intervals

    Each .csv is the table's twin for paper/verify_claims.py (registered in
    draft1Nov_work/table_sources_study.csv); each _notes.txt holds the caption and note, whose numbers are checked too.

USAGE
    python -I paper/scripts/make_draft_study_tables.py
"""
import ast
import csv
import hashlib
import io
import os
import re
import sys
from collections import OrderedDict
from decimal import ROUND_HALF_UP, Decimal

HERE = os.path.dirname(os.path.abspath(__file__))
PAPER = os.path.dirname(HERE)
STUDY = os.path.join(PAPER, "phd plan", "[anonymised]", "11_Study_Materials")
AGREE_CSV = os.path.join(STUDY, "F_Analysis", "results", "agreement", "numbers_agreement.csv")
AFFECTED_MD = os.path.join(STUDY, "F_Analysis", "results", "agreement", "affected_fields.md")
RESULTS_CSV = os.path.join(STUDY, "F_Analysis", "results", "results_numbers.csv")
TASK_BANK = os.path.join(STUDY, "C_Task_Bank_and_Keys", "task_bank.csv")
NUMBERS_TEX = os.path.join(PAPER, "generated", "study_v9", "numbers.tex")
DEV_TEX = os.path.join(PAPER, "generated", "study_v9", "tab_deviations.tex")
RES = os.path.join(STUDY, "F_Analysis", "results")
PARTA_CSV = os.path.join(RES, "partA", "numbers_partA.csv")
RQ1_CSV = os.path.join(RES, "rq1", "fresh_vs_corpus.csv")
FIRSTQ_CSV = os.path.join(RES, "rq3", "first_question_page.csv")
E2_CSV = os.path.join(RES, "rq3", "e2_by_answer_received.csv")
TIMING_CSV = os.path.join(RES, "rq3", "answer_timing.csv")
LME4_TXT = os.path.join(RES, "rq3", "lme4_sensitivity_without_S3.txt")
BLIND_CSV = os.path.join(RES, "rq2", "blinding_check.csv")
QUAL_CSV = os.path.join(RES, "qual", "code_counts.csv")
# the two coders' labels on the double-coded live answers (label_coder1, label_coder2), and label_agreement.py's own
# crosstab of them; the confusion table (Appendix E, the first author 29 Oct item 14) is built from the first, checked on the second
LIVE_BOTH_CSV = os.path.join(STUDY, "G_Study_Data", "labels", "agreement", "agreed_draft.csv")
CONFUSION_CSV = os.path.join(STUDY, "G_Study_Data", "labels", "agreement", "confusion.csv")
OUT = os.path.join(PAPER, "generated", "draft1Nov")

THRESHOLD = 0.60          # the study plan's kappa rule (Agreement_and_Adjudication_Procedure.md)
LABELS = ["W", "WL", "FD", "U", "OT"]


def die(msg: str) -> None:
    sys.stderr.write("make_draft_study_tables: " + msg + "\n")
    sys.exit(1)


def sha(path: str) -> str:
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()[:16]


def rel(path: str) -> str:
    return os.path.relpath(path, PAPER).replace(os.sep, "/")


# ---------------------------------------------------------------- LaTeX text
_UNICODE = [
    ("–", "--"), ("—", "---"), ("’", "'"), ("‘", "`"), ("“", "``"), ("”", "''"),
    ("°C", r"\textdegree{}C"), ("°", r"\textdegree{}"), ("₂", r"\textsubscript{2}"),
    ("≈", r"$\approx$"), ("≥", r"$\geq$"), ("≤", r"$\leq$"), ("≠", r"$\neq$"),
    ("×", r"$\times$"), ("…", r"\ldots{}"), (" ", "~"),
]


def tex(s: str) -> str:
    """Escape a plain-text cell for LaTeX, then map the few non-ASCII characters the task bank uses."""
    s = str(s)
    s = s.replace("\\", r"\textbackslash{}")
    s = re.sub(r"([&%$#_{}])", r"\\\1", s)
    s = s.replace("~", r"\textasciitilde{}").replace("^", r"\textasciicircum{}")
    for a, b in _UNICODE:
        s = s.replace(a, b)
    s = re.sub(r"\bCO2\b", r"CO\\textsubscript{2}", s)          # typesetting only; the CSV twin keeps "CO2"
    s = re.sub(r"\bkappa (\d\.\d+)", r"$\\kappa=\1$", s)
    bad = sorted({c for c in s if ord(c) > 127})
    if bad:
        die(f"unmapped non-ASCII characters {bad!r} in: {s[:80]}")
    return s


def plain(s: str) -> str:
    """The same text as it appears in the CSV twin (Unicode kept, so numbers read the same)."""
    return str(s)


# ---------------------------------------------------------------- inputs
def read_agreement() -> dict:
    with open(AGREE_CSV, encoding="utf-8") as fh:
        return {r["key"]: r["value"] for r in csv.DictReader(fh)}


def read_results() -> dict:
    with open(RESULTS_CSV, encoding="utf-8") as fh:
        return {r["key"]: r for r in csv.DictReader(fh)}


def read_affected() -> dict:
    """Parse affected_fields.md (machine-written by the agreement scripts) into counts per material and field."""
    text = io.open(AFFECTED_MD, encoding="utf-8").read().replace("\r\n", "\n")
    out = {}
    live = re.search(r"## Live answer labels.*?- n=(\d+), kappa ([\d.]+), raw agreement (\d+)/(\d+) \((\d+)%\)\s*"
                     r"- first author's labels: (\{[^}]*\})\s*- second coder's labels: (\{[^}]*\})", text, re.S)
    if not live:
        die("affected_fields.md: live answer block not found (format changed?)")
    out[("live", "label")] = {
        "n": int(live.group(1)), "kappa": live.group(2), "agree_k": int(live.group(3)), "agree_n": int(live.group(4)),
        "pct": int(live.group(5)), "c1": ast.literal_eval(live.group(6)), "c2": ast.literal_eval(live.group(7))}
    for material, head in (("mixed", r"## Mixed questions"), ("partA", r"## Part A survey questions")):
        m = re.search(head + r".*?(?=\n## )", text, re.S)
        if not m:
            die(f"affected_fields.md: block {head!r} not found")
        for f in re.finditer(r"### (F3[abc])_\w+ -- kappa ([\d.]+)[^\n]*\n- raw agreement: (\d+)/(\d+) \((\d+)%\)\n"
                             r"- first author's values[^:]*: (\{[^}]*\})\n- second coder's values: (\{[^}]*\})",
                             m.group(0)):
            out[(material, f.group(1))] = {
                "kappa": f.group(2), "agree_k": int(f.group(3)), "agree_n": int(f.group(4)), "pct": int(f.group(5)),
                "c1": ast.literal_eval(f.group(6)), "c2": ast.literal_eval(f.group(7))}
    m = re.search(r"## Reason codes.*?(?=\n## )", text, re.S)
    if not m:
        die("affected_fields.md: reason-code block not found")
    for f in re.finditer(r"### (\w+) -- kappa ([^\n]+)\n- raw agreement: (\d+)/(\d+) \((\d+)%\)\n"
                         r"- first author ticked it: (\d+)/(\d+); second coder ticked it: (\d+)/(\d+)", m.group(0)):
        out[("reasons", f.group(1))] = {
            "kappa": f.group(2).split()[0], "agree_k": int(f.group(3)), "agree_n": int(f.group(4)),
            "pct": int(f.group(5)), "c1": int(f.group(6)), "c2": int(f.group(8)), "n": int(f.group(7))}
    return out


def read_task_bank() -> list:
    with open(TASK_BANK, encoding="utf-8") as fh:
        rows = [r for r in csv.DictReader(fh) if r["use"] == "study"]
    if not rows:
        die("task_bank.csv: no study forms")
    return rows


def existing_keys() -> set:
    return set(re.findall(r"\\csname sv@([^\\]+)\\endcsname", io.open(NUMBERS_TEX, encoding="utf-8").read()))


def sv_values() -> dict:
    """Every value printed by numbers.tex, as written there (LaTeX escapes kept)."""
    text = io.open(NUMBERS_TEX, encoding="utf-8").read()
    return {m.group(1): m.group(2) for m in re.finditer(r"\\csname sv@([^\\]+)\\endcsname\{(.*)\}%", text)}


def read_csv_rows(path: str) -> list:
    with open(path, encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def half_up(x, dp: int) -> str:
    """Round half up to dp places (a printed value, never banker's rounding)."""
    return str(Decimal(repr(float(x))).quantize(Decimal(1).scaleb(-dp), rounding=ROUND_HALF_UP))


def signed(x, dp: int = 0) -> str:
    s = half_up(x, dp)
    return s if s.startswith("-") else "+" + s


def k_of(n: int, rate: float) -> int:
    """The count behind a share (a rate written by the analysis), refusing a share that is not k/n."""
    k = round(n * rate)
    if abs(k - n * rate) > 1e-6:
        die(f"share {rate} is not a whole number of {n}")
    return k


# ---------------------------------------------------------------- task-bank kinds
KIND_ORDER = ["real readings", "generated series", "constructed record", "deliberate absence"]


def kind_of(part: str) -> str:
    """One provenance clause -> one kind of data. The rule is printed in the Appendix G note."""
    p = part.lower()
    hits = []
    if "real snapshot" in p:
        hits.append("real readings")
    if "generated" in p:
        hits.append("generated series")
    if "constructed register" in p or "estimate" in p:
        hits.append("constructed record")
    if re.search(r"\b(none|absent|no)\b", p):
        hits.append("deliberate absence")
    if len(hits) != 1:
        die(f"task_bank.csv provenance clause maps to {hits!r}, not one kind: {part!r}")
    return hits[0]


def kinds_of(provenance: str) -> list:
    found = {kind_of(p.strip()) for p in provenance.split("|") if p.strip()}
    return [k for k in KIND_ORDER if k in found]


# ---------------------------------------------------------------- table writer
def float_lines(label: str, caption: str, colspec: str, header: list, rows: list, note: str, size: str) -> list:
    lines = [r"\begin{table}[tbp]", r"\centering", size, r"\caption{" + caption + "}", r"\label{" + label + "}",
             r"\begin{tabular}{" + colspec + "}", r"\toprule", " & ".join(header) + r" \\", r"\midrule"]
    for r in rows:
        if r[0] == "head":
            lines.append(r"\multicolumn{" + str(len(header)) + r"}{@{}l}{\emph{" + r[1] + r"}} \\")
        elif r[0] == "raw":
            lines.append(r[1])
        else:
            lines.append(" & ".join(r[1]) + r" \\")
    lines += [r"\bottomrule", r"\end{tabular}"]
    if note:
        lines.append(r"\par\smallskip\parbox{\linewidth}{\footnotesize " + note + "}")
    lines += [r"\end{table}", ""]
    return lines


def write_table(name: str, label: str, caption: str, colspec: str, header: list, rows: list, note: str,
                csv_rows: list = None, size: str = r"\small", parts: list = None) -> None:
    """rows: list of ('head', text) or ('row', [cells as LaTeX]); csv_rows: the same cells as plain text.

    parts: optional [(label, caption, rows, note), ...] to write one table as several consecutive floats (a float taller
    than a page is clipped); the CSV twin and the notes file then cover every part."""
    lines = [f"% {name}.tex -- generated by paper/scripts/make_draft_study_tables.py; do not edit by hand "
             "(re-run the script)."]
    if parts is None:
        parts = [(label, caption, rows, note)]
    for (lab, cap, rws, nt) in parts:
        lines += float_lines(lab, cap, colspec, header, rws, nt, size)
    with open(os.path.join(OUT, name + ".tex"), "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(lines))
    with open(os.path.join(OUT, name + ".csv"), "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh, lineterminator="\n")
        w.writerow([re.sub(r"\\l(W|WL|FD|U|OT)\{\}", r"\1", re.sub(r"\$\\kappa\$", "kappa", h)) for h in header])
        for r in (csv_rows if csv_rows is not None else []):
            w.writerow(r)
    with open(os.path.join(OUT, name + "_notes.txt"), "w", encoding="utf-8", newline="\n") as fh:
        for (lab, cap, rws, nt) in parts:
            fh.write(f"{lab} caption: " + cap + "\n" + (f"{lab} note: " + nt + "\n" if nt else ""))


def split_deviations(n_parts: int) -> None:
    """generated/study_v9/tab_deviations.tex is one float about two pages tall (v9 clipped it: 'Float too large').
    Write the same rows, unchanged, as n_parts consecutive floats in \\footnotesize, split where the estimated heights
    balance. Its CSV twin stays study_v9/tab_deviations.csv."""
    src = io.open(DEV_TEX, encoding="utf-8").read().replace("\r\n", "\n")
    m = re.search(r"\\caption\{(.*?)\}\n\\label\{tab:deviations\}\n\\begin\{tabular\}\{(.*)\}\n\\toprule\n(.*?)\n"
                  r"\\midrule\n(.*?)\n\\bottomrule", src, re.S)
    if not m:
        die("tab_deviations.tex: layout not recognised (has build_article_assets.py changed it?)")
    caption, colspec, header, body = m.groups()
    rows = body.split("\n")
    if not all(r.endswith(r" \\") for r in rows):
        die("tab_deviations.tex: a row spans several lines")
    widths = [float(w) for w in re.findall(r"p\{([\d.]+)cm\}", colspec)]
    if len(widths) != header.count("&") + 1:
        die("tab_deviations.tex: column widths not recognised")

    def height(row: str) -> int:
        cells = row[:-3].split(" & ")
        return max(-(-len(re.sub(r"\\[a-zA-Z]+|[{}]", "", c)) // int(w * 6.0)) for c, w in zip(cells, widths))

    hs = [height(r) for r in rows]
    total, cut, acc, parts = sum(hs), [], 0, []
    for i, h in enumerate(hs):
        acc += h
        if len(cut) < n_parts - 1 and acc >= total * (len(cut) + 1) / n_parts:
            cut.append(i + 1)
    bounds = [0] + cut + [len(rows)]
    for k in range(n_parts):
        lab = "tab:deviations" if k == 0 else ("tab:deviations-cont" if k == 1 else f"tab:deviations-cont{k}")
        cap = caption if k == 0 else caption.rstrip(".") + " (continued)."
        parts.append((lab, cap, [("raw", r) for r in rows[bounds[k]:bounds[k + 1]]], ""))
    lines = ["% tab_deviations_split.tex -- generated by paper/scripts/make_draft_study_tables.py from "
             "paper/generated/study_v9/tab_deviations.tex; rows unchanged, split into consecutive floats so that none is "
             "taller than a page. Do not edit by hand."]
    hdr = header[:-3].split(" & ") if header.endswith(r" \\") else header.split(" & ")
    for (lab, cap, rws, nt) in parts:
        lines += float_lines(lab, cap, colspec, hdr, rws, nt, r"\footnotesize")
    with open(os.path.join(OUT, "tab_deviations_split.tex"), "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(lines))


def kci(k: str, ci: str = "") -> str:
    """'0.48' and '0.28--0.69' -> '0.48 [0.28, 0.69]'."""
    if not ci:
        return k
    lo, hi = re.split(r"-{2,3}", ci)
    return f"{k} [{lo}, {hi}]"


def label_counts(d: dict) -> str:
    return ", ".join(f"{lab} {d.get(lab, 0)}" for lab in LABELS)


def f3_counts(d: dict) -> str:
    return " / ".join(str(d.get(v, 0)) for v in ("specified", "missing", "n/a"))


# ---------------------------------------------------------------- main
def main() -> int:
    for p in (AGREE_CSV, AFFECTED_MD, RESULTS_CSV, TASK_BANK, NUMBERS_TEX, PARTA_CSV, RQ1_CSV, FIRSTQ_CSV, E2_CSV,
              TIMING_CSV, LME4_TXT, BLIND_CSV, QUAL_CSV, LIVE_BOTH_CSV, CONFUSION_CSV):
        if not os.path.exists(p):
            die(f"missing input {p}")
    os.makedirs(OUT, exist_ok=True)
    ag = read_agreement()
    af = read_affected()
    res = read_results()
    bank = read_task_bank()
    have = existing_keys()

    def A(key: str) -> str:
        if key not in ag:
            die(f"numbers_agreement.csv has no {key}")
        return ag[key]

    def R(key: str) -> str:
        if key not in res:
            die(f"results_numbers.csv has no {key}")
        return res[key]["value"]

    # cross-check: the two agreement sources must agree wherever both give a kappa
    checks = [(("live", "label"), "AGREE_live_kappa")]
    for mat in ("partA", "mixed"):
        for f in ("F3a", "F3b", "F3c"):
            checks.append(((mat, f), f"AGREE_{mat}_kappa_{f}"))
    for (key, akey) in checks:
        if key in af and af[key]["kappa"] != A(akey):
            die(f"kappa disagrees between affected_fields.md {key} ({af[key]['kappa']}) and {akey} ({A(akey)})")
    for code, d in af.items():
        if code[0] == "reasons" and d["kappa"] not in ("undefined",) and d["kappa"] != A(f"AGREE_reasons_kappa_{code[1]}"):
            die(f"kappa disagrees for reason code {code[1]}")

    srcs = {"ag": f"{rel(AGREE_CSV)} (sha256 {sha(AGREE_CSV)})", "af": f"{rel(AFFECTED_MD)} (sha256 {sha(AFFECTED_MD)})",
            "res": f"{rel(RESULTS_CSV)} (sha256 {sha(RESULTS_CSV)})", "tb": f"{rel(TASK_BANK)} (sha256 {sha(TASK_BANK)})"}
    for tag, path in (("nt", NUMBERS_TEX), ("pa", PARTA_CSV), ("rq1", RQ1_CSV), ("fq", FIRSTQ_CSV), ("e2", E2_CSV),
                      ("tm", TIMING_CSV), ("lme", LME4_TXT), ("bl", BLIND_CSV), ("ql", QUAL_CSV)):
        srcs[tag] = f"{rel(path)} (sha256 {sha(path)})"
    sv = sv_values()

    def S(key: str) -> str:
        if key not in sv:
            die(f"numbers.tex has no {key}")
        return sv[key]

    # ------------------------------------------------------------ extra macros
    macros = OrderedDict()

    def mac(key: str, value, desc: str, src: str) -> None:
        if key in have:
            die(f"key {key} already exists in numbers.tex")
        if key in macros:
            die(f"duplicate key {key}")
        macros[key] = (str(value), desc, srcs[src])

    kinds = OrderedDict((r["form"], kinds_of(r["provenance"])) for r in bank)
    mac("TB_forms_study", len(bank), "study forms in the task bank", "tb")
    for kind, key in (("real readings", "real"), ("generated series", "generated"),
                      ("constructed record", "constructed"), ("deliberate absence", "absence")):
        mac(f"TB_forms_{key}_any", sum(kind in ks for ks in kinds.values()),
            f"study forms whose key rests at least in part on {kind}", "tb")
    mac("TB_forms_no_real", sum("real readings" not in ks for ks in kinds.values()),
        "study forms whose key rests on no real readings", "tb")
    mac("TB_forms_absence_only", sum(ks == ["deliberate absence"] for ks in kinds.values()),
        "study forms whose key rests only on a deliberate absence", "tb")

    live = af[("live", "label")]
    if live["n"] != int(A("AGREE_live_n")):
        die("live n differs between the agreement sources")
    mac("AGX_live_agree_k", live["agree_k"], "live answers both coders labelled the same", "af")
    for who, d in (("c1", live["c1"]), ("c2", live["c2"])):
        if sum(d.values()) != live["n"]:
            die(f"live label counts for {who} do not sum to n")
        for lab in LABELS:
            mac(f"AGX_live_{who}_{lab}", d.get(lab, 0),
                f"live answers in the double-coded sample labelled {lab} by the "
                f"{'first author' if who == 'c1' else 'second coder'}", "af")
    for code in ("LIMIT_MATCH", "DECLINE_ACCEPTED"):
        d = af[("reasons", code)]
        mac(f"AGX_reasons_{code}_c1", d["c1"], f"double-coded reasons the first author coded {code}", "af")
        mac(f"AGX_reasons_{code}_c2", d["c2"], f"double-coded reasons the second coder coded {code}", "af")
        mac(f"AGX_reasons_{code}_pct", d["pct"], f"double-coded reasons on which the coders agreed for {code} (%)",
            "af")
    for mat in ("partA", "mixed"):
        for f in ("F3a", "F3b", "F3c"):
            mac(f"AGX_{mat}_{f}_pct", af[(mat, f)]["pct"], f"{mat}: % of double-coded rows with the same {f}", "af")

    forms_k = {k[5:-4]: v["value"] for k, v in res.items() if re.fullmatch(r"FORM_S\d-\d_k_n", k)}
    if len(forms_k) != len(bank):
        die("results_numbers.csv: per-form counts do not cover the twelve forms")
    mac("FORMS_none_correct", sum(v.split("/")[0] == "0" for v in forms_k.values()),
        "study forms on which no decision was correct (from FORM_*_k_n)", "res")

    # -------- decisions by where the first question was asked (deviations table: 'exploratory split')
    fq = {r["first_question_on"]: r for r in read_csv_rows(FIRSTQ_CSV)}
    for page, key, macro in (("goal", "goal", "first_q_goal_n"), ("decision", "visible", "first_q_options_visible_n")):
        n = int(fq[page]["n"])
        if str(n) != S(macro):
            die(f"first_question_page.csv {page} n={n} differs from {macro}={S(macro)}")
        k = k_of(n, float(fq[page]["warranted_rate"]))
        mac(f"FQ_{key}_k_n", f"{k}/{n}", f"tasks whose first question was asked on the {page} page: correct/all", "fq")
        mac(f"FQ_{key}_pct", half_up(100 * k / n, 0), f"... the same as a percentage", "fq")

    # -------- decisions by the worst answer in the task (deviations table: 'worst-answer sensitivity')
    e2rows = read_csv_rows(E2_CSV)
    last = {r["label"]: r for r in e2rows if r["basis"] == "answer_received"}
    worst = {r["label"]: r for r in e2rows if r["basis"] == "answer_worst"}
    for lab in ("W", "WL", "FD", "U"):
        n, k = int(worst[lab]["n"]), int(worst[lab]["k_warranted"])
        mac(f"E2worst_{lab}_k_n", f"{k}/{n}", f"correct decisions when the worst answer in the task was {lab} "
            "(worst first: U, FD, OT, WL, W)", "e2")
        mac(f"E2worst_{lab}_pct", half_up(100 * k / n, 0), f"... the same as a percentage", "e2")
    rates = [int(worst[x]["k_warranted"]) / int(worst[x]["n"]) for x in ("W", "WL", "U", "FD")]
    if rates != sorted(rates, reverse=True):
        die("worst-answer rates no longer keep the order W > WL > U > FD; the text says they do")

    # -------- the decisions with no answer before deciding: why (Table rq3-e2 'none' against Table measures)
    tm = {r["answer_timing"]: int(r["n"]) for r in read_csv_rows(TIMING_CSV)}
    if tm["no_question"] + tm["decided_before_answer"] != int(last["none"]["n"]):
        die("no-question + decided-before-answer does not equal the E2 'none' row")
    if tm["no_question"] != int(S("beh_decisions")) - int(S("beh_tasks_with_question")):
        die("no-question tasks differ from decisions minus tasks with a question")
    mac("E2X_none_n", last["none"]["n"], "decisions with no answer before deciding (the E2 'none' row)", "e2")
    mac("beh_tasks_no_question", tm["no_question"], "tasks with no question asked", "tm")
    mac("beh_decided_before_answer", tm["decided_before_answer"],
        "tasks with a question whose decision was submitted before the first answer arrived", "tm")

    # -------- values already printed, rounded so one sentence uses one precision
    lo_hi = S("E2sens_FD_range").split("--")
    if len(lo_hi) != 2 or lo_hi[0] != lo_hi[1]:
        die("E2sens_FD_range no longer collapses to one value; the text says it stays put")
    mac("E2sens_FD_value", lo_hi[0], "% correct after FD, the same in every label variant (E2sens_FD_range)", "nt")
    mac("lme4_noS3_form_sd_r", half_up(S("lme4_noS3_form_sd"), 2), "lme4_noS3_form_sd to two decimals", "nt")
    for c in ("C1", "C2", "C3"):
        mac(f"P3_holm_p_{c}", half_up(S(f"holm_p_{c}"), 3), f"holm_p_{c} to three decimals", "nt")
    lme = io.open(LME4_TXT, encoding="utf-8").read().split("====")[2]   # [1] is the first model's header line
    m = re.search(r"S2 / S1\s+([\d.]+)\s+\S+\s+Inf\s+1\s+[\d.-]+\s+([\d.]+)", lme)
    if not m or m.group(1) != S("lme4_noS3_S2_OR") or half_up(m.group(2), 2) != S("lme4_noS3_S2_p"):
        die("lme4_sensitivity_without_S3.txt: S2/S1 contrast not found or differs from numbers.tex")
    mac("P3_lme4_noS3_S2_p", half_up(m.group(2), 3), "lme4_noS3_S2_p to three decimals, from the unrounded output", "lme")
    for key in ("comparison_A_vs_B_mcnemar_U", "T-LIVE_A_vs_B_mcnemar_U", "T-FRESH_A_vs_B_mcnemar_U",
                "comparison_A_vs_Aminus_mcnemar_U", "comparison_Aminus_vs_B_mcnemar_U"):
        m = re.fullmatch(r"(\d+) vs (\d+), p=([\d.]+)", S(key))
        if not m:
            die(f"{key} is not 'a vs b, p=x': {S(key)!r}")
        mac(f"MCN_{key}_counts", f"{m.group(1)} against {m.group(2)}", f"{key}: discordant questions", "nt")
        mac(f"MCN_{key}_p", half_up(m.group(3), 3), f"{key}: exact p to three decimals", "nt")

    # -------- the second coder's system guesses, by system (Limitations)
    bl = {r["system"]: r for r in read_csv_rows(BLIND_CSV) if r["coder"] == "coder2_pass2"}
    if f"{bl['all']['correct']} of {bl['all']['guessed']}" not in S("blinding_coder2_pass2_correct"):
        die("blinding_check.csv differs from blinding_coder2_pass2_correct")
    if any(int(bl[s]["cant_tell"]) for s in bl):
        die("the second coder answered 'can't tell'; the counts below assume a guess for every answer")
    mac("BLIND_all_k_n", f"{bl['all']['correct']} of {bl['all']['guessed']}",
        "offline answers whose system family the second coder named correctly (all systems)", "bl")
    for s, key in (("A", "A"), ("A-minus", "Aminus"), ("B", "B")):
        mac(f"BLIND_{key}_k_n", f"{bl[s]['correct']} of {bl[s]['guessed']}",
            f"offline answers from {s} whose system family the second coder named correctly", "bl")
    onto_n = int(bl["A"]["guessed"]) + int(bl["A-minus"]["guessed"])
    onto_k = int(bl["A"]["correct"]) + int(bl["A-minus"]["correct"])
    b_named_onto = int(bl["B"]["guessed"]) - int(bl["B"]["correct"])
    mac("BLIND_named_onto_for_onto", f"{onto_k} of {onto_n}",
        "OntoSage+-family answers (both configurations) the second coder said OntoSage+ wrote", "bl")
    mac("BLIND_named_onto_for_B", f"{b_named_onto} of {bl['B']['guessed']}",
        "Assistant B answers the second coder said OntoSage+ wrote", "bl")

    # -------- 'useful: the evidence and sources' by closing question (qual_people_useful_evidence counts any of them)
    qc = {(r["material"], r["code"]): int(r["people"]) for r in read_csv_rows(QUAL_CSV)}
    for cl in ("CL1", "CL2"):
        mac(f"qual_{cl}_people_useful_evidence", qc.get((cl, "USEFUL_EVIDENCE"), 0),
            f"participants coded 'useful: the evidence and sources' in closing question {cl}", "ql")

    # -------- own questions against the 400 Part A questions (Section 6, the two corpus estimates)
    pa = {r["key"]: r["value"] for r in read_csv_rows(PARTA_CSV)}
    rq1 = {(r["field"], r["value"]): r for r in read_csv_rows(RQ1_CSV)}
    for field, value, short in (("F2_evidence_source", "description", "F2"), ("F2_evidence_source", "external", "F2"),
                                ("F4_evidence_relation", "direct", "F4"),
                                ("F4_evidence_relation", "not_establishable", "F4")):
        r = rq1[(field, value)]
        own, c90 = 100 * float(r["fresh_share"]), 100 * float(r["corpus_share"])
        pkey = f"PA_{short}_{value}_pct"
        if pa[pkey] != S(pkey):
            die(f"{pkey} differs between numbers_partA.csv and numbers.tex")
        mtx = re.match(r"(\d+)\\% vs (\d+)\\%", S(f"rq1_{short}_{value}_fresh_vs_corpus"))
        if not mtx or (mtx.group(1), mtx.group(2)) != (half_up(own, 0), half_up(c90, 0)):
            die(f"fresh_vs_corpus.csv {value} differs from rq1_{short}_{value}_fresh_vs_corpus")
        mac(f"RQ1X_{value}_own", half_up(own, 0), f"own questions coded {short}={value} (%)", "rq1")
        mac(f"RQ1X_{value}_corpus90", half_up(c90, 0), f"the 90 corpus questions coded {short}={value} (%)", "rq1")
        mac(f"RQ1X_{value}_own_minus_partA", signed(own - float(pa[pkey])),
            f"own share minus the stage-weighted Part A share for {short}={value} (points; two estimates from "
            "separate samples and coding passes, no interval)", "rq1")

    # ------------------------------------------------------------ agreement rows (shared by both tables)
    def k_or_dash(key: str) -> str:
        v = A(key)
        return v if v not in ("", "n/a") else "not defined"

    reason_names = OrderedDict([
        ("LIMIT_RECOGNISED", "named a limit of the answer"),
        ("LIMIT_MATCH", "the limit named is the key's limit"),
        ("DECLINE_ACCEPTED", "took a refusal as the answer"),
        ("EVIDENCE_CITED", "cited what the answer showed"),
        ("VERIFY_INTENDED", "would check elsewhere"),
        ("REPHRASED", "asked again in other words"),
        ("FLUENCY_CUE", "trusted detail or a confident tone"),
        ("DECLINE_FRUSTRATION", "frustrated by a refusal"),
        ("PROXY_ACCEPTED", "accepted a related reading"),
        ("PRIOR_KNOWLEDGE", "went on prior knowledge"),
        ("GUESS", "guessed"),
        ("OTHER", "other"),
    ])
    question_fields = OrderedDict([
        ("F1", ("operation asked for (mean Jaccard)", "jaccard")),
        ("F2", ("what a complete answer needs (mean Jaccard)", "jaccard")),
        ("F3a", ("names the place", "kappa")),
        ("F3b", ("gives the time", "kappa")),
        ("F3c", ("defines the criterion", "kappa")),
        ("F4", ("could the building's data establish it", "kappa")),
        ("F5", ("answerable in principle", "kappa")),
        ("F6", ("states a purpose", "kappa")),
    ])

    def low(k: str) -> bool:
        try:
            return float(k) < THRESHOLD
        except ValueError:
            return False

    def build(full: bool):
        tex_rows, csv_rows = [], []

        def head(t: str) -> None:
            tex_rows.append(("head", tex(t)))
            csv_rows.append([t, "", "", "", "", ""])

        def row(field: str, n, k: str, same: str, c1: str, c2: str) -> None:
            cells = [field, str(n), k, same, c1, c2]
            tex_rows.append(("row", [tex(c) for c in cells]))
            csv_rows.append(cells)

        head("Answers participants received (RQ3)")
        n = A("AGREE_live_n")
        row("answer label", n, kci(A("AGREE_live_kappa"), A("AGREE_live_kappa_ci")), A("AGREE_live_pct") + "%",
            label_counts(live["c1"]), label_counts(live["c2"]))
        row("U against every other label", n, A("AGREE_live_kappa_U"), "", "", "")
        if full:
            row("labelled differently, each discussed against the rubric", A("AGREE_live_disagreed"), "", "",
                f"kept: {A('AGREE_live_discussed_coder1')}", f"taken: {A('AGREE_live_discussed_coder2')}")
        head("Offline answers (RQ2)")
        n = A("AGREE_offline_n")
        row("answer label", n, kci(A("AGREE_offline_kappa"), A("AGREE_offline_kappa_ci")),
            A("AGREE_offline_pct") + "%", "", "")
        row("U against every other label", n, A("AGREE_offline_kappa_U"), "", "", "")
        if full:
            row("labelled differently, settled by the rule", A("AGREE_offline_disagreed"), "", "",
                f"kept: {A('AGREE_offline_disputed')}", "")
        head("Reasons participants wrote (RQ3)")
        n = A("AGREE_reasons_n")
        lo, hi = re.split(r"-{2,3}", A("AGREE_reasons_kappa_range"))
        row("all codes: median (lowest to highest)", n, f"{A('AGREE_reasons_kappa_median')} ({lo} to {hi})",
            A("AGREE_reasons_pct") + "% of cells", "", "")
        shown = list(reason_names) if full else ["LIMIT_RECOGNISED", "LIMIT_MATCH", "DECLINE_ACCEPTED",
                                                 "EVIDENCE_CITED", "VERIFY_INTENDED"]
        zero_codes = [c for c in reason_names if A(f"AGREE_reasons_kappa_{c}") == "0.00"]
        for code in shown:
            k = k_or_dash(f"AGREE_reasons_kappa_{code}")
            d = af.get(("reasons", code))
            if d and (low(k) or k == "not defined"):
                row(reason_names[code], n, k, f"{d['pct']}%", f"ticked {d['c1']}", f"ticked {d['c2']}")
            else:
                if low(k):
                    die(f"reason code {code} is below {THRESHOLD} but affected_fields.md gives no counts")
                row(reason_names[code], n, k, "", "", "")
        if not full:
            ds = [af[("reasons", c)] for c in zero_codes]
            if len({(d["pct"], d["c1"], d["c2"]) for d in ds}) != 1:
                die("the codes with kappa 0.00 differ in their counts; list them separately")
            d = ds[0]
            row("; ".join(reason_names[c] for c in zero_codes), n, "0.00 each", f"{d['pct']}% each",
                f"ticked {d['c1']} each", f"ticked {d['c2']} each")
        if full:
            row("reasons coded differently, settled by the rule", A("AGREE_reasons_disagreed"), "", "",
                f"kept: {A('AGREE_reasons_disputed')}", "")
        for mat, title in (("partA", "Survey questions, Part A (RQ1)"),
                           ("mixed", "Participants' own and corpus questions, mixed (RQ1)")):
            head(title)
            n = A(f"AGREE_{mat}_n")
            fields = list(question_fields) if full else ["F2", "F3a", "F3b", "F3c", "F4", "F5"]
            for f in fields:
                name, kind = question_fields[f]
                if kind == "jaccard":
                    row(name, n, A(f"AGREE_{mat}_jaccard_{f}") + " (J)", "", "", "")
                    continue
                k = A(f"AGREE_{mat}_kappa_{f}")
                d = af.get((mat, f))
                if d:
                    if d["agree_n"] != int(n):
                        die(f"{mat} {f}: n differs between the agreement sources")
                    c1 = f3_counts(d["c1"]) if low(k) else ""
                    c2 = f3_counts(d["c2"]) if low(k) else ""
                    row(name, n, k, f"{d['pct']}%", c1, c2)
                else:
                    if low(k):
                        die(f"{mat} {f} is below {THRESHOLD} but affected_fields.md gives no counts")
                    row(name, n, k, "", "", "")
            if full:
                row("questions coded differently, settled by the rule", A(f"AGREE_{mat}_disagreed"), "", "",
                    f"kept: {A(f'AGREE_{mat}_disputed')}", "")
        head("Stage 5 answers (RQ1)")
        row("every code", "", "no second coder", "", "", "")
        if full:
            head("All materials")
            row("items labelled or coded differently", A("AGREE_all_disagreed"), "", "",
                f"kept by the rule: {A('AGREE_all_disputed')}", "")
        return tex_rows, csv_rows

    header = ["Material and field", "n", r"$\kappa$ [95\% CI]", "Same", "First author", "Second coder"]
    colspec = (r"@{}>{\raggedright\arraybackslash\leftskip=0.8em}p{3.5cm}r>{\raggedright\arraybackslash}p{2.2cm}"
               r">{\raggedright\arraybackslash}p{1.0cm}>{\raggedright\arraybackslash}p{2.3cm}"
               r">{\raggedright\arraybackslash}p{2.3cm}@{}")
    note_common = (
        "Agreement between the second coder and the first author's reviewed labels and codes, on the seeded samples "
        "the second coder labelled without seeing any other label. $\\kappa$: Cohen's kappa; a 95\\% interval "
        "(bootstrap) was computed for the two answer-label sets only. Same: the share of items (for the reasons, of "
        "code cells) given the same value. (J): mean Jaccard similarity of the two coders' sets of codes, for the two "
        "fields that take several codes. First author and second coder: how often each used the value, given for "
        f"every field below {THRESHOLD:.2f}; for answer labels, the number of answers given each label; for reason "
        "codes, the number of the reasons each coder ticked; for place, time and criterion, the number coded "
        "specified / missing / n/a. A $\\kappa$ of 0.00 with most items the same arises when one coder used a code "
        "once and the other never.")
    t_rows, c_rows = build(full=False)
    write_table("tab_agreement", "tab:agreement",
                "Agreement between the two coders, by material and field.",
                colspec, header, t_rows,
                note_common + r" Every field, and how the disagreements were settled: Appendix~\ref{app:agreement}.",
                c_rows, size=r"\footnotesize\setlength{\tabcolsep}{4pt}")
    t_rows, c_rows = build(full=True)
    cut = next(k for k, r in enumerate(t_rows) if r[0] == "head" and r[1].startswith("Survey questions"))
    note_full = (note_common + " In the rows on settling, n is the number of items the coders labelled or coded "
                 "differently; kept: those that kept the first author's label or code; taken: those settled in the "
                 "second coder's favour. For the live answers every disagreement was discussed one by one "
                 "against the rubric; for the other materials a disagreement kept the first author's label or code "
                 r"by a rule agreed before either set was compared (Appendix~\ref{app:deviations}).")
    write_table("tab_agreement_full", "", "", colspec, header, [], "", c_rows,
                size=r"\footnotesize\setlength{\tabcolsep}{4pt}",
                parts=[("tab:agreement-full",
                        "Agreement between the two coders for every field, and how the disagreements were settled: "
                        "the answers and the reasons.", t_rows[:cut], note_full),
                       ("tab:agreement-full-q",
                        "Agreement between the two coders for every field, and how the disagreements were settled: "
                        "the questions, the Stage 5 answers, and all materials together.", t_rows[cut:],
                        r"Notes as for Table~\ref{tab:agreement-full}.")])
    split_deviations(2)

    # ------------------------------------------------------------ results on the second coder's labels
    c2_rows_tex, c2_rows_csv = [], []

    def head2(t: str) -> None:
        c2_rows_tex.append(("head", tex(t)))
        c2_rows_csv.append([t, "", ""])

    def row2(what: str, reported: str, c2: str) -> None:
        c2_rows_tex.append(("row", [tex(what), tex(reported), tex(c2)]))
        c2_rows_csv.append([what, reported, c2])

    head2(f"Correct decisions by the last answer received (live labels, kappa {A('AGREE_live_kappa')})")
    names = {"W": "after W (supported by the data)", "WL": "after WL (states its limits)",
             "FD": "after FD (wrong refusal)", "U": "after U (not supported by the data)",
             "OT": "after OT (answers something else)", "none": "no answer before deciding"}
    for lab in LABELS + ["none"]:
        kn = R(f"E2_{lab}_k_n")
        pct = res.get(f"E2_{lab}_pct", {}).get("value", "")
        reported = f"{kn} ({pct}%)" if pct else kn
        row2(names[lab], reported, f"{R(f'SENS_C2_E2_{lab}_pct')}% of {R(f'SENS_C2_E2_{lab}_n')}")
    head2(f"Reasons that named a limit (kappa {A('AGREE_reasons_kappa_LIMIT_RECOGNISED')}) and whether it was the "
          f"key's limit (kappa {A('AGREE_reasons_kappa_LIMIT_MATCH')})")
    row2("reasons that named a limit", R("qual_reasons_limit_named"), R("SENS_C2_qual_reasons_limit_named"))
    row2("of which the key's limit", R("qual_reasons_limit_matches_key"), R("SENS_C2_qual_reasons_limit_matches_key"))
    for s in ("S1", "S2", "S3", "S4"):
        row2(f"{s}: the key's limit, of those naming a limit",
             f"{R(f'LIM_situation_{s}_match')} of {R(f'LIM_situation_{s}_named')}",
             f"{R(f'SENS_C2_LIM_situation_{s}_match')} of {R(f'SENS_C2_LIM_situation_{s}_named')}")
    head2(f"Reasons that took a refusal as the answer (kappa {A('AGREE_reasons_kappa_DECLINE_ACCEPTED')})")
    row2("after a wrong refusal (FD)", f"{R('qual_after_FD_decline_accepted')} of {R('qual_after_FD_n')}",
         f"{R('SENS_C2_qual_after_FD_decline_accepted')} of {R('SENS_C2_qual_after_FD_n')}")
    row2("after a correct refusal or a stated limit (WL)",
         f"{R('qual_after_WL_decline_accepted')} of {R('qual_after_WL_n')}",
         f"{R('SENS_C2_qual_after_WL_decline_accepted')} of {R('SENS_C2_qual_after_WL_n')}")
    write_table("tab_agreement_c2", "tab:agreement-c2",
                "The results that rest on the fields with the lowest agreement, as reported and with the second "
                "coder's labels or codes.",
                r"@{}>{\raggedright\arraybackslash\leftskip=0.8em}p{6.0cm}>{\raggedright\arraybackslash}p{2.9cm}"
                r">{\raggedright\arraybackslash}p{3.2cm}@{}",
                ["Result", "As reported", "Second coder's labels or codes"], c2_rows_tex,
                f"As reported: the agreed labels and codes behind the results in \\S\\ref{{sec:rq3}}. Second "
                f"coder's labels: the same "
                f"computation with the second coder's label or codes put in place of the agreed one for each item the "
                f"second coder coded ({R('SENS_C2_live_n_swapped')} live answers, {R('SENS_C2_qual_n_swapped')} "
                f"reasons); every "
                f"other item keeps its agreed label or code. Percentages of decisions that were correct.",
                c2_rows_csv, size=r"\small")

    # ------------------------------------------------------------ live labels, coder by coder (Appendix E)
    both = [r for r in read_csv_rows(LIVE_BOTH_CSV) if r["label_coder1"].strip() and r["label_coder2"].strip()]
    pairs = {}
    for r in both:
        k = (r["label_coder1"].strip(), r["label_coder2"].strip())
        pairs[k] = pairs.get(k, 0) + 1
    if any(a not in LABELS or b not in LABELS for (a, b) in pairs):
        die(f"agreed_draft.csv: a label outside {LABELS}")
    with io.open(CONFUSION_CSV, encoding="utf-8") as fh:
        conf = {r["label_a"]: {c: int(v) for c, v in r.items() if c != "label_a"} for r in csv.DictReader(fh)}
    for a in LABELS:
        for b in LABELS:
            if pairs.get((a, b), 0) != conf.get(a, {}).get(b, 0):
                die(f"confusion.csv and agreed_draft.csv disagree on first author {a}, second coder {b}")
    live = af[("live", "label")]
    n_both = sum(pairs.values())
    same = sum(pairs.get((x, x), 0) for x in LABELS)
    if n_both != int(A("AGREE_live_n")) or same != live["agree_k"]:
        die("the live crosstab does not reproduce AGREE_live_n or the raw agreement in affected_fields.md")
    for x in LABELS:
        if sum(pairs.get((x, b), 0) for b in LABELS) != live["c1"].get(x, 0) or \
                sum(pairs.get((a, x), 0) for a in LABELS) != live["c2"].get(x, 0):
            die(f"the live crosstab's totals for {x} differ from affected_fields.md")
    w_wl = pairs.get(("W", "WL"), 0) + pairs.get(("WL", "W"), 0)
    lmac = {x: "\\l" + x + "{}" for x in LABELS}
    cf_tex, cf_csv = [], []
    for a in LABELS:
        cells = [str(pairs.get((a, b), 0)) for b in LABELS]
        tot = str(sum(pairs.get((a, b), 0) for b in LABELS))
        cf_tex.append(("row", [lmac[a]] + cells + [tot]))
        cf_csv.append([a] + cells + [tot])
    col_tot = [str(sum(pairs.get((a, b), 0) for a in LABELS)) for b in LABELS]
    cf_tex.append(("raw", r"\midrule"))
    cf_tex.append(("row", ["Total"] + col_tot + [str(n_both)]))
    cf_csv.append(["Total"] + col_tot + [str(n_both)])
    write_table("tab_live_confusion", "tab:live-confusion",
                "The live answers both coders labelled: the first author's label against the second coder's.",
                r"@{}lcccccc@{}",
                ["First author", r"\lW{}", r"\lWL{}", r"\lFD{}", r"\lU{}", r"\lOT{}", "Total"], cf_tex,
                f"Rows: the first author's label; columns: the second coder's, before the disagreements were settled. "
                f"The coders gave the same label to {same} of the {n_both} answers (the diagonal). Of the "
                f"{n_both - same} they labelled differently, {w_wl} lie between \\lW{{}} and \\lWL{{}}.",
                cf_csv, size=r"\small")

    # ------------------------------------------------------------ task sources (Appendix G)
    ts_tex, ts_csv = [], []
    for r in bank:
        key = r["key_answer"]
        ks = kinds[r["form"]]
        q = r["canonical_question"]
        ts_tex.append(("row", [tex(r["form"]), tex(q) + r" \emph{Key:} " + tex(key),
                               tex(r["provenance"].replace(" | ", "; ")), tex(", ".join(ks))]))
        ts_csv.append([r["form"], q + " Key: " + key, r["provenance"], ", ".join(ks)])
    write_table("tab_task_sources", "tab:task-sources",
                "What each task's key rests on.",
                r"@{}l>{\raggedright\arraybackslash}p{5.2cm}>{\raggedright\arraybackslash}p{3.7cm}"
                r">{\raggedright\arraybackslash}p{2.0cm}@{}",
                ["Form", "Question (researchers' wording) and key", "What the key rests on", "Kind of data"],
                ts_tex,
                "From the task bank frozen on 14 October 2026: each form's question in the researchers' wording, the "
                "answer its key fixes, and its provenance as the bank records it. Kind of data, assigned from that "
                "text by rule: a clause naming the real snapshot is real readings; one naming generated data, "
                "generated series; one naming a constructed register or the building's own estimate, a constructed "
                "record; one stating that nothing is held (none, absent, no), a deliberate absence.",
                ts_csv, size=r"\footnotesize")

    # ------------------------------------------------------------ situations (Method)
    examples = OrderedDict([("S1", ("S1-1", "the whole answer")),
                            ("S2", ("S2-2", "part of the answer, or only a related quantity")),
                            ("S3", ("S3-3", "nothing that answers it")),
                            ("S4", ("S4-1", "two facts that must be combined"))])
    by_form = {r["form"]: r for r in bank}
    si_tex, si_csv = [], []
    for sit, (form, holds) in examples.items():
        r = by_form[form]
        if r["situation"] != sit:
            die(f"{form} is not in {sit}")
        first = r["warranted_options"].split()[0]
        key = r[f"option_{first}"]
        si_tex.append(("row", [sit, tex(holds), tex(form) + ": " + tex(r["canonical_question"]) + r" \emph{Key:} "
                               + tex(key) + "."]))
        si_csv.append([sit, holds, f"{form}: {r['canonical_question']} Key: {key}."])
    write_table("tab_situations", "tab:situations",
                "The four situations. A decision is \\emph{correct} when it is the option the building's data "
                "support, fixed in the key before the study. In S3 both ``not recorded'' and ``I could not find "
                "out'' are correct.",
                r"@{}l>{\raggedright\arraybackslash}p{3.2cm}>{\raggedright\arraybackslash}p{7.8cm}@{}",
                ["Situation", "What the data hold", "Example form: question (researchers' wording) and its key"],
                si_tex,
                "The key shown is the first correct option on the decision form, quoted from the task bank frozen on "
                r"14 October 2026; Appendix~\ref{app:task-sources} lists every form.",
                si_csv, size=r"\small")

    # ------------------------------------------------------------ Part A codes (Section 6)
    pa_names = {
        "F1": OrderedDict([("fact", "a fact: one value or attribute"), ("explain", "an explanation or cause"),
                           ("capability", "whether the building has or offers something"),
                           ("action", "an action in the world"), ("rank", "a ranking or choice"),
                           ("compare", "a comparison"), ("summarise", "a summary over a period or set"),
                           ("unclear", "cannot tell")]),
        "F2": OrderedDict([("measurement", "sensor readings"), ("description", "the building's description"),
                           ("document", "policies and manuals"), ("external", "outside knowledge"),
                           ("record", "dated records"), ("none", "no evidence, or cannot tell")]),
        "F4": OrderedDict([("direct", "yes, directly"), ("proxy", "only through a related quantity"),
                           ("not_establishable", "no building data could"), ("unclear", "cannot tell")]),
        "F5": OrderedDict([("yes", "yes"), ("partly", "partly"), ("no", "no")]),
    }
    groups = [("F1", "Operation the question asks for (several can apply)", True),
              ("F2", "What a complete answer needs (several can apply)", True),
              ("F4", "Could the building's data establish the answer?", False),
              ("F5", "Answerable in principle, in a typical instrumented building?", False)]
    n_rows = pa["PA_n_rows"]
    pa_tex, pa_csv = [], []

    def pa_row(name: str, key: str) -> None:
        for suffix in ("pct", "ci", "n"):
            if f"{key}_{suffix}" not in pa:
                die(f"numbers_partA.csv has no {key}_{suffix}")
        if pa[f"{key}_pct"] != S(f"{key}_pct"):
            die(f"{key}_pct differs between numbers_partA.csv and numbers.tex")
        lo, hi = pa[f"{key}_ci"].split("-")
        cells = [name, pa[f"{key}_pct"], f"[{lo}, {hi}]", pa[f"{key}_n"]]
        pa_tex.append(("row", [tex(c) for c in cells]))
        pa_csv.append(cells)

    for f, title, by_share in groups:
        pa_tex.append(("head", tex(title)))
        pa_csv.append([title, "", "", ""])
        vals = list(pa_names[f])
        known = {k.split("_", 2)[2].rsplit("_", 1)[0] for k in pa if k.startswith(f"PA_{f}_") and k.endswith("_pct")}
        if known != set(vals):
            die(f"Part A {f} values {sorted(known)} differ from the table's {sorted(vals)}")
        if by_share:
            vals.sort(key=lambda v: -float(pa[f"PA_{f}_{v}_pct"]))
        for v in vals:
            pa_row(pa_names[f][v], f"PA_{f}_{v}")
    title = "What the question leaves out"
    pa_tex.append(("head", tex(title)))
    pa_csv.append([title, "", "", ""])
    for f, what in (("F3a", "a place it needs"), ("F3b", "a time it needs"), ("F3c", "a criterion it needs")):
        pa_row(f"{what} (kappa {A(f'AGREE_partA_kappa_{f}')})", f"PA_{f}_missing")
    title = "Purpose"
    pa_tex.append(("head", tex(title)))
    pa_csv.append([title, "", "", ""])
    pa_row("states why the asker wants to know", "PA_F6_yes")
    low_f3 = [w for f, w in (("F3a", "place"), ("F3b", "time"), ("F3c", "criterion"))
              if low(A(f"AGREE_partA_kappa_{f}"))]
    write_table("tab_partA_needs", "tab:partA-needs",
                f"What the {n_rows} coded survey questions ask for and what a complete answer to them needs (Part~A).",
                r"@{}>{\raggedright\arraybackslash\leftskip=0.8em}p{6.9cm}rlr@{}",
                ["Code", r"\% (stage-weighted)", r"95\% CI", "Questions"],
                pa_tex,
                f"Shares are weighted by each stage's share of the corpus; intervals are bootstrap intervals that "
                f"resample contributors (2,000 resamples); Questions: how many of the {n_rows} coded questions carry "
                f"the code. Operation and evidence can take several codes each, so their shares do not sum to 100\\%. "
                f"Codes: an AI model's proposals, each reviewed by the first author (\\S\\ref{{sec:method-labels}}); "
                f"agreement with the second coder on {A('AGREE_partA_n')} of the questions is in "
                f"Table~\\ref{{tab:agreement}}. The {' and '.join(low_f3)} fields agreed below {THRESHOLD:.2f}, so "
                f"those shares are the first author's coding alone.",
                pa_csv, size=r"\small")

    # ------------------------------------------------------------ the macros
    lines = [
        r"%% Extra study values for the expanded article, in the same \sv{} namespace as numbers.tex beside this file",
        r"%% (e.g. how many task keys rest on each kind of data). Generated by the drafting scripts named in",
        r"%% draft1Nov_work/table_sources_study.csv; do not edit by hand.",
        r"%% Written by paper/scripts/make_draft_study_tables.py (W5 has run): every value, its meaning and its source "
        r"file are in numbers_extra.csv.",
    ]
    for k, (v, d, s) in macros.items():
        lines.append(rf"\expandafter\def\csname sv@{k}\endcsname{{{v}}}% {d}")
    with open(os.path.join(OUT, "numbers_extra.tex"), "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(lines) + "\n")
    with open(os.path.join(OUT, "numbers_extra.csv"), "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh, lineterminator="\n")
        w.writerow(["key", "value", "description", "source"])
        for k, (v, d, s) in macros.items():
            w.writerow([k, v, d, s])
    print(f"{len(macros)} values -> numbers_extra.tex; tables: tab_agreement, tab_agreement_full, tab_agreement_c2, "
          f"tab_task_sources, tab_situations, tab_deviations_split, tab_partA_needs -> {rel(OUT)}/")
    for form, ks in kinds.items():
        print(f"  {form}: {', '.join(ks)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
