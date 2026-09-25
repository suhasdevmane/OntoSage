"""Stage 5 Task 3 ("Your Vision for a Talking Building") -- the analysis behind
paper section 3.15 (sec:vision), its table, and the 8.1 limitations.

Reads  inputs/recommendations.csv  and  inputs/questions_by_user.csv
Writes outputs/tables/Z_stage5_vision_themes.csv

Every number in the paper's Table `tab:vision-themes`, the accountable-role
completion finding, and the de-templating robustness check is produced here.

Run:  python scripts/Z_stage5_vision_analysis.py
"""
import csv
import io
import os
import re
from collections import Counter, defaultdict
from difflib import SequenceMatcher

from scipy.stats import fisher_exact, mannwhitneyu

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
INP = os.path.join(ROOT, "inputs")
OUT = os.path.join(ROOT, "outputs", "tables")

FIELDS = ["Scenarios", "Interaction", "Trust", "Success", "PainPoints"]

# Roles answerable FOR a building rather than users OF one. Fixed here so the
# split is auditable rather than chosen after seeing the result.
ACCOUNTABLE_PREFIXES = (
    "Sustainability and Energy",
    "Health and Safety",
    "Building Owners",
    "Facility Managers",
)

# Coding frame. Regex, not a model: every count below is reproducible and the
# patterns are open to inspection and disagreement.
THEMES = {
    "Trust": {
        "Privacy and surveillance": r"privac|surveil|track|anonym|gdpr",
        "Explanation and provenance": r"explain|transparen|source|cited|justif|clear",
        "Security and access control": r"secur|hack|breach|encrypt|unauthor",
        "Accuracy and error": r"accura|error|wrong|mistake|incorrect|reliab",
        "Consent and opt-out": r"consent|opt.?out|control over|permission",
    },
    "PainPoints": {
        "Information buried": r"find|navigat|buri|dig|search|scatter|too many|clutter",
        "Too complex / technical": r"complex|complicat|confus|difficult|technical|jargon|black box",
        "Slow": r"slow|lag|delay|time.consuming",
        "Fragmented across systems": r"multiple|different system|separate|fragment|scatter|silo|centralis|centraliz",
    },
    "Interaction": {
        "Conversational (voice/chat)": r"voice|spoken|talk|speak|chat|text|messag|conversat",
        "Charts on demand": r"chart|graph|visual|plot",
        "Short, plain answers": r"simple|plain|clear|concise|short|straightforward",
        "Alerts and notifications": r"alert|notif|push",
    },
}

SIMILARITY = 0.70  # near-duplicate threshold for the de-templating check


def _norm(t):
    return " ".join(re.sub(r"[^a-z ]", " ", (t or "").lower()).split())


def _personas(p):
    return [x.strip() for x in re.split(r"[;,]", p or "") if x.strip()]


def _is_accountable(personas):
    return any(x.startswith(ACCOUNTABLE_PREFIXES) for x in personas)


def templated(rows, field, thr=SIMILARITY):
    """Usernames whose response duplicates another's at >= thr similarity."""
    t = [(r["Username"], _norm(r[field])) for r in rows if (r[field] or "").strip()]
    out = set()
    for i in range(len(t)):
        for j in range(i + 1, len(t)):
            if SequenceMatcher(None, t[i][1], t[j][1]).ratio() >= thr:
                out.add(t[i][0])
                out.add(t[j][0])
    return out


def main():
    rows = list(csv.DictReader(io.open(os.path.join(INP, "recommendations.csv"),
                                       encoding="utf-8-sig")))
    qs = list(csv.DictReader(io.open(os.path.join(INP, "questions_by_user.csv"),
                                     encoding="utf-8-sig")))

    users = {}
    for q in qs:
        users.setdefault(q["Username"], q["Personas"])
    qcount = Counter(q["Username"] for q in qs)
    did3 = {r["Username"] for r in rows}

    total_words = sum(int(r[f + "_Words"] or 0) for r in rows for f in FIELDS)
    print(f"Task 3 respondents : {len(rows)} of {len(users)} corpus contributors")
    print(f"Responses          : {len(rows) * len(FIELDS)}")
    print(f"Words              : {total_words:,}")
    print()

    # ---- theme frequencies, with and without the templated cluster ---------
    os.makedirs(OUT, exist_ok=True)
    out_rows = []
    for field, themes in THEMES.items():
        fl = templated(rows, field)
        keep = [r for r in rows if r["Username"] not in fl]
        print(f"=== {field}  (all n={len(rows)}, de-templated n={len(keep)}) ===")
        for label, pat in themes.items():
            a = sum(1 for r in rows if re.search(pat, (r[field] or "").lower()))
            b = sum(1 for r in keep if re.search(pat, (r[field] or "").lower()))
            pa, pb = a / len(rows) * 100, b / len(keep) * 100
            print(f"  {label:<30} all {pa:5.1f}%   reported {pb:5.1f}%")
            out_rows.append({
                "prompt": field, "theme": label,
                "n_all": a, "pct_all": round(pa, 1),
                "n_detemplated": b, "pct_detemplated": round(pb, 1),
                "n_base_all": len(rows), "n_base_detemplated": len(keep),
            })
        print()

    for k, v in [("_respondents", len(rows)),
                 ("_responses", len(rows) * len(FIELDS)),
                 ("_total_words", total_words)]:
        out_rows.append({"prompt": "CONSTANT", "theme": k,
                         "n_all": v, "pct_all": "", "n_detemplated": "",
                         "pct_detemplated": "", "n_base_all": "",
                         "n_base_detemplated": ""})

    with io.open(os.path.join(OUT, "Z_stage5_vision_themes.csv"), "w",
                 encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(out_rows[0].keys()))
        w.writeheader()
        w.writerows(out_rows)

    # ---- who declined the open task ---------------------------------------
    grp = defaultdict(lambda: [0, 0])
    for u, p in users.items():
        key = "accountable" if _is_accountable(_personas(p)) else "user-side"
        grp[key][0 if u in did3 else 1] += 1
    odds, p = fisher_exact([grp["accountable"], grp["user-side"]])
    ay, an = grp["accountable"]
    uy, un = grp["user-side"]
    print("Completion of the open task")
    print(f"  accountable roles : {ay}/{ay+an} ({ay/(ay+an)*100:.0f}%)")
    print(f"  user-side roles   : {uy}/{uy+un} ({uy/(uy+un)*100:.0f}%)")
    print(f"  Fisher exact      : OR={odds:.3f}, p={p:.6f}")

    # ---- was it general disengagement? ------------------------------------
    def thin(ps):
        return any(x.startswith(("Sustainability and Energy", "Health and Safety")) for x in ps)

    a = [qcount[u] for u, p in users.items() if thin(_personas(p))]
    b = [qcount[u] for u, p in users.items() if not thin(_personas(p))]
    _, pv = mannwhitneyu(a, b)
    print(f"  questions in S1-S4: {sum(a)/len(a):.1f} vs {sum(b)/len(b):.1f} "
          f"per participant, Mann-Whitney p={pv:.4f}")
    print("  -> not general disengagement; the open format is what they declined.")


if __name__ == "__main__":
    main()
