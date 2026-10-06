"""Backup passphrase handling for the encrypted backup scripts.

The passphrase lives in the Windows Credential Manager (via the `keyring` package, DPAPI
protected, readable only by this Windows user) under service ``OntoSage-backup`` and
username ``bldg1``. It is never read from ``.env`` and never written into the repository.

First-time setup (prints nothing secret)::

    .venv\\Scripts\\python.exe scripts\\_backup_secret.py --set

Check whether a passphrase is stored (prints yes/no only)::

    .venv\\Scripts\\python.exe scripts\\_backup_secret.py --check

A scheduled run cannot prompt, so it fails with exit code 2 when nothing is stored.
"""

import argparse
import getpass
import sys
from typing import Any, Callable, Optional

SERVICE = "OntoSage-backup"
USERNAME = "bldg1"
MIN_LENGTH = 12


class PassphraseError(Exception):
    """No usable passphrase could be obtained."""


def _default_keyring() -> Any:
    try:
        import keyring
    except ImportError as exc:
        raise PassphraseError(
            "the 'keyring' package is not installed in this interpreter "
            "(.venv\\Scripts\\python.exe -m pip install keyring)"
        ) from exc
    return keyring


def get_passphrase(
    *,
    creating: bool = False,
    interactive: Optional[bool] = None,
    keyring_mod: Any = None,
    prompt: Callable[[str], str] = getpass.getpass,
    input_fn: Callable[[str], str] = input,
    service: str = SERVICE,
    username: str = USERNAME,
) -> str:
    """Return the backup passphrase from the Credential Manager, or prompt for it.

    creating=True asks twice, enforces MIN_LENGTH, and offers to store the result. It is
    used when writing a new archive. creating=False (restore) prompts once and only offers
    to store when nothing is stored yet.
    """
    kr = keyring_mod if keyring_mod is not None else _default_keyring()
    try:
        stored = kr.get_password(service, username)
    except Exception as exc:  # keyring backends raise a family of errors
        raise PassphraseError(f"Credential Manager unavailable: {type(exc).__name__}") from exc
    if stored:
        return stored

    if interactive is None:
        interactive = sys.stdin is not None and sys.stdin.isatty()
    if not interactive:
        raise PassphraseError(
            "no backup passphrase stored. Run: "
            ".venv\\Scripts\\python.exe scripts\\_backup_secret.py --set"
        )

    first = prompt("Backup passphrase: ")
    if creating:
        second = prompt("Repeat passphrase: ")
        if first != second:
            raise PassphraseError("passphrases do not match")
        if len(first) < MIN_LENGTH:
            raise PassphraseError(f"passphrase must be at least {MIN_LENGTH} characters")
    if not first:
        raise PassphraseError("empty passphrase")

    answer = input_fn("Store it in the Windows Credential Manager for this user? [y/N] ")
    if answer.strip().lower() in ("y", "yes"):
        try:
            kr.set_password(service, username, first)
            print("Stored in Credential Manager.")
        except Exception as exc:
            print(f"Could not store it ({type(exc).__name__}); using it for this run only.")
    return first


def main(argv=None) -> int:
    """Set or check the stored passphrase. The value itself is never printed."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--set", action="store_true", help="prompt and store a new passphrase")
    group.add_argument("--check", action="store_true", help="report whether one is stored")
    args = parser.parse_args(argv)
    try:
        kr = _default_keyring()
        if args.check:
            present = bool(kr.get_password(SERVICE, USERNAME))
            print("stored" if present else "not stored")
            return 0 if present else 2
        existing = kr.get_password(SERVICE, USERNAME)
        if existing:
            print("A passphrase is already stored. Overwrite it? Existing backups still need it.")
            if input("Overwrite? [y/N] ").strip().lower() not in ("y", "yes"):
                return 0
        first = getpass.getpass("New backup passphrase: ")
        second = getpass.getpass("Repeat: ")
        if first != second or len(first) < MIN_LENGTH:
            print(f"Refused: passphrases differ or are shorter than {MIN_LENGTH} characters.")
            return 2
        kr.set_password(SERVICE, USERNAME, first)
        print("Stored in Windows Credential Manager.")
        return 0
    except PassphraseError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
