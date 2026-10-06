"""Backup passphrase: read from BACKUP_PASSPHRASE only (environment, then the active .env).

The Windows Credential Manager is not used (owner decision, 2026-10-06), so no test here
touches a keyring. Nothing reads a real .env: every test passes an explicit environ and file.
"""

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPTS = REPO / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import _backup_secret as sec  # noqa: E402

pytestmark = pytest.mark.unit

GOOD = "a long enough passphrase"


def _no_env_file(tmp_path: Path) -> Path:
    return tmp_path / "absent.env"


def test_environment_value_is_returned(tmp_path):
    got = sec.get_passphrase(
        environ={sec.ENV_NAME: GOOD}, env_file=_no_env_file(tmp_path), creating=True
    )
    assert got == GOOD


def test_active_env_file_is_read_when_the_environment_is_empty(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text(f'# comment\nOTHER=1\n{sec.ENV_NAME}="{GOOD}"\n', encoding="utf-8")
    assert sec.get_passphrase(environ={}, env_file=env_file, creating=True) == GOOD


def test_environment_wins_over_the_file(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text(f"{sec.ENV_NAME}=from-the-file-value\n", encoding="utf-8")
    got = sec.get_passphrase(environ={sec.ENV_NAME: GOOD}, env_file=env_file)
    assert got == GOOD


def test_unset_everywhere_fails_naming_the_variable(tmp_path):
    with pytest.raises(sec.PassphraseError, match=sec.ENV_NAME):
        sec.get_passphrase(environ={}, env_file=_no_env_file(tmp_path))


def test_a_file_without_the_key_is_not_a_passphrase(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("BACKUP_PASSPHRASE_OLD=whatever\n", encoding="utf-8")
    with pytest.raises(sec.PassphraseError):
        sec.get_passphrase(environ={}, env_file=env_file)


def test_writing_refuses_a_short_passphrase(tmp_path):
    with pytest.raises(sec.PassphraseError, match="at least"):
        sec.get_passphrase(
            creating=True, environ={sec.ENV_NAME: "short"}, env_file=_no_env_file(tmp_path)
        )


def test_restoring_accepts_any_non_empty_passphrase(tmp_path):
    # An archive written under an older, shorter passphrase must still open.
    got = sec.get_passphrase(
        creating=False, environ={sec.ENV_NAME: "old"}, env_file=_no_env_file(tmp_path)
    )
    assert got == "old"


def test_keyring_is_not_imported_or_referenced():
    source = (SCRIPTS / "_backup_secret.py").read_text(encoding="utf-8")
    assert "keyring" not in source
    assert "getpass" not in source


def test_check_reports_set_or_not_set_without_printing_the_value(monkeypatch, capsys):
    monkeypatch.setenv(sec.ENV_NAME, GOOD)
    assert sec.main(["--check"]) == 0
    out = capsys.readouterr().out
    assert out.strip() == "set"
    assert GOOD not in out

    monkeypatch.delenv(sec.ENV_NAME)
    monkeypatch.setattr(sec, "REPO_ROOT", REPO / "does-not-exist-for-test")
    assert sec.main(["--check"]) == 2
    assert GOOD not in capsys.readouterr().out
