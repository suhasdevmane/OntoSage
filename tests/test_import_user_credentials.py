# -*- coding: utf-8 -*-
"""scripts/import_user_credentials.py: CSV parsing, and idempotent create/update.

The database is an in-memory fake; AuthManager is the REAL class, so the hashing, the
register path and the password reset are the ones the orchestrator uses.
"""

import asyncio
import importlib.util
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "import_user_credentials.py"


def _load():
    spec = importlib.util.spec_from_file_location("import_creds_under_test", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod  # dataclasses looks the module up by name while building
    spec.loader.exec_module(mod)
    return mod


ic = _load()

_GOOD_PW_A = "trial-password-AAAA-1"
_GOOD_PW_B = "trial-password-BBBB-2"


class FakePg:
    """The four PostgresManager methods the import path touches, in memory."""

    def __init__(self):
        self.users = {}

    async def get_user(self, username):
        row = self.users.get(username)
        return dict(row) if row else None

    async def create_user(self, username, password_hash, salt, email, metadata, role="occupant"):
        self.users[username] = {
            "username": username,
            "password_hash": password_hash,
            "salt": salt,
            "email": email or "",
            "role": role,
            "metadata": "{}",
        }
        return True

    async def update_user_role_and_email(self, username, role, email):
        if username not in self.users:
            return False
        self.users[username].update(role=role, email=email)
        return True

    async def update_password(self, username, password_hash, salt):
        if username not in self.users:
            return False
        self.users[username].update(password_hash=password_hash, salt=salt)
        return True


def _auth(pg):
    from orchestrator.auth_manager import AuthManager

    # redis=None: the signup and reset paths use Postgres here. The session-revocation
    # branch of set_password is wrapped in its own try and logs a warning without it.
    return AuthManager(None, pg)


def _write_csv(tmp_path, body, name="creds.csv"):
    path = tmp_path / name
    path.write_text(body, encoding="utf-8")
    return path


_HEADER = "username,password,role,email\n"


def test_parse_accepts_good_rows_and_rejects_bad_ones(tmp_path):
    path = _write_csv(
        tmp_path,
        "﻿"
        + _HEADER
        + f"alice_01,{_GOOD_PW_A},occupant,alice@example.com\n"
        + "bob_02,short,occupant,bob@example.com\n"  # password too short
        + f"carol_03,{_GOOD_PW_A},superuser,carol@example.com\n"  # not a role
        + f"no-dash!,{_GOOD_PW_A},analyst,x@example.com\n",  # username shape
    )
    rows, rejected = ic.parse_csv(path)
    assert [r.username for r in rows] == ["alice_01"]
    assert rows[0].role == "occupant" and rows[0].email == "alice@example.com"
    assert len(rejected) == 3
    # A rejection names the row and the rule, and never echoes a password.
    for line in rejected:
        assert _GOOD_PW_A not in line and ",short," not in line


def test_missing_column_is_an_error(tmp_path):
    path = _write_csv(tmp_path, "username,role\nalice_01,occupant\n")
    with pytest.raises(ValueError, match="missing column"):
        ic.parse_csv(path)


def test_import_is_idempotent(tmp_path):
    path = _write_csv(
        tmp_path,
        _HEADER
        + f"alice_01,{_GOOD_PW_A},occupant,alice@example.com\n"
        + f"ops_02,{_GOOD_PW_B},operator,\n",
    )
    rows, _ = ic.parse_csv(path)
    pg = FakePg()
    auth = _auth(pg)

    first = asyncio.run(ic.import_rows(rows, auth, pg))
    assert sorted(first.created) == ["alice_01", "ops_02"]
    assert pg.users["ops_02"]["role"] == "operator"

    second = asyncio.run(ic.import_rows(rows, auth, pg))
    assert second.created == []
    assert second.role_or_email_updated == []
    assert second.password_reset == []
    assert sorted(second.unchanged) == ["alice_01", "ops_02"]
    assert second.failed == []


def test_changed_role_and_password_are_applied_on_rerun(tmp_path):
    pg = FakePg()
    auth = _auth(pg)
    rows, _ = ic.parse_csv(
        _write_csv(tmp_path, _HEADER + f"alice_01,{_GOOD_PW_A},occupant,a@example.com\n", "one.csv")
    )
    asyncio.run(ic.import_rows(rows, auth, pg))

    rows2, _ = ic.parse_csv(
        _write_csv(tmp_path, _HEADER + f"alice_01,{_GOOD_PW_B},analyst,a@example.com\n", "two.csv")
    )
    summary = asyncio.run(ic.import_rows(rows2, auth, pg))
    assert summary.role_or_email_updated == ["alice_01"]
    assert summary.password_reset == ["alice_01"]
    assert summary.created == []
    assert pg.users["alice_01"]["role"] == "analyst"
    # The new password verifies against the stored hash; the old one no longer does.
    stored = pg.users["alice_01"]
    assert auth._verify_password(_GOOD_PW_B, stored["password_hash"], stored["salt"])
    assert not auth._verify_password(_GOOD_PW_A, stored["password_hash"], stored["salt"])


def test_dry_run_writes_nothing(tmp_path):
    pg = FakePg()
    rows, _ = ic.parse_csv(_write_csv(tmp_path, _HEADER + f"alice_01,{_GOOD_PW_A},occupant,\n"))
    summary = asyncio.run(ic.import_rows(rows, _auth(pg), pg, dry_run=True))
    assert summary.created == ["alice_01"]
    assert pg.users == {}


def test_one_failing_row_does_not_stop_the_rest(tmp_path):
    pg = FakePg()
    auth = _auth(pg)

    pg.get_user_orig = pg.get_user

    async def flaky_get(username):
        if username == "alice_01":
            raise RuntimeError("db hiccup")
        return await pg.get_user_orig(username)

    pg.get_user = flaky_get
    rows, _ = ic.parse_csv(
        _write_csv(
            tmp_path,
            _HEADER + f"alice_01,{_GOOD_PW_A},occupant,\nbob_02,{_GOOD_PW_B},occupant,\n",
        )
    )
    summary = asyncio.run(ic.import_rows(rows, auth, pg))
    assert summary.failed == ["alice_01: RuntimeError"]
    assert summary.created == ["bob_02"]
