#!/usr/bin/env python3
"""Replace the shipped placeholder credentials in an env file with random values (B1).

Only keys whose value is still a template placeholder (``CHANGE-ME``, ``YOUR_...``) or a
known shipped default are rewritten. Empty values stay empty (the integration is simply
not configured) and third-party provider keys (OpenAI, Ollama Cloud, Tavily) are never
touched, because a random value there is not a credential we can generate.

Every other line, comment and line ending is preserved byte for byte. Only the NAMES of
the keys changed are printed; values never are.

    python scripts/generate_secrets.py                 # rewrites .env1 in the repo root
    python scripts/generate_secrets.py --env .env1 --dry-run
    python scripts/generate_secrets.py --force         # also rotate SECRET_KEY etc. holding real values

Caution, and the reason this is not run automatically: the stateful stores (MySQL,
PostgreSQL, GraphDB) read their passwords only when their volume is first initialised.
Rotating MYSQL_PASSWORD in the env file does not change the password the database already
has, so the orchestrator then fails to connect. Those keys need the store changed too.
"""

from __future__ import annotations

import argparse
import re
import secrets
import sys
from pathlib import Path
from typing import List, Optional, Tuple

REPO_ROOT = Path(__file__).resolve().parents[1]

#: Always generated when they hold a placeholder, a shipped default, or are missing.
ALWAYS_KEYS = ("SECRET_KEY", "WEBUI_SECRET_KEY", "PIPELINE_API_KEY")

#: Third-party provider keys. A random string here is not a valid credential for anyone.
PROVIDER_KEYS = {"OPENAI_API_KEY", "OLLAMA_CLOUD_API_KEY", "TAVILY_API_KEY"}

#: Values shipped in the code or the templates as defaults.
KNOWN_DEFAULTS = {
    "Admin@GraphDB2024",
    "ontobot_secret",
    "mysql",
    "sk-ontobot-pipeline",
    "change-me-in-production-use-32-random-bytes",
    "changeme",
    "password",
    "secret",
}

_PLACEHOLDER_RE = re.compile(r"^(CHANGE[-_]?ME|YOUR[_-])", re.IGNORECASE)
_LINE_RE = re.compile(r"^(?P<key>[A-Z][A-Z0-9_]*)=(?P<rest>.*?)(?P<eol>\r?\n?)$", re.DOTALL)


def _is_credential_name(name: str) -> bool:
    if name in PROVIDER_KEYS or name == "STRICT_SECRETS":
        return False
    if name in ALWAYS_KEYS or name == "API_KEY":
        return True
    return name.endswith(("PASSWORD", "PASSWD"))


def _split_value(rest: str) -> Tuple[str, str]:
    """Separate the value from an inline ``# comment`` so the comment survives."""
    idx = rest.find(" #")
    if idx == -1:
        return rest, ""
    return rest[:idx], rest[idx:]


def _is_default(value: str) -> bool:
    bare = value.strip().strip("\"'")
    # Empty is NOT a default: it means "this integration is not configured".
    return bool(bare) and (bool(_PLACEHOLDER_RE.match(bare)) or bare in KNOWN_DEFAULTS)


def _generate() -> str:
    # URL-safe: no spaces, quotes or '#', so it survives every env-file reader.
    return secrets.token_urlsafe(48)


def rotate_text(text: str, force: bool = False) -> Tuple[str, List[str]]:
    """Return ``(new_text, names_rotated)``. Pure: touches no file and prints nothing."""
    lines = text.splitlines(keepends=True)
    rotated: List[str] = []
    present = set()
    out: List[str] = []
    for line in lines:
        m = _LINE_RE.match(line)
        if not m:
            out.append(line)
            continue
        key = m.group("key")
        present.add(key)
        if key not in ALWAYS_KEYS and not _is_credential_name(key):
            out.append(line)
            continue
        value, comment = _split_value(m.group("rest"))
        if not ((force and key in ALWAYS_KEYS) or _is_default(value)):
            out.append(line)
            continue
        rotated.append(key)
        out.append(f"{key}={_generate()}{comment}{m.group('eol')}")

    # An always-key the file lacks is appended, not silently skipped.
    eol = "\r\n" if "\r\n" in text else "\n"
    for key in ALWAYS_KEYS:
        if key in present:
            continue
        if out and not out[-1].endswith(("\n", "\r")):
            out[-1] = out[-1] + eol
        out.append(f"{key}={_generate()}{eol}")
        rotated.append(key)
    return "".join(out), rotated


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--env", default=str(REPO_ROOT / ".env1"), help="env file to rewrite")
    parser.add_argument("--dry-run", action="store_true", help="report names only, write nothing")
    parser.add_argument(
        "--force",
        action="store_true",
        help="also rotate SECRET_KEY/WEBUI_SECRET_KEY/PIPELINE_API_KEY holding real values",
    )
    args = parser.parse_args(argv)

    path = Path(args.env)
    if not path.is_file():
        print(f"error: {path} does not exist", file=sys.stderr)
        return 2
    text = path.read_text(encoding="utf-8")
    new_text, rotated = rotate_text(text, force=args.force)

    if not rotated:
        print(f"{path.name}: no placeholder credentials found; nothing changed")
        return 0
    verb = "would rotate" if args.dry_run else "rotated"
    print(f"{path.name}: {verb} {len(rotated)} key(s): {', '.join(rotated)}")
    if not args.dry_run:
        path.write_text(new_text, encoding="utf-8", newline="")
    print(
        "NOTE: MySQL, PostgreSQL and GraphDB read their passwords only when their volume is "
        "first initialised. Rotating those keys here does not change the stored password; "
        "change the store too or the orchestrator cannot connect."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
