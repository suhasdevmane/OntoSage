"""Replace participant names with PIDs throughout the shareable Datasets copy.

WHY
    The survey exports carry real participant names in a Username column
    ("a real name"), an email address, and eight MTurk worker IDs. The classified
    corpus already uses PIDs, so the pseudonymisation existed but was never
    applied to the raw exports. This folder is meant to be emailed, and the
    study runs under SREC COMSC/Ethics/2025/044b.

WHY NOT A BLIND FIND-AND-REPLACE
    One participant's username is the word "got", which occurs in question
    text. A whole-file substitution would rewrite a participant's words. So:

      * in CSV, only the identifier COLUMNS are rewritten
      * in JSON, only the identifier KEYS
      * an email address and a worker ID are unambiguous wherever they appear,
        so those are replaced in free text as well

    The mapping is then deleted from the shared copy, because a pseudonym
    table shipped beside pseudonymised data re-identifies it. It stays under
    paper/, which is not shared.

Run:  python Datasets/pseudonymise.py [--apply]
"""
import csv
import io
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
MAP = os.path.join(HERE, "Survey analysis and results", "outputs",
                   "intermediate", "username_to_pid.csv")
APPLY = "--apply" in sys.argv

ID_COLS = {"username", "user", "pid", "participant", "worker", "workerid"}


def load_map():
    m = {}
    with io.open(MAP, encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            u = (row.get("Username") or "").strip()
            p = (row.get("PID") or "").strip()
            if u and p:
                m[u.lower()] = p
    return m


def unambiguous(m):
    """Names that are certainly identifiers wherever they appear: emails and
    long opaque worker IDs. Never an English word."""
    out = {}
    for u, p in m.items():
        if "@" in u or re.fullmatch(r"[a-z0-9_]{9,}", u):
            out[u] = p
    return out


def do_csv(path, m, free):
    rows = list(csv.reader(io.open(path, encoding="utf-8", errors="ignore",
                                   newline="")))
    if not rows:
        return 0
    head = [h.strip().lower() for h in rows[0]]
    idx = [i for i, h in enumerate(head) if h in ID_COLS]
    n = 0
    for r in rows[1:]:
        for i in idx:
            if i < len(r):
                v = r[i].strip().lower()
                if v in m:
                    r[i] = m[v]
                    n += 1
        for i, cell in enumerate(r):
            if i in idx:
                continue
            for u, p in free.items():
                if u in cell.lower():
                    r[i] = re.sub(re.escape(u), p, cell, flags=re.I)
                    n += 1
    if APPLY and n:
        with io.open(path, "w", encoding="utf-8", newline="") as f:
            csv.writer(f).writerows(rows)
    return n


def do_json(path, m, free):
    try:
        data = json.load(io.open(path, encoding="utf-8"))
    except Exception:
        return 0
    n = [0]

    def walk(o):
        if isinstance(o, dict):
            return {k: (m.get(str(v).strip().lower(), v)
                        if str(k).strip().lower() in ID_COLS
                        and str(v).strip().lower() in m
                        else walk(v)) for k, v in o.items()}
        if isinstance(o, list):
            return [walk(x) for x in o]
        if isinstance(o, str):
            s = o
            for u, p in free.items():
                if u in s.lower():
                    s = re.sub(re.escape(u), p, s, flags=re.I)
                    n[0] += 1
            return s
        return o

    new = walk(data)
    # count identifier swaps by diffing the serialised forms
    before, after = json.dumps(data, sort_keys=True), json.dumps(new, sort_keys=True)
    if before != after:
        n[0] = max(n[0], 1)
        if APPLY:
            io.open(path, "w", encoding="utf-8").write(json.dumps(new, indent=1))
    return n[0]


def do_text(path, free):
    s = io.open(path, encoding="utf-8", errors="ignore").read()
    n = 0
    for u, p in free.items():
        c = len(re.findall(re.escape(u), s, flags=re.I))
        if c:
            s = re.sub(re.escape(u), p, s, flags=re.I)
            n += c
    if APPLY and n:
        io.open(path, "w", encoding="utf-8").write(s)
    return n


def main():
    if not os.path.exists(MAP):
        print("mapping already removed; nothing to do")
        return 0
    m = load_map()
    free = unambiguous(m)
    print(f"mapping: {len(m)} participants")
    print(f"of which unambiguous in free text (emails, worker IDs): {len(free)}")
    print("  " + ", ".join(sorted(free)[:4]) + " ...\n")

    touched = []
    for dirpath, dirnames, filenames in os.walk(HERE):
        dirnames[:] = [d for d in dirnames if d != "__pycache__"]
        for fn in filenames:
            p = os.path.join(dirpath, fn)
            if os.path.abspath(p) == os.path.abspath(MAP):
                continue
            ext = os.path.splitext(fn)[1].lower()
            n = 0
            if ext == ".csv":
                n = do_csv(p, m, free)
            elif ext == ".json":
                n = do_json(p, m, free)
            elif ext in {".md", ".txt", ".log"}:
                n = do_text(p, free)
            if n:
                touched.append((os.path.relpath(p, HERE), n))

    for rel, n in sorted(touched, key=lambda r: -r[1])[:18]:
        print(f"  {n:>7,}  {rel}")
    print(f"\n  {sum(n for _, n in touched):,} replacements across {len(touched)} files")

    if not APPLY:
        print("\nreport only. re-run with --apply.")
        return 0

    os.remove(MAP)
    print("\n  mapping DELETED from the shared copy (it remains under paper/)")

    # verify: no identifier column anywhere still holds a name
    left = []
    for dirpath, dirnames, filenames in os.walk(HERE):
        dirnames[:] = [d for d in dirnames if d != "__pycache__"]
        for fn in filenames:
            if not fn.lower().endswith(".csv"):
                continue
            p = os.path.join(dirpath, fn)
            rows = list(csv.reader(io.open(p, encoding="utf-8", errors="ignore")))
            if not rows:
                continue
            head = [h.strip().lower() for h in rows[0]]
            for i, h in enumerate(head):
                if h not in ID_COLS:
                    continue
                for r in rows[1:]:
                    if i < len(r) and r[i].strip().lower() in m:
                        left.append(f"{os.path.relpath(p, HERE)}:{h}")
                        break
    left = sorted(set(left))
    print(f"  verification: {len(left)} identifier column(s) still hold a name"
          + ("" if not left else f"\n    {left}"))
    return 1 if left else 0


if __name__ == "__main__":
    sys.exit(main())
