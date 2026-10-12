#!/usr/bin/env python3
"""Write the Paper 3 study accounts (P01..P45) to a git-ignored credentials CSV, once.

Each participant code gets an OntoSage username ``study_pNN``, the role ``occupant`` (every role
reads every data source under the QA access setting, NOTE-1416, so the role cannot cause a
refusal on a study task), an e-mail on the reserved ``example.com`` domain (no personal data),
and a random 16-character password.

The file is written ONLY if it does not exist: re-running never changes a password a
facilitator has already printed. Passwords are never printed. Provision both systems with:

    python scripts/make_study_credentials.py
    python scripts/provision_demo_users.py user_credentials_study_bldg1.csv

The output name matches the ``user_credentials*.csv`` rule in .gitignore.
"""

from __future__ import annotations

import argparse
import csv
import secrets
import string
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DEFAULT_OUT = REPO / "user_credentials_study_bldg1.csv"
ALPHABET = string.ascii_letters + string.digits


def study_rows(n: int) -> list:
    """Rows for participant codes P01..Pn (username, password, role, email)."""
    rows = []
    for i in range(1, n + 1):
        code = f"p{i:02d}"
        pw = "".join(secrets.choice(ALPHABET) for _ in range(16))
        rows.append(
            {
                "username": f"study_{code}",
                "password": pw,
                "role": "occupant",
                "email": f"{code}@study.example.com",
            }
        )
    return rows


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--n", type=int, default=45)
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    args = ap.parse_args()
    out = Path(args.out)
    if out.exists():
        print(f"{out.name} already exists; not overwritten (passwords are kept).")
        return 0
    rows = study_rows(args.n)
    with out.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(
            fh, fieldnames=["username", "password", "role", "email"], lineterminator="\n"
        )
        w.writeheader()
        w.writerows(rows)
    print(f"wrote {len(rows)} study accounts to {out.name} (git-ignored); passwords not shown")
    return 0


if __name__ == "__main__":
    sys.exit(main())
