#!/usr/bin/env python3
"""Create or update OntoSage accounts from a credentials CSV (idempotent).

The CSV has the header ``username,password,role,email``. For each row:

* no account yet      -> created through AuthManager.register_user (the same path as /auth/register)
* account exists      -> role and email are set to the CSV values when they differ;
                         the password is re-set only when the stored hash does not verify
                         against the CSV password (set_password also revokes live sessions)
* nothing differs     -> nothing is written

Running it twice in a row therefore writes nothing the second time. Passwords and hashes are
never printed; output names the usernames and what happened to them.

    python scripts/import_user_credentials.py                      # repo-root user_credentials_bldg1.csv
    python scripts/import_user_credentials.py --csv path/to.csv --dry-run

Needs the stack's PostgreSQL reachable through the active .env (the same one the orchestrator
reads). It does not need the orchestrator to be running.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

DEFAULT_CSV = REPO_ROOT / "user_credentials_bldg1.csv"
VALID_ROLES = {"admin", "facility_manager", "analyst", "operator", "occupant", "readonly"}
#: The same rules RegisterRequest applies, so an imported account is one a user could register.
_USERNAME_RE = re.compile(r"^[a-zA-Z0-9_]{3,255}$")
_MIN_PASSWORD = 12


@dataclass
class Row:
    username: str
    password: str
    role: str
    email: str


@dataclass
class Summary:
    created: List[str] = field(default_factory=list)
    role_or_email_updated: List[str] = field(default_factory=list)
    password_reset: List[str] = field(default_factory=list)
    unchanged: List[str] = field(default_factory=list)
    rejected: List[str] = field(default_factory=list)  # "username: reason" (never the password)
    failed: List[str] = field(default_factory=list)

    def as_text(self, dry_run: bool) -> str:
        verb = (lambda s: f"would {s}") if dry_run else (lambda s: s)
        lines = [
            f"created ({verb('create')}): {len(self.created)}",
            f"role/email updated ({verb('update')}): {len(self.role_or_email_updated)}",
            f"password reset ({verb('reset')}): {len(self.password_reset)}",
            f"unchanged: {len(self.unchanged)}",
            f"rejected rows: {len(self.rejected)}",
            f"failed: {len(self.failed)}",
        ]
        for label, items in (
            ("rejected", self.rejected),
            ("failed", self.failed),
        ):
            for item in items:
                lines.append(f"  {label}: {item}")
        return "\n".join(lines)


def parse_csv(path: Path) -> Tuple[List[Row], List[str]]:
    """Return ``(valid_rows, rejections)``. A rejection names the row and the rule it broke."""
    rows: List[Row] = []
    rejected: List[str] = []
    with path.open(encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        missing = {"username", "password", "role"} - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"{path.name}: missing column(s) {sorted(missing)}")
        for lineno, raw in enumerate(reader, start=2):
            username = (raw.get("username") or "").strip()
            password = raw.get("password") or ""
            role = (raw.get("role") or "").strip()
            email = (raw.get("email") or "").strip()
            label = f"line {lineno} ({username or 'no username'})"
            if not _USERNAME_RE.match(username):
                rejected.append(f"{label}: username must be 3+ letters, digits or underscores")
            elif len(password) < _MIN_PASSWORD:
                rejected.append(f"{label}: password shorter than {_MIN_PASSWORD} characters")
            elif role not in VALID_ROLES:
                rejected.append(f"{label}: unknown role {role!r}")
            else:
                rows.append(Row(username, password, role, email))
    return rows, rejected


async def import_rows(rows: List[Row], auth: Any, pg: Any, dry_run: bool = False) -> Summary:
    """Apply ``rows`` to the accounts. ``auth`` is an AuthManager, ``pg`` a PostgresManager."""
    summary = Summary()
    for row in rows:
        try:
            existing: Optional[Dict[str, Any]] = await pg.get_user(row.username)
            if existing is None:
                if not dry_run:
                    result = await auth.register_user(
                        row.username, row.password, row.email or None, role=row.role
                    )
                    if not result.get("success"):
                        summary.failed.append(f"{row.username}: {result.get('error')}")
                        continue
                summary.created.append(row.username)
                continue

            changed = False
            if (existing.get("role") or "") != row.role or (
                existing.get("email") or ""
            ) != row.email:
                changed = True
                if not dry_run:
                    ok = await pg.update_user_role_and_email(row.username, row.role, row.email)
                    if not ok:
                        summary.failed.append(f"{row.username}: role/email update failed")
                        continue
                summary.role_or_email_updated.append(row.username)

            # Verify, never compare: stored hashes are salted Argon2id and cannot be matched by
            # equality. A mismatch means the account's password differs from the CSV.
            matches = auth._verify_password(
                row.password, existing.get("password_hash") or "", existing.get("salt") or ""
            )
            if not matches:
                if not dry_run:
                    reset = await auth.set_password(row.username, row.password)
                    if not reset.get("success"):
                        summary.failed.append(f"{row.username}: password reset failed")
                        continue
                summary.password_reset.append(row.username)
                changed = True

            if not changed:
                summary.unchanged.append(row.username)
        except Exception as e:  # one bad row must not stop the rest; never echo the password
            summary.failed.append(f"{row.username}: {type(e).__name__}")
    return summary


async def _run(csv_path: Path, dry_run: bool) -> int:
    from orchestrator.auth_manager import AuthManager
    from orchestrator.postgres_manager import PostgresManager

    rows, rejected = parse_csv(csv_path)
    pg = PostgresManager()
    await pg.connect()
    try:
        auth = AuthManager(None, pg)
        summary = await import_rows(rows, auth, pg, dry_run=dry_run)
    finally:
        try:
            await pg.close()
        except Exception:
            pass
    summary.rejected.extend(rejected)
    print(f"{csv_path.name}: {len(rows)} valid row(s), {len(rejected)} rejected")
    print(summary.as_text(dry_run))
    return 1 if summary.failed else 0


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--csv", default=str(DEFAULT_CSV), help="credentials CSV to import")
    parser.add_argument("--dry-run", action="store_true", help="report what would change")
    args = parser.parse_args(argv)
    path = Path(args.csv)
    if not path.is_file():
        print(f"error: {path} does not exist", file=sys.stderr)
        return 2
    return asyncio.run(_run(path, args.dry_run))


if __name__ == "__main__":
    raise SystemExit(main())
