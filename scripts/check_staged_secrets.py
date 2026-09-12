#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Fail if a real credential is about to be committed (BUG-507).

WHY THIS EXISTS
---------------
On 2026-09-10, un-ignoring ``tasks/`` for CAVEAT-501 would have committed the live
``ADMIN_PASSWORD`` -- it sat in ``tasks/REVIEW_AND_EXTEND_PROMPT.md`` inside a runnable
login example. It was caught by an ad-hoc grep run minutes before staging, which is luck,
not a control.

Worse, the same session then declared the credential had "never been committed" on the
strength of ``git grep -l HEAD``. That reads the CURRENT TREE only. The file had been
untracked a month earlier, so HEAD was clean while the blob sat in ``3756e8a``, an ancestor
of every remote branch. **A present-tense check cannot answer a historical question**, and
this script does not pretend otherwise: it guards what is ABOUT to enter history, which is
the only part still preventable.

WHAT IT CHECKS
--------------
Two independent passes, because either alone is insufficient:

1. **Known values.** Every credential-shaped value in the local ``.env`` / ``.envN`` files
   is searched for, verbatim, in the staged content. This is the pass that catches a real
   password pasted into a working note, which no generic pattern reliably matches -- the
   one that nearly shipped looked like an ordinary word.

2. **Generic patterns.** ``password: "..."``, private-key headers, and long
   high-entropy-looking assignments, for credentials this machine's ``.env`` does not
   happen to hold.

WHAT IT DELIBERATELY IGNORES
---------------------------
* Values equal to a ``.env.example`` placeholder or to a known default in
  ``shared/config.py`` -- an unchanged default is a hygiene problem, not a disclosure, and
  flagging it here would train whoever runs this to pass ``--no-verify``. ``STRICT_SECRETS``
  is the control for that, at boot, where it belongs.
* Short values (< 8 chars) and obvious placeholders (``CHANGE-ME``, ``YOUR_``, ``xxx``).
* The ``.env`` files themselves -- they are gitignored, and if one is ever staged the
  filename rule below catches it first.

    python scripts/check_staged_secrets.py            # staged content (pre-commit)
    python scripts/check_staged_secrets.py --all      # every tracked file, not just staged
    python scripts/check_staged_secrets.py --self-test

Exit 0 clean, 1 on a finding, 2 if it could not run -- never 0 for "I could not check",
because a guard that reports green from a starved input is worse than no guard.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Set, Tuple

REPO = Path(__file__).resolve().parent.parent

#: Filenames that must never be committed whatever their contents.
#:
#: ``*.example`` and ``*.sample`` are EXCLUDED first: `.env.example`, `.env2.example` and
#: their kin are templates whose whole job is to be committed. The first version of this
#: rule matched `.env2.example` on "`.env` followed by a digit" and would have blocked a
#: commit for staging the very file that documents what to fill in.
FORBIDDEN_NAMES = re.compile(
    r"(?!.*\.(example|sample|template)$)"
    r"(?:(^|/)\.env(\.|\d|$)|credentials?[^/]*\.(csv|json|ya?ml)$"
    r"|\.pem$|\.p12$|id_rsa$|(^|/)env\.backup)",
    re.IGNORECASE,
)

#: Generic shapes, for secrets this machine's .env does not hold.
PATTERNS: List[Tuple[str, str]] = [
    ("private key block", r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    ("aws access key id", r"\bAKIA[0-9A-Z]{16}\b"),
    ("github token", r"\bgh[pousr]_[A-Za-z0-9]{30,}\b"),
    ("openai key", r"\bsk-[A-Za-z0-9]{20,}\b"),
    ("password assignment", r"(?i)\bpass(?:word|wd)\b[\"']?\s*[:=]\s*[\"'][^\"'\s]{8,}[\"']"),
]

PLACEHOLDER = re.compile(r"^(change[-_]?me|your[-_]|xxx+|\.\.\.|<.*>|placeholder|secret|example)",
                         re.IGNORECASE)

#: A reference is not a value. "$ADMIN_PASSWORD", "${PW}" and "%PW%" are the CORRECT way to
#: write a credential into a runnable example, so flagging them punishes the fix.
VAR_REFERENCE = re.compile(r"^[\$%]\{?[A-Za-z_][A-Za-z0-9_]*\}?%?$")

#: Names that mark a fixture account rather than a real credential. These exist to be
#: committed -- `replaytest`/`replaytestpass99` is a seeded test login, not a disclosure.
TEST_CREDENTIAL = re.compile(r"(?i)\b(replaytest|testuser|dummy|fixture|sample|example)\b")


def _run(args: List[str]) -> str:
    """git output as text, decoded as UTF-8 whatever the console codepage says.

    `text=True` alone uses the LOCALE encoding — cp1252 on Windows — and a repository file
    containing one byte outside it raises UnicodeDecodeError mid-scan. Observed
    2026-09-12 on a staged file at byte 848,151: the traceback printed and the scan then
    reported "no live credential in 24 file(s)". A guard that skips a file it could not
    read and still reports clean is the exact failure its own `return 2` path exists to
    prevent, and it was in the guard itself.

    `errors="replace"` rather than `ignore`: a replacement character is visible in the
    output, whereas silently dropping bytes could split a credential and hide it.
    """
    return subprocess.run(
        args, capture_output=True, cwd=REPO, encoding="utf-8", errors="replace"
    ).stdout


def _env_secrets() -> Dict[str, str]:
    """Credential-shaped values from every local .env, keyed by "FILE:NAME".

    These files are gitignored; they are read only so their VALUES can be searched for
    somewhere else. Nothing here is printed -- see `_mask`.
    """
    out: Dict[str, str] = {}
    for p in sorted(REPO.glob(".env*")):
        if p.suffix == ".example" or p.name.endswith(".example") or not p.is_file():
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for m in re.finditer(r"^([A-Z0-9_]+)=(.*)$", text, re.M):
            name, val = m.group(1), m.group(2).strip().strip('"').strip("'")
            if not re.search(r"(PASSWORD|PASSWD|SECRET|TOKEN|_KEY|APIKEY)", name):
                continue
            if len(val) < 8 or PLACEHOLDER.match(val):
                continue
            out[f"{p.name}:{name}"] = val
    return out


def _benign_values() -> Set[str]:
    """Values that are unchanged defaults, not disclosures."""
    benign: Set[str] = set()
    for name in (".env.example", ".env1.example", ".env2.example"):
        p = REPO / name
        if p.is_file():
            for m in re.finditer(r"^[A-Z0-9_]+=(.*)$", p.read_text(encoding="utf-8", errors="replace"), re.M):
                v = m.group(1).strip().strip('"').strip("'")
                if v:
                    benign.add(v)
    cfg = REPO / "shared" / "config.py"
    if cfg.is_file():
        body = cfg.read_text(encoding="utf-8", errors="replace")
        block = re.search(r"_DEFAULT_PASSWORDS\s*=\s*\{(.*?)\}", body, re.S)
        if block:
            benign.update(re.findall(r":\s*[\"']([^\"']+)[\"']", block.group(1)))
    return benign


def _mask(v: str) -> str:
    return f"{v[:2]}{'*' * max(4, len(v) - 4)}{v[-2:]}" if len(v) > 6 else "*" * len(v)


def _staged_files() -> List[str]:
    out = _run(["git", "diff", "--cached", "--name-only", "--diff-filter=ACMR"])
    return [f for f in out.splitlines() if f.strip()]


def _staged_blob(path: str) -> str:
    return _run(["git", "show", f":{path}"])


def scan(paths: List[str], reader) -> Tuple[List[str], List[str]]:
    """Returns (errors, infos).

    The split is the point. The known-value pass is an EXACT match against a credential
    this machine actually uses, so a hit is a disclosure and blocks the commit. The pattern
    pass is a heuristic over prose and code, and its first run produced eight hits of which
    zero were real -- a shell variable reference I had just written as the FIX, and a seeded
    test login that exists to be committed. Blocking on those trains whoever runs this to
    reach for ``--no-verify``, and a bypassed guard protects nothing. So suspicion is
    reported and certainty is enforced, which is the same ERROR/INFO split
    ``check_building_literals.py`` already uses.
    """
    known = _env_secrets()
    benign = _benign_values()
    errors: List[str] = []
    infos: List[str] = []

    for path in paths:
        if FORBIDDEN_NAMES.search(path):
            errors.append(f"  FORBIDDEN FILE  {path}  -- a credential file must never be committed")
            continue
        try:
            content = reader(path)
        except Exception:
            continue
        if not content:
            continue
        for key, val in known.items():
            if val in benign:
                continue
            if val in content:
                errors.append(f"  LIVE CREDENTIAL {path}  -- matches {key} (value {_mask(val)})")
        for label, rx in PATTERNS:
            for m in re.finditer(rx, content):
                frag = m.group(0)
                if any(b and b in frag for b in benign) or PLACEHOLDER.search(frag):
                    continue
                quoted = re.search(r"[\"']([^\"']+)[\"']\s*$", frag)
                if quoted and VAR_REFERENCE.match(quoted.group(1)):
                    continue
                line = content[: m.start()].count("\n") + 1
                lines = content.splitlines()
                ctx = lines[line - 1] if 0 <= line - 1 < len(lines) else ""
                if TEST_CREDENTIAL.search(ctx):
                    continue
                infos.append(f"  {label:<20} {path}:{line}")
    return errors, infos


def _self_test() -> int:
    """Prove the guard catches a planted secret.

    The literal guard once scanned two directories and reported "clean" while fifteen real
    literals sat outside its scope. A guard with no self-test is a guard nobody can trust,
    so this asserts a positive AND a negative rather than only that the script runs.
    """
    known = _env_secrets()
    if not known:
        print("SELF-TEST INCONCLUSIVE: no local .env credential to plant; run where .env exists")
        return 2
    key, val = next(iter(known.items()))
    planted, _ = scan(["fake.md"], lambda _p: f"here is a note\npassword: {val}\n")
    clean, _ = scan(["fake.md"], lambda _p: "here is a note with no secret in it\n")
    fname, _ = scan([".env2"], lambda _p: "irrelevant\n")
    # A shell variable reference is the FIX, not the defect, and must stay quiet.
    _, ref_infos = scan(["ok.sh"], lambda _p: 'curl -d \'{"password":"$ADMIN_PASSWORD"}\'\n')
    checks = [
        ("planted secret blocks the commit", bool(planted)),
        ("a clean file stays clean", not clean),
        ("a credential FILENAME blocks it", bool(fname)),
        ("a $VAR reference is not flagged", not ref_infos),
    ]
    for label, ok_ in checks:
        print(f"  {label:<34} {ok_}  (expected True)")
    ok = all(c[1] for c in checks)
    print("SELF-TEST PASS" if ok else "SELF-TEST FAIL")
    return 0 if ok else 1


def main(argv: List[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--all", action="store_true", help="scan every tracked file, not just staged")
    ap.add_argument("--self-test", action="store_true", help="prove the guard still catches one")
    ap.add_argument("--strict", action="store_true", help="also fail on INFO patterns")
    args = ap.parse_args(argv)

    if args.self_test:
        return _self_test()

    if not (REPO / ".git").exists():
        print("not a git repository -- refusing to report clean", file=sys.stderr)
        return 2

    if args.all:
        paths = [p for p in _run(["git", "ls-files"]).splitlines() if p.strip()]
        reader = lambda p: (REPO / p).read_text(encoding="utf-8", errors="replace")  # noqa: E731
    else:
        paths = _staged_files()
        reader = _staged_blob

    if not paths:
        print("nothing staged -- no secrets to check")
        return 0

    errors, infos = scan(paths, reader)

    if infos:
        print(f"INFO -- {len(infos)} credential-shaped pattern(s), not blocking:")
        print("\n".join(infos))
        print()

    if errors:
        print(f"REFUSING THE COMMIT -- {len(errors)} finding(s) in {len(paths)} file(s):\n")
        print("\n".join(errors))
        print(
            "\nRedact the value and stage again. If the file legitimately holds a credential,\n"
            "gitignore the file rather than committing it. `--no-verify` bypasses this check\n"
            "and puts the secret in history permanently -- BUG-507 is what that costs."
        )
        return 1

    if args.strict and infos:
        print("REFUSING THE COMMIT -- --strict was given and there are INFO findings.")
        return 1

    print(f"no live credential in {len(paths)} file(s)"
          + (f"; {len(infos)} INFO pattern(s) reported above" if infos else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
