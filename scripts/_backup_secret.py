"""Backup passphrase for the encrypted backup scripts: read from BACKUP_PASSPHRASE, nowhere else.

The passphrase is an environment variable in the active ``.env``, like every other credential
in this project (owner decision, 2026-10-06). The Windows Credential Manager is deliberately
not used. A value already in the process environment wins over the file, so a scheduled run
may supply it without writing it anywhere.

    BACKUP_PASSPHRASE=<at least 12 characters>      # in the active .env

Check that it is set (prints set / not set, never the value)::

    .venv\\Scripts\\python.exe scripts\\_backup_secret.py --check
"""

import argparse
import os
import sys
from pathlib import Path
from typing import Mapping, Optional

SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from _backup_format import MIN_PASSPHRASE_LENGTH  # noqa: E402

REPO_ROOT = SCRIPTS_DIR.parent
ENV_NAME = "BACKUP_PASSPHRASE"


class PassphraseError(Exception):
    """No usable passphrase could be obtained."""


def _read_key_from_env_file(path: Path, key: str) -> Optional[str]:
    """Return the value of one KEY=VALUE line in a dotenv file, or None. Never prints it."""
    if not path.is_file():
        return None
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, _, value = line.partition("=")
        if name.strip() != key:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        return value
    return None


def get_passphrase(
    *,
    creating: bool = False,
    environ: Optional[Mapping[str, str]] = None,
    env_file: Optional[Path] = None,
) -> str:
    """Return BACKUP_PASSPHRASE from the environment, else from the active .env.

    creating=True is used when WRITING an archive and enforces MIN_PASSPHRASE_LENGTH.
    creating=False (restore) accepts any non-empty value, because an old archive was written
    with whatever passphrase was in force then.
    """
    env = os.environ if environ is None else environ
    value = env.get(ENV_NAME) or _read_key_from_env_file(
        env_file if env_file is not None else REPO_ROOT / ".env", ENV_NAME
    )
    if not value:
        raise PassphraseError(
            f"{ENV_NAME} is not set. Add it to the active .env (see .env.example); "
            "the backup cannot be encrypted or decrypted without it."
        )
    if creating and len(value) < MIN_PASSPHRASE_LENGTH:
        raise PassphraseError(
            f"{ENV_NAME} must be at least {MIN_PASSPHRASE_LENGTH} characters to write a backup"
        )
    return value


def main(argv=None) -> int:
    """Report whether the passphrase is set. The value itself is never printed."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--check", action="store_true", help="report set / not set")
    parser.parse_args(argv)
    try:
        get_passphrase()
    except PassphraseError as exc:
        print(f"not set: {exc}", file=sys.stderr)
        return 2
    print("set")
    return 0


if __name__ == "__main__":
    sys.exit(main())
