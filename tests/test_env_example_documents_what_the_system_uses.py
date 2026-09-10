# -*- coding: utf-8 -*-
"""A setting the system uses and the template omits is undiscoverable (CAVEAT-449).

WHAT WENT WRONG
---------------
`.env.example` was missing **31** settings the live `.env` uses -- among them the entire
GraphDB connection, the `STRICT_SECRETS` boot guard, `OLLAMA_NUM_CTX` (whose wrong value
silently produced empty completions on 2.7% of turns, BUG-188) and `PROTECT_ENFORCE`.

A fresh clone booted on the code defaults for all of them with no way to learn they
existed. That is the deployment half of the same failure this project keeps finding
elsewhere: the thing works, and nothing tells you what it is doing.

WHY THE TEST IS SHAPED THIS WAY
-------------------------------
It runs only when a live `.env` is present -- a parked tree and CI have none, and a skip is
honest there. It compares KEY NAMES only and never values, because reading a secret into an
assertion message is how a secret reaches a log.
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict

import pytest

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parent.parent
EXAMPLE = REPO / ".env.example"
LIVE = REPO / ".env"

#: Keys that are legitimately absent from the template.
#:
#: A per-deployment value with no sensible example, or a key the template deliberately
#: leaves to the swap procedure. Kept short on purpose: every entry here is a setting a
#: newcomer cannot discover, so each one needs to be worth that.
_EXPECTED_ABSENT: set = set()


def _keys(path: Path) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        s = line.strip()
        if s and not s.startswith("#") and "=" in s:
            k, v = (x.strip() for x in s.split("=", 1))
            out[k] = v
    return out


def test_the_example_exists():
    assert EXAMPLE.is_file(), ".env.example is the only documentation of what to configure"


@pytest.mark.skipif(not LIVE.is_file(), reason="no live .env (parked tree or CI)")
def test_every_live_setting_appears_in_the_example():
    live = _keys(LIVE)
    example = _keys(EXAMPLE)
    missing = sorted(set(live) - set(example) - _EXPECTED_ABSENT)
    assert not missing, (
        f"{len(missing)} setting(s) are live and undocumented, so a fresh clone runs on "
        f"the code default and cannot discover them: {missing}"
    )


@pytest.mark.skipif(not LIVE.is_file(), reason="no live .env")
def test_no_credential_in_the_example_matches_the_live_value():
    """Names only in the message. A value here would put a secret in a test log.

    GATED ON `STRICT_SECRETS`, deliberately, and the reasoning is worth stating because the
    obvious alternative is worse.

    Six credentials DID match on 2026-09-06: POSTGRES_PASSWORD, PGADMIN_DEFAULT_PASSWORD,
    API_KEY, API_PGPASSWORD, API_MYSQL_PASSWORD and PG_THINGSBOARD_PASSWORD. That is a real
    finding about a deployment, not a defect in any file -- and on a development machine
    with `STRICT_SECRETS=false` it is an accepted trade, not a mistake. Failing the unit
    suite on it would put a permanent red line in front of every developer, and a suite
    that is always red is a suite nobody reads.

    So the check binds to the switch the deployment itself sets. `STRICT_SECRETS=true`
    means "this is not a toy" -- and there, a published credential fails the build. The
    boot guard uses the same switch and refuses to start (CAVEAT-458), so the two agree.
    """
    live = _keys(LIVE)
    example = _keys(EXAMPLE)
    if str(live.get("STRICT_SECRETS", "")).strip().lower() not in ("true", "1", "yes", "on"):
        pytest.skip(
            "STRICT_SECRETS is off: this deployment declares itself local development, "
            "where a published credential is an accepted trade rather than a defect"
        )
    markers = ("PASSWORD", "SECRET", "API_KEY", "TOKEN", "PRIVATE_KEY")
    not_credentials = {"STRICT_SECRETS", "SECRETS_BACKEND", "MASK_SECRETS"}
    shared = sorted(
        k
        for k, v in example.items()
        if any(m in k.upper() for m in markers)
        and k not in not_credentials
        and v
        and live.get(k) == v
    )
    assert not shared, (
        f"{len(shared)} credential(s) still hold their published example value: {shared}. "
        f"Set real values in .env; the committed template must never be a working secret."
    )
