"""Scan the shareable Datasets folder for anything that identifies a person.

`pseudonymise.py` replaced identifier columns; a later pass caught names
embedded in composite keys ("<name>|1|qd892..."). This looks wider still: email
addresses anywhere, participant names written into free text, worker IDs,
phone numbers and file names. A participant can sign their own answer, and no
column rename catches that.

Reports only; nothing is changed.

    python Datasets/pii_scan.py [--names names.txt]

WHY THE PATTERNS LOOK FUSSY
    The first version reported 142 hits, almost all false. A 16-digit run
    inside a correlation coefficient looked like a card number; ACCESSIBILITY
    and AUTOMATICALLLY looked like MTurk worker IDs. A scanner that cries wolf
    gets ignored, so each pattern is narrowed and every deliberate exception
    is named with its reason.
"""
import io
import os
import re
import sys
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
TEXT_EXT = {".csv", ".json", ".jsonl", ".md", ".txt", ".yaml", ".yml", ".ttl",
            ".py", ".log", ".html"}

PATTERNS = {
    "email address":
        re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"),
    # a real worker id mixes letters and digits; without the digit lookahead
    # this matched ACCESSIBILITY and AUTOMATICALLLY
    "MTurk worker id":
        re.compile(r"\bA(?=[0-9A-Z]{12,14}\b)(?=[0-9A-Z]*[0-9])[0-9A-Z]{12,14}\b"),
    "phone (intl)":
        re.compile(r"\+\d{1,3}[\s-]?\(?\d{2,4}\)?[\s-]?\d{3,4}[\s-]?\d{3,4}\b"),
    "UK postcode":
        re.compile(r"\b[A-Z]{1,2}\d[A-Z\d]?\s\d[A-Z]{2}\b"),
    # a 16-digit run inside a decimal is a float, not a card number
    "credit-card-like":
        re.compile(r"(?<![.\d])\d{4}[ -]\d{4}[ -]\d{4}[ -]\d{4}(?![.\d])"),
    "IP address":
        re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b"),
}

# Each exception is a decision, so each carries its reason.
ALLOW_EMAIL = {
    "devmanesp1@cardiff.ac.uk": "corresponding author, meant to be reachable",
    "ranaof@cardiff.ac.uk": "co-author",
    "pererac@cardiff.ac.uk": "co-author",
    "estates@cardiff.ac.uk": "shared institutional inbox, quoted by the system in its own answer",
    "safety@cardiff.ac.uk": "shared institutional inbox",
    "security@cardiff.ac.uk": "shared institutional inbox",
    "ethics@cardiff.ac.uk": "shared institutional inbox",
    "it-support@cardiff.ac.uk": "shared institutional inbox",
    "dataprotection@cardiff.ac.uk": "shared institutional inbox",
    "disability@cardiff.ac.uk": "shared institutional inbox",
    "estates@example.ac.uk": "placeholder domain in the ontology",
}
ALLOW_POSTCODE = {
    "CF24 4AG": "the building's own public address, in a system answer",
    "EX1 2AB": "placeholder in the ontology",
}
ALLOW_NAME = {
    "john smith": ('the probe "Where was John Smith in the building yesterday?", a '
                   "generic name used to test privacy refusal. No participant is "
                   "identifiable from it: the shared data carries only P01-P96 and "
                   "no name mapping ships with it."),
}


def main():
    names = []
    if "--names" in sys.argv:
        p = sys.argv[sys.argv.index("--names") + 1]
        names = [n.strip().lower() for n in io.open(p, encoding="utf-8")
                 if len(n.strip()) > 3]

    hits = {k: Counter() for k in PATTERNS}
    name_hits, allowed_names = Counter(), Counter()
    scanned = 0

    for dirpath, dirnames, filenames in os.walk(HERE):
        dirnames[:] = [d for d in dirnames if d != "__pycache__"]
        for fn in filenames:
            p = os.path.join(dirpath, fn)
            rel = os.path.relpath(p, HERE)
            if os.path.splitext(fn)[1].lower() not in TEXT_EXT:
                continue
            try:
                s = io.open(p, encoding="utf-8", errors="ignore").read()
            except OSError:
                continue
            scanned += 1
            for label, pat in PATTERNS.items():
                for v in set(pat.findall(s)):
                    v = v if isinstance(v, str) else v[0]
                    if label == "email address" and v.lower() in ALLOW_EMAIL:
                        continue
                    if label == "UK postcode" and v.upper() in ALLOW_POSTCODE:
                        continue
                    hits[label][f"{v}  <-  {rel}"] += 1
            for n in names:
                if re.search(r"\b" + re.escape(n) + r"\b", s, re.I):
                    tgt = allowed_names if n in ALLOW_NAME else name_hits
                    tgt[f"{n}  <-  {rel}"] += 1

    print(f"scanned {scanned} text files under Datasets/\n")
    clean = True
    for label, c in hits.items():
        if not c:
            print(f"  clean   {label}")
            continue
        clean = False
        print(f"  ** {len(c)} {label}(s):")
        for k, _ in c.most_common(12):
            print(f"       {k}")

    if names:
        if name_hits:
            clean = False
            print(f"\n  ** {len(name_hits)} participant name(s) in free text:")
            for k, _ in name_hits.most_common(20):
                print(f"       {k}")
        else:
            print("  clean   participant names in free text")

    bad = []
    for dirpath, dirnames, filenames in os.walk(HERE):
        dirnames[:] = [d for d in dirnames if d != "__pycache__"]
        for fn in filenames + dirnames:
            for n in names:
                if n in fn.lower() and n not in ALLOW_NAME:
                    bad.append(os.path.join(os.path.relpath(dirpath, HERE), fn))
    if bad:
        clean = False
        print(f"  ** {len(bad)} name(s) in file or folder names: {bad[:8]}")
    else:
        print("  clean   name(s) in file or folder names")

    if allowed_names:
        print("\n  allowed by exception:")
        for k, _ in allowed_names.most_common():
            nm = k.split("  <-  ")[0]
            print(f"     {k}")
        print(f"       reason: {ALLOW_NAME[nm]}")

    print("\n" + ("PASS - no personally identifying data found"
                  if clean else "REVIEW THE ITEMS ABOVE BEFORE SHARING"))
    return 0 if clean else 1


if __name__ == "__main__":
    sys.exit(main())
